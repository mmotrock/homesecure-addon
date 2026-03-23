"""
HomeSecure — One-Time Data Migration
Runs automatically on first container startup if the old integration database
exists at /config/homesecure.db and the container database at
/data/homesecure.db has no users yet.

What gets migrated:
  ✓ alarm_users          (preserves bcrypt hashes — no re-enrollment needed)
  ✓ alarm_config         (all timing + notification settings)
  ✓ user_lock_slots      (slot assignments survive intact)
  ✓ user_lock_access     (per-lock enable/disable state + sync status)
  ✓ alarm_events         (last 500 events for continuity)

What is intentionally NOT migrated:
  ✗ failed_attempts      (stale lockout state — better to start clean)
  ✗ service_pin          (container generates its own)
"""
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Optional

_LOGGER = logging.getLogger(__name__)

OLD_DB_PATH = "/config/homesecure.db"   # written by the old HA integration
NEW_DB_PATH = "/data/homesecure.db"     # owned by the container
MIGRATION_FLAG = "/data/.migration_done"


def _conn(path: str, row_factory: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    if row_factory:
        conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")   # skip FK checks during bulk copy
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row["name"] == column for row in cur.fetchall())


# ── per-table migration helpers ───────────────────────────────────────────────

def _migrate_users(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    if not _table_exists(src, "alarm_users"):
        return 0

    src_cur = src.execute("SELECT * FROM alarm_users")
    rows = src_cur.fetchall()
    if not rows:
        return 0

    columns = [d[0] for d in src_cur.description]
    # Build INSERT that works regardless of minor schema differences
    placeholders = ",".join("?" * len(columns))
    col_list = ",".join(columns)

    count = 0
    dst_cur = dst.cursor()
    for row in rows:
        try:
            dst_cur.execute(
                f"INSERT OR IGNORE INTO alarm_users ({col_list}) VALUES ({placeholders})",
                tuple(row),
            )
            count += dst_cur.rowcount
        except Exception as exc:
            _LOGGER.warning("Skipping user row (id=%s): %s", row["id"], exc)

    dst.commit()
    return count


def _migrate_config(src: sqlite3.Connection, dst: sqlite3.Connection) -> bool:
    if not _table_exists(src, "alarm_config"):
        return False

    row = src.execute("SELECT * FROM alarm_config WHERE id=1").fetchone()
    if not row:
        return False

    # Get destination columns (may differ slightly)
    dst_cols_cur = dst.execute("PRAGMA table_info(alarm_config)")
    dst_cols = {r["name"] for r in dst_cols_cur.fetchall()}

    src_cols = [d[0] for d in src.execute("SELECT * FROM alarm_config LIMIT 0").description]
    transferable = [c for c in src_cols if c in dst_cols and c not in ("id", "service_pin")]

    set_clause = ", ".join(f"{c}=?" for c in transferable)
    values = [row[c] for c in transferable]

    dst.execute(f"UPDATE alarm_config SET {set_clause} WHERE id=1", values)
    dst.commit()
    return True


def _migrate_lock_slots(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    if not _table_exists(src, "user_lock_slots"):
        return 0

    rows = src.execute("SELECT * FROM user_lock_slots").fetchall()
    count = 0
    for row in rows:
        try:
            dst.execute(
                """
                INSERT OR IGNORE INTO user_lock_slots
                (user_id, slot_number, assigned_at, last_synced)
                VALUES (?, ?, ?, ?)
                """,
                (row["user_id"], row["slot_number"],
                 row["assigned_at"], row["last_synced"]),
            )
            count += dst.execute("SELECT changes()").fetchone()[0]
        except Exception as exc:
            _LOGGER.warning("Skipping lock slot row: %s", exc)
    dst.commit()
    return count


def _migrate_lock_access(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    if not _table_exists(src, "user_lock_access"):
        return 0

    rows = src.execute("SELECT * FROM user_lock_access").fetchall()
    count = 0
    for row in rows:
        try:
            dst.execute(
                """
                INSERT OR IGNORE INTO user_lock_access
                (user_id, lock_entity_id, enabled,
                 last_synced, last_sync_success, last_sync_error,
                 created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    row["user_id"], row["lock_entity_id"], row["enabled"],
                    row["last_synced"], row["last_sync_success"],
                    row["last_sync_error"], row["created_at"], row["updated_at"],
                ),
            )
            count += dst.execute("SELECT changes()").fetchone()[0]
        except Exception as exc:
            _LOGGER.warning("Skipping lock access row: %s", exc)
    dst.commit()
    return count


def _migrate_events(
    src: sqlite3.Connection, dst: sqlite3.Connection, limit: int = 500
) -> int:
    if not _table_exists(src, "alarm_events"):
        return 0

    rows = src.execute(
        "SELECT * FROM alarm_events ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()

    count = 0
    for row in rows:
        try:
            dst.execute(
                """
                INSERT OR IGNORE INTO alarm_events
                (id, event_type, user_id, user_name, timestamp,
                 state_from, state_to, zone_entity_id, details, is_duress)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["id"], row["event_type"], row["user_id"], row["user_name"],
                    row["timestamp"], row["state_from"], row["state_to"],
                    row["zone_entity_id"], row["details"], row["is_duress"],
                ),
            )
            count += dst.execute("SELECT changes()").fetchone()[0]
        except Exception as exc:
            _LOGGER.warning("Skipping event row (id=%s): %s", row["id"], exc)
    dst.commit()
    return count


# ── public entry point ────────────────────────────────────────────────────────

def should_migrate() -> bool:
    """Return True if migration should run."""
    if Path(MIGRATION_FLAG).exists():
        return False
    if not Path(OLD_DB_PATH).exists():
        _LOGGER.debug("No old database found at %s — skipping migration", OLD_DB_PATH)
        return False
    # Only migrate if the new DB has no users yet
    if Path(NEW_DB_PATH).exists():
        try:
            with _conn(NEW_DB_PATH) as dst:
                if _table_exists(dst, "alarm_users"):
                    count = dst.execute("SELECT COUNT(*) FROM alarm_users").fetchone()[0]
                    if count > 0:
                        _LOGGER.info(
                            "Container DB already has %d user(s) — skipping migration",
                            count,
                        )
                        Path(MIGRATION_FLAG).touch()
                        return False
        except Exception as exc:
            _LOGGER.warning("Could not check destination DB: %s", exc)
    return True


def run_migration(
    old_db: str = OLD_DB_PATH,
    new_db: str = NEW_DB_PATH,
) -> bool:
    """
    Copy data from the old HA integration DB into the container DB.
    Returns True on success, False on failure.
    The container DB must already be initialised (schema created) before
    calling this — call AlarmDatabase(new_db) first.
    """
    _LOGGER.info("=" * 60)
    _LOGGER.info("HomeSecure data migration starting")
    _LOGGER.info("  Source : %s", old_db)
    _LOGGER.info("  Target : %s", new_db)
    _LOGGER.info("=" * 60)

    # Back up the old DB so we can never lose data
    backup = old_db + ".pre_migration_backup"
    try:
        shutil.copy2(old_db, backup)
        _LOGGER.info("Backup created: %s", backup)
    except Exception as exc:
        _LOGGER.error("Cannot create backup — aborting migration: %s", exc)
        return False

    try:
        src = _conn(old_db)
        dst = _conn(new_db)

        users   = _migrate_users(src, dst)
        config  = _migrate_config(src, dst)
        slots   = _migrate_lock_slots(src, dst)
        access  = _migrate_lock_access(src, dst)
        events  = _migrate_events(src, dst)

        src.close()
        dst.close()

        _LOGGER.info("Migration complete:")
        _LOGGER.info("  Users migrated        : %d", users)
        _LOGGER.info("  Config migrated       : %s", "yes" if config else "no")
        _LOGGER.info("  Lock slots migrated   : %d", slots)
        _LOGGER.info("  Lock access migrated  : %d", access)
        _LOGGER.info("  Events migrated       : %d", events)
        _LOGGER.info("=" * 60)

        # Leave the migration flag so we never run again
        Path(MIGRATION_FLAG).touch()
        return True

    except Exception as exc:
        _LOGGER.error("Migration failed: %s", exc, exc_info=True)
        return False


# ── allow running standalone for manual/test migrations ──────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")
    old = sys.argv[1] if len(sys.argv) > 1 else OLD_DB_PATH
    new = sys.argv[2] if len(sys.argv) > 2 else NEW_DB_PATH
    ok = run_migration(old, new)
    sys.exit(0 if ok else 1)
