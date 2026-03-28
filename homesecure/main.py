"""
HomeSecure Container — main entrypoint
Wires together the database, alarm coordinator, lock manager, and API server.
Run with:  python3 main.py
"""
import asyncio
import logging
import os
import secrets
import sys

from database import AlarmDatabase
from alarm_coordinator import AlarmCoordinator
from lock_manager import LockManager
from api_server import APIServer
from migrate import should_migrate, run_migration

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
_LOGGER = logging.getLogger("homesecure.main")


def _get_or_create_service_pin(db: AlarmDatabase) -> str:
    """Return the stored service PIN, creating and persisting one if absent."""
    cfg = db.get_config()
    pin = cfg.get("service_pin")
    if not pin:
        pin = "".join(str(secrets.randbelow(10)) for _ in range(8))
        db.update_config({"service_pin": pin})
        _LOGGER.info("Generated new service PIN (stored in DB, not logged)")
    return pin



async def _broadcast_loop(event_queue: asyncio.Queue, api_server: APIServer) -> None:
    """Relay coordinator events to all connected WebSocket clients."""
    while True:
        try:
            payload = await event_queue.get()
            await api_server.broadcast(payload)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            _LOGGER.error("Broadcast error: %s", exc)


async def _periodic_lock_sync(lock_manager: LockManager, db: AlarmDatabase) -> None:
    """Re-verify lock codes against Z-Wave JS on a configurable interval."""
    while True:
        try:
            interval = db.get_lock_sync_config()
            await asyncio.sleep(interval)
            _LOGGER.debug("Running periodic lock sync (interval=%ds)", interval)
            results = await lock_manager.periodic_lock_sync()
            _LOGGER.info("Periodic lock sync: %s", results)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            _LOGGER.error("Periodic lock sync error: %s", exc)


async def main() -> None:
    # ── config from environment ───────────────────────────────────────────
    db_path    = os.environ.get("DB_PATH",      "/data/homesecure.db")
    zwave_url  = os.environ.get("ZWAVE_URL",    "ws://a0d7b954-zwavejs2mqtt:3000")
    api_host   = os.environ.get("API_HOST",     "0.0.0.0")
    api_port   = int(os.environ.get("API_PORT", "8099"))

    _LOGGER.info("=== HomeSecure Container starting ===")
    _LOGGER.info("DB:       %s", db_path)
    _LOGGER.info("Z-Wave:   %s", zwave_url)
    _LOGGER.info("API:      %s:%d", api_host, api_port)
    _LOGGER.info(
        "Token auth: %s",
        "ENABLED" if os.environ.get("HOMESECURE_API_TOKEN") else "DISABLED (no token set)",
    )
    _LOGGER.info(
        "Trusted networks (zone trigger): %s",
        os.environ.get(
            "HOMESECURE_TRUSTED_NETWORKS",
            "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 (default)",
        ),
    )

    # ── one-time data migration ───────────────────────────────────────────
    if should_migrate():
        AlarmDatabase(db_path)   # create schema first
        if not run_migration():
            _LOGGER.warning("Migration had errors — continuing with partial data")

    # ── initialise components ─────────────────────────────────────────────
    database    = AlarmDatabase(db_path)
    users        = database.get_users()
    failed_count = database.get_failed_attempts_count()
    locked_out   = database.is_locked_out()
    if users:
        _LOGGER.info("Existing database — %d user(s) configured", len(users))
        if locked_out:
            _LOGGER.warning(
                "⚠ System is LOCKED OUT (%d failed attempts) — "
                "clear via GET /api/debug/status or wait for lockout to expire",
                failed_count,
            )
    else:
        _LOGGER.warning("Fresh database — no users configured yet")
        _LOGGER.warning("Install the HomeSecure integration to create your first admin user")
        if failed_count > 0:
            _LOGGER.warning(
                "Clearing %d stale failed attempts from previous install", failed_count
            )
            database.clear_failed_attempts()
    _get_or_create_service_pin(database)

    event_queue = asyncio.Queue()
    coordinator = AlarmCoordinator(database, event_queue)
    lock_mgr    = LockManager(database, zwave_url)
    api_server  = APIServer(coordinator, lock_mgr, database)

    # Connect Z-Wave JS and start the API server
    await lock_mgr.async_setup()
    await api_server.start(api_host, api_port)

    _LOGGER.info("=== HomeSecure Container ready ===")

    # ── background tasks ──────────────────────────────────────────────────
    tasks = [
        asyncio.create_task(_broadcast_loop(event_queue, api_server),
                            name="broadcast"),
        asyncio.create_task(_periodic_lock_sync(lock_mgr, database),
                            name="lock_sync"),
    ]

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        _LOGGER.info("Shutting down …")
    finally:
        for t in tasks:
            t.cancel()
        await lock_mgr.async_shutdown()
        _LOGGER.info("=== HomeSecure Container stopped ===")


if __name__ == "__main__":
    asyncio.run(main())
