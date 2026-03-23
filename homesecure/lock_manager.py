"""
HomeSecure Container Lock Manager
Standalone Z-Wave JS lock management — no Home Assistant dependency.
Owns a direct WebSocket connection to the Z-Wave JS server.
"""
import asyncio
import logging
from typing import Optional, Dict, List, Any

from zwave_js_server.client import Client as ZwaveClient
from zwave_js_server.model.node import Node as ZwaveNode
from zwave_js_server.model.value import Value as ZwaveValue
from zwave_js_server.const import CommandClass
import aiohttp

_LOGGER = logging.getLogger(__name__)


class LockManager:
    """
    Manages Z-Wave JS lock user codes synced with alarm system users.

    Lifecycle:
        manager = LockManager(db, zwave_url)
        await manager.async_setup()          # connect + discover
        ...
        await manager.async_shutdown()       # clean disconnect
    """

    def __init__(self, database, zwave_server_url: str = "ws://localhost:3000"):
        self.database = database
        self._zwave_server_url = zwave_server_url
        self._zwave_client: Optional[ZwaveClient] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._managed_locks: List[str] = []   # entity_id strings (cosmetic / DB keys)
        self._lock_nodes: Dict[str, ZwaveNode] = {}  # entity_id → ZwaveNode
        self._sync_lock = asyncio.Lock()
        self._pin_cache: Dict[int, str] = {}

    # ------------------------------------------------------------------ #
    #  Setup / teardown                                                    #
    # ------------------------------------------------------------------ #

    async def async_setup(self) -> None:
        """Connect to Z-Wave JS and discover managed locks."""
        self._session = aiohttp.ClientSession()
        await self._connect_zwave_server()
        await self._discover_locks()
        # M3: start background reconnect task so Z-Wave JS restarts are handled
        self._reconnect_task = asyncio.create_task(
            self._reconnect_loop(), name="zwave_reconnect"
        )
        _LOGGER.info("Lock manager ready — %d lock(s) managed", len(self._managed_locks))

    async def async_shutdown(self) -> None:
        """Disconnect cleanly."""
        if hasattr(self, "_reconnect_task") and self._reconnect_task:
            self._reconnect_task.cancel()
        if self._zwave_client:
            try:
                await self._zwave_client.disconnect()
            except Exception:
                pass
        if self._session:
            await self._session.close()
        _LOGGER.info("Lock manager shut down")

    async def _reconnect_loop(self) -> None:
        """M3: Periodically attempt to reconnect to Z-Wave JS if disconnected."""
        delay = 30
        while True:
            try:
                await asyncio.sleep(delay)
                if self._zwave_client is None:
                    _LOGGER.info(
                        "Z-Wave JS disconnected — attempting reconnect (delay was %ds)", delay
                    )
                    await self._connect_zwave_server()
                    if self._zwave_client:
                        await self._discover_locks()
                        _LOGGER.info(
                            "Z-Wave JS reconnected — %d lock(s) rediscovered",
                            len(self._managed_locks),
                        )
                        delay = 30  # reset backoff on success
                    else:
                        delay = min(delay * 2, 300)  # exponential backoff up to 5 min
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _LOGGER.error("Reconnect loop error: %s", exc)
                delay = min(delay * 2, 300)

    # ------------------------------------------------------------------ #
    #  Z-Wave JS connection                                                #
    # ------------------------------------------------------------------ #

    async def _connect_zwave_server(self) -> None:
        """Open a WebSocket connection to the Z-Wave JS server."""
        try:
            self._zwave_client = ZwaveClient(self._zwave_server_url, self._session)
            _LOGGER.info("Connecting to Z-Wave JS server at %s …", self._zwave_server_url)
            await self._zwave_client.connect()

            # If driver is immediately ready we're done.
            if self._zwave_client.driver:
                nodes = len(self._zwave_client.driver.controller.nodes)
                _LOGGER.info("Z-Wave JS driver ready — %d node(s)", nodes)
                return

            # Otherwise wait for the driver-ready event.
            driver_ready = asyncio.Event()
            self._zwave_client.driver_events.on(
                "driver ready", lambda: driver_ready.set()
            )

            try:
                await asyncio.wait_for(driver_ready.wait(), timeout=30.0)
                nodes = len(self._zwave_client.driver.controller.nodes)
                _LOGGER.info("Z-Wave JS driver ready — %d node(s)", nodes)
            except asyncio.TimeoutError:
                _LOGGER.error(
                    "Timed out waiting for Z-Wave JS driver ready. "
                    "Lock features will be unavailable until next restart."
                )
                self._zwave_client = None

        except Exception as exc:
            _LOGGER.error("Failed to connect to Z-Wave JS: %s", exc, exc_info=True)
            self._zwave_client = None

    # ------------------------------------------------------------------ #
    #  Lock discovery                                                      #
    # ------------------------------------------------------------------ #

    async def _discover_locks(self) -> None:
        """
        Discover all Z-Wave nodes that support the DOOR_LOCK command class.

        Without Home Assistant's entity registry we work directly against the
        Z-Wave JS node list.  We store each lock using the entity_id pattern
        'lock.<node_id>' so the rest of the code can use string keys as before,
        and the Lovelace cards / HA integration can map back by node_id.
        """
        self._managed_locks = []
        self._lock_nodes = {}

        if not self._zwave_client or not self._zwave_client.driver:
            _LOGGER.warning("Z-Wave JS not available — skipping lock discovery")
            return

        for node_id, node in self._zwave_client.driver.controller.nodes.items():
            if CommandClass.DOOR_LOCK not in node.command_classes:
                continue

            entity_id = f"lock.node_{node_id}"
            self._managed_locks.append(entity_id)
            self._lock_nodes[entity_id] = node
            desc = getattr(node.device_config, "description", f"Node {node_id}")
            _LOGGER.info("Discovered lock: %s (%s)", entity_id, desc)

        _LOGGER.info("Lock discovery complete — %d lock(s)", len(self._managed_locks))

    # ------------------------------------------------------------------ #
    #  Internal Z-Wave helpers                                             #
    # ------------------------------------------------------------------ #

    def _get_usercode_value(self, node: ZwaveNode, slot: int) -> Optional[ZwaveValue]:
        for v in node.values.values():
            if (v.command_class == CommandClass.USER_CODE
                    and v.property_ == "userCode"
                    and v.property_key == slot):
                return v
        return None

    def _get_userid_status_value(self, node: ZwaveNode, slot: int) -> Optional[ZwaveValue]:
        for v in node.values.values():
            if (v.command_class == CommandClass.USER_CODE
                    and v.property_ == "userIdStatus"
                    and v.property_key == slot):
                return v
        return None

    async def _set_lock_code(
        self, entity_id: str, slot: int, name: str, pin: str
    ) -> bool:
        node = self._lock_nodes.get(entity_id)
        if not node:
            _LOGGER.error("No Z-Wave node for %s", entity_id)
            return False
        try:
            status_val = self._get_userid_status_value(node, slot)
            if status_val:
                await node.async_set_value(status_val.value_id, 1)

            code_val = self._get_usercode_value(node, slot)
            if not code_val:
                _LOGGER.error("No usercode value for slot %d on %s", slot, entity_id)
                return False

            await node.async_set_value(code_val.value_id, pin)
            _LOGGER.info("Set lock code for %s in slot %d on %s", name, slot, entity_id)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to set lock code on %s slot %d: %s", entity_id, slot, exc)
            return False

    async def _clear_lock_code(self, entity_id: str, slot: int) -> bool:
        node = self._lock_nodes.get(entity_id)
        if not node:
            return False
        try:
            status_val = self._get_userid_status_value(node, slot)
            if status_val:
                await node.async_set_value(status_val.value_id, 0)

            code_val = self._get_usercode_value(node, slot)
            if code_val:
                await node.async_set_value(code_val.value_id, "")
            return True
        except Exception as exc:
            _LOGGER.debug("Failed to clear slot %d on %s: %s", slot, entity_id, exc)
            return False

    async def _find_available_slot(self, entity_id: str) -> Optional[int]:
        assigned = self.database.get_assigned_slots()
        node = self._lock_nodes.get(entity_id)
        if not node:
            return None

        occupied: set = set()
        for v in node.values.values():
            if (v.command_class == CommandClass.USER_CODE
                    and v.property_ == "userCode"
                    and v.property_key is not None
                    and v.value):
                raw = str(v.value)
                pin = raw.split(":")[0] if ":" in raw else raw
                if pin and pin != "0" * len(pin):
                    occupied.add(v.property_key)

        for slot in range(1, 31):
            if slot not in assigned and slot not in occupied:
                return slot
        for slot in range(1, 31):
            if slot not in occupied:
                return slot
        return None

    # ------------------------------------------------------------------ #
    #  Public API — called by the API server                              #
    # ------------------------------------------------------------------ #

    def get_managed_locks(self) -> List[str]:
        return list(self._managed_locks)

    def cache_pin(self, user_id: int, pin: str) -> None:
        self._pin_cache[user_id] = pin

    def clear_pin_cache(self, user_id: Optional[int] = None) -> None:
        if user_id is None:
            self._pin_cache.clear()
        else:
            self._pin_cache.pop(user_id, None)

    async def get_user_pin_from_lock(
        self, user_id: int, entity_id: Optional[str] = None
    ) -> Optional[str]:
        """Read the PIN currently programmed into a lock slot."""
        if not self._managed_locks:
            return None
        slot = self.database.get_user_lock_slot(user_id)
        if slot is None:
            return None
        target = entity_id or self._managed_locks[0]
        node = self._lock_nodes.get(target)
        if not node:
            return None
        try:
            val = self._get_usercode_value(node, slot)
            if val and val.value:
                raw = str(val.value)
                pin = raw.split(":")[0] if ":" in raw else raw
                if pin and pin != "0" * len(pin):
                    return pin
        except Exception as exc:
            _LOGGER.warning("Error reading pin from %s slot %d: %s", target, slot, exc)
        return None

    async def sync_user_to_locks(
        self,
        user_id: int,
        pin: Optional[str] = None,
        lock_pin: Optional[str] = None,
    ) -> None:
        """Sync a user's code to all managed locks."""
        async with self._sync_lock:
            users = self.database.get_users()
            user = next((u for u in users if u["id"] == user_id), None)
            if not user or not user["enabled"]:
                if user:
                    await self._remove_user_from_locks(user_id, user["name"])
                return

            code = (lock_pin if user.get("has_separate_lock_pin") and lock_pin else pin)
            if not code or len(code) < 4:
                _LOGGER.warning("No valid PIN for user %s — skipping sync", user["name"])
                return

            slot = self.database.get_user_lock_slot(user_id)
            if slot is None and self._managed_locks:
                slot = await self._find_available_slot(self._managed_locks[0])
                if slot is None:
                    _LOGGER.error("No free lock slots for %s", user["name"])
                    return
                self.database.assign_lock_slot(user_id, slot)
                _LOGGER.info("Assigned slot %d to %s", slot, user["name"])

            synced = []
            for eid in self._managed_locks:
                if await self._set_lock_code(eid, slot, user["name"], code):
                    synced.append(eid)

            _LOGGER.info(
                "Synced %s to %d/%d lock(s) in slot %d",
                user["name"], len(synced), len(self._managed_locks), slot,
            )
            if synced:
                self.database.initialize_user_lock_access(user_id, synced)

    async def remove_user_from_locks(self, user_id: int) -> None:
        async with self._sync_lock:
            users = self.database.get_users()
            user = next((u for u in users if u["id"] == user_id), None)
            name = user["name"] if user else f"User {user_id}"
            await self._remove_user_from_locks(user_id, name)

    async def _remove_user_from_locks(self, user_id: int, name: str) -> None:
        slot = self.database.get_user_lock_slot(user_id)
        if slot is None:
            return
        for eid in self._managed_locks:
            await self._clear_lock_code(eid, slot)
        self.database.remove_lock_slot(user_id)
        _LOGGER.info("Removed %s from all locks (slot %d)", name, slot)

    async def set_user_lock_enabled(
        self, user_id: int, entity_id: str, enabled: bool
    ) -> bool:
        """Enable/disable a user on one specific lock (updates DB + syncs async)."""
        ok = self.database.set_user_lock_access(user_id, entity_id, enabled)
        if not ok:
            return False
        asyncio.create_task(
            self._sync_lock_access_background(user_id, entity_id, enabled)
        )
        return True

    async def _sync_lock_access_background(
        self, user_id: int, entity_id: str, enabled: bool
    ) -> None:
        slot = self.database.get_user_lock_slot(user_id)
        if slot is None:
            self.database.update_lock_sync_status(
                user_id, entity_id, False, "No slot assigned"
            )
            return

        users = self.database.get_users()
        user = next((u for u in users if u["id"] == user_id), None)
        if not user:
            self.database.update_lock_sync_status(
                user_id, entity_id, False, "User not found"
            )
            return

        try:
            if enabled:
                pin = self._pin_cache.get(user_id)
                if not pin:
                    for other in self._managed_locks:
                        if other != entity_id:
                            pin = await self.get_user_pin_from_lock(user_id, other)
                            if pin:
                                break
                if not pin:
                    pin = await self.get_user_pin_from_lock(user_id, entity_id)
                if not pin:
                    self.database.update_lock_sync_status(
                        user_id, entity_id, False, "No PIN available"
                    )
                    return
                success = await self._set_lock_code(entity_id, slot, user["name"], pin)
            else:
                success = await self._clear_lock_code(entity_id, slot)

            self.database.update_lock_sync_status(
                user_id, entity_id, success,
                None if success else "Z-Wave operation failed",
            )
        except Exception as exc:
            self.database.update_lock_sync_status(
                user_id, entity_id, False, str(exc)
            )

    async def sync_all_users(self) -> Dict[str, Any]:
        async with self._sync_lock:
            users = self.database.get_users()
            results = {"total": 0, "synced": 0, "skipped": 0, "errors": []}
            for user in users:
                if not user["enabled"]:
                    continue
                results["total"] += 1
                pin = self._pin_cache.get(user["id"])
                if not pin:
                    results["skipped"] += 1
                    results["errors"].append(
                        f"No cached PIN for {user['name']}"
                    )
                    continue
                try:
                    await self.sync_user_to_locks(
                        user["id"],
                        pin=None if user.get("has_separate_lock_pin") else pin,
                        lock_pin=pin if user.get("has_separate_lock_pin") else None,
                    )
                    results["synced"] += 1
                except Exception as exc:
                    results["errors"].append(f"Failed {user['name']}: {exc}")
            return results

    async def periodic_lock_sync(self) -> Dict[str, Any]:
        """Verify DB lock-access state against actual Z-Wave state."""
        all_access = self.database.get_all_user_lock_access()
        results = {
            "total_records": len(all_access),
            "verified": 0,
            "differences_found": 0,
            "errors": 0,
        }
        for user_id in {r["user_id"] for r in all_access}:
            try:
                res = await self._verify_user_lock_access(user_id)
                if res["success"]:
                    results["verified"] += 1
                    results["differences_found"] += len(res["differences"])
                else:
                    results["errors"] += 1
            except Exception as exc:
                _LOGGER.error("Periodic sync error for user %d: %s", user_id, exc)
                results["errors"] += 1
        _LOGGER.info("Periodic lock sync: %s", results)
        return results

    async def _verify_user_lock_access(self, user_id: int) -> Dict[str, Any]:
        slot = self.database.get_user_lock_slot(user_id)
        if slot is None:
            return {"success": False, "differences": []}
        db_access = self.database.get_user_lock_access(user_id)
        differences = []
        for eid in self._managed_locks:
            try:
                pin = await self.get_user_pin_from_lock(user_id, eid)
                actual = bool(pin)
                expected = db_access.get(eid, {}).get("enabled", False)
                if actual != expected:
                    differences.append(
                        {"lock": eid, "expected": expected, "actual": actual}
                    )
                    self.database.set_user_lock_access(user_id, eid, actual)
                self.database.update_lock_sync_status(user_id, eid, True, None)
            except Exception as exc:
                self.database.update_lock_sync_status(user_id, eid, False, str(exc))
        return {"success": True, "differences": differences}

    async def get_lock_status(self) -> Dict[str, Any]:
        status: Dict[str, Any] = {
            "locks": [],
            "total_locks": len(self._managed_locks),
            "assigned_slots": self.database.get_assigned_slots(),
            "zwave_connected": self._zwave_client is not None,
        }
        for eid in self._managed_locks:
            node = self._lock_nodes.get(eid)
            # C4: never expose raw PIN codes in the API response.
            # Report only which slot numbers are occupied (no PIN values).
            occupied_slots: List[int] = []
            if node:
                for v in node.values.values():
                    if (v.command_class == CommandClass.USER_CODE
                            and v.property_ == "userCode"
                            and v.property_key is not None
                            and v.value):
                        raw = str(v.value)
                        pin_val = raw.split(":")[0] if ":" in raw else raw
                        if pin_val and pin_val != "0" * len(pin_val):
                            occupied_slots.append(v.property_key)
            status["locks"].append({
                "entity_id": eid,
                "node_id":   node.node_id if node else None,
                "name": (
                    getattr(node.device_config, "description", eid) if node else eid
                ),
                "occupied_slots": sorted(occupied_slots),
                "total_slots": 30,
            })
        return status
