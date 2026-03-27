"""
HomeSecure Container Alarm State Machine
Pure-Python alarm coordinator — no Home Assistant dependency.
Drives all state transitions and timers with asyncio.
Notifies subscribers via asyncio.Queue (consumed by the WS broadcaster).
"""
import asyncio
import hmac
import logging
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Set

_LOGGER = logging.getLogger(__name__)

# ── states ────────────────────────────────────────────────────────────────────
STATE_DISARMED    = "disarmed"
STATE_ARMING      = "arming"
STATE_ARMED_HOME  = "armed_home"
STATE_ARMED_AWAY  = "armed_away"
STATE_PENDING     = "pending"       # entry delay countdown
STATE_TRIGGERED   = "triggered"

ZONE_TYPE_ENTRY = "entry"

# ── input validation constants ────────────────────────────────────────────────
PIN_MIN_LEN  = 6
PIN_MAX_LEN  = 8
NAME_MAX_LEN = 64

# ── alarm_auto_action valid values ────────────────────────────────────────────
# "none"     — stay triggered until manually disarmed
# "disarm"   — auto-disarm after alarm_duration
# "rearm"    — auto-rearm to previous mode after alarm_duration
VALID_AUTO_ACTIONS = {"none", "disarm", "rearm"}

# ── fields an admin is allowed to update on a user record ────────────────────
ALLOWED_UPDATE_FIELDS = {
    "name", "pin", "phone", "email", "enabled",
    "is_admin", "is_duress", "has_separate_lock_pin", "lock_pin",
}


class AlarmCoordinator:
    """
    Alarm state machine for the container.

    Public interface mirrors the old HA coordinator so the API layer stays
    simple.  Instead of firing HA bus events it pushes state-change dicts to
    an asyncio.Queue that the WebSocket broadcaster reads.
    """

    def __init__(self, database, event_queue: asyncio.Queue):
        self.database = database
        self._event_queue = event_queue

        self._state: str = STATE_DISARMED
        self._previous_state: Optional[str] = None
        self._changed_by: Optional[str] = None
        self._triggered_by: Optional[str] = None
        self._armed_state_before_trigger: Optional[str] = None  # for rearm after alarm

        self._exit_timer: Optional[asyncio.TimerHandle] = None
        self._entry_timer: Optional[asyncio.TimerHandle] = None
        self._alarm_timer: Optional[asyncio.TimerHandle] = None

        self._bypassed_zones: Set[str] = set()
        self._listeners: Set[Callable] = set()   # L2: was List — list has no .discard()

        # L5: reload persisted bypass state from the database on startup
        try:
            self._bypassed_zones = {
                z["entity_id"] for z in database.get_zones()
                if z.get("bypassed")
            }
            if self._bypassed_zones:
                _LOGGER.info(
                    "Restored %d bypassed zone(s) from database", len(self._bypassed_zones)
                )
        except Exception as exc:
            _LOGGER.warning("Could not restore bypass state: %s", exc)

    # ------------------------------------------------------------------ #
    #  Properties                                                          #
    # ------------------------------------------------------------------ #

    @property
    def state(self) -> str:
        return self._state

    @property
    def changed_by(self) -> Optional[str]:
        return self._changed_by

    @property
    def triggered_by(self) -> Optional[str]:
        return self._triggered_by

    def state_dict(self) -> Dict[str, Any]:
        return {
            "state": self._state,
            "changed_by": self._changed_by,
            "triggered_by": self._triggered_by,
        }

    # ------------------------------------------------------------------ #
    #  Listener management (for in-process observers)                     #
    # ------------------------------------------------------------------ #

    def add_listener(self, cb: Callable) -> None:
        self._listeners.append(cb)

    def remove_listener(self, cb: Callable) -> None:
        self._listeners.discard(cb)

    # ------------------------------------------------------------------ #
    #  Internal state management                                           #
    # ------------------------------------------------------------------ #

    async def _set_state(
        self, new_state: str, changed_by: Optional[str] = None
    ) -> None:
        old_state = self._state
        self._previous_state = old_state
        self._state = new_state
        if changed_by:
            self._changed_by = changed_by

        # M4: clear triggered_by here when transitioning to disarmed,
        # so the WS broadcast below always reflects the cleared value.
        if new_state == STATE_DISARMED:
            self._triggered_by = None

        self.database.log_event(
            "state_change",
            user_name=changed_by,
            state_from=old_state,
            state_to=new_state,
        )

        payload = {
            "type": "state_changed",
            "state": new_state,
            "previous_state": old_state,
            "changed_by": changed_by,
            "triggered_by": self._triggered_by,
        }
        await self._event_queue.put(payload)

        for cb in list(self._listeners):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(payload)
                else:
                    cb(payload)
            except Exception as exc:
                _LOGGER.error("Listener error: %s", exc)

        _LOGGER.info("State: %s → %s (by %s)", old_state, new_state, changed_by)

    def _cancel_timers(self) -> None:
        for attr in ("_exit_timer", "_entry_timer", "_alarm_timer"):
            handle = getattr(self, attr)
            if handle:
                handle.cancel()
            setattr(self, attr, None)

    # ------------------------------------------------------------------ #
    #  Authentication helpers                                              #
    # ------------------------------------------------------------------ #

    def _get_service_pin(self) -> str:
        cfg = self.database.get_config()
        return cfg.get("service_pin", "")

    def _authenticate(self, pin: str) -> Optional[Dict]:
        """User PIN auth (keypad-style, logs failures)."""
        return self.database.authenticate_user(pin)

    def _authenticate_service(self, pin: str) -> Optional[Dict]:
        """Service/admin auth — accepts service PIN or admin user PIN."""
        return self.database.authenticate_user_service(pin, self._get_service_pin())

    # ------------------------------------------------------------------ #
    #  Public alarm operations                                             #
    # ------------------------------------------------------------------ #

    async def arm_away(self, pin: str) -> Dict[str, Any]:
        svc_pin = self._get_service_pin()
        # H1: constant-time comparison for service PIN
        if svc_pin and hmac.compare_digest(pin, svc_pin):
            user = {"id": -1, "name": "Service", "is_admin": True, "is_duress": False}
        else:
            # C1: arm operations go through authenticate_user so failed attempts
            # are rate-limited identically to disarm operations.
            user = self._authenticate(pin)

        if not user:
            return {"success": False, "message": "Invalid PIN"}

        cfg = self.database.get_config()
        require_pin = bool(cfg.get("require_pin_to_arm", False))
        if require_pin and not user:
            return {"success": False, "message": "PIN required to arm"}

        if self._state in (STATE_ARMED_AWAY, STATE_ARMING):
            return {"success": False, "message": "Already arming or armed away"}

        exit_delay = int(cfg.get("exit_delay", 60))
        changed_by = user["name"]

        self._cancel_timers()
        await self._set_state(STATE_ARMING, changed_by)

        # M2: use get_running_loop() — get_event_loop() deprecated in Python 3.10+
        asyncio.get_running_loop().call_later(
            exit_delay,
            lambda: asyncio.create_task(self._complete_arming_away()),
        )

        _LOGGER.info("Arming away in %ds (initiated by %s)", exit_delay, changed_by)
        return {"success": True, "message": f"Arming away in {exit_delay}s", "delay": exit_delay}

    async def arm_home(self, pin: str) -> Dict[str, Any]:
        svc_pin = self._get_service_pin()
        # H1: constant-time comparison for service PIN
        if svc_pin and hmac.compare_digest(pin, svc_pin):
            user = {"id": -1, "name": "Service", "is_admin": True, "is_duress": False}
        else:
            # C1: arm through authenticate_user for rate limiting
            user = self._authenticate(pin)

        if not user:
            return {"success": False, "message": "Invalid PIN"}

        if self._state == STATE_ARMED_HOME:
            return {"success": False, "message": "Already armed home"}

        self._cancel_timers()
        changed_by = user["name"]
        await self._set_state(STATE_ARMED_HOME, changed_by)
        return {"success": True, "message": "Armed home"}

    async def disarm(self, pin: str) -> Dict[str, Any]:
        user = self._authenticate(pin)
        if not user:
            return {"success": False, "message": "Invalid PIN"}

        self._cancel_timers()
        await self._set_state(STATE_DISARMED, user["name"])
        # _triggered_by is now cleared inside _set_state (M4)
        self._bypassed_zones.clear()

        if user["is_duress"]:
            await self._event_queue.put({
                "type": "duress_code_used",
                "user_name": user["name"],
                "user_id": user["id"],
            })

        return {"success": True, "message": "Disarmed"}

    async def trigger_alarm(self, zone_entity_id: str, zone_name: str) -> None:
        """Externally trigger the alarm (called when a zone trips)."""
        await self._trigger_alarm(zone_entity_id, zone_name)

    # ------------------------------------------------------------------ #
    #  Internal timer callbacks                                            #
    # ------------------------------------------------------------------ #

    async def _complete_arming_away(self) -> None:
        await self._set_state(STATE_ARMED_AWAY, self._changed_by)
        _LOGGER.info("Armed away complete")

    async def _start_entry_delay(self, zone_entity_id: str, zone_name: str) -> None:
        config = self.database.get_config()
        entry_delay = int(config.get("entry_delay", 30))

        self._triggered_by = zone_name
        await self._set_state(STATE_PENDING, self._changed_by)

        if self._entry_timer:
            self._entry_timer.cancel()

        # M2: use get_running_loop()
        self._entry_timer = asyncio.get_running_loop().call_later(
            entry_delay,
            lambda: asyncio.create_task(self._trigger_alarm(zone_entity_id, zone_name)),
        )
        _LOGGER.warning("Entry delay: %ds to disarm (%s)", entry_delay, zone_name)

    async def _trigger_alarm(self, zone_entity_id: str, zone_name: str) -> None:
        if self._state == STATE_TRIGGERED:
            return

        self._triggered_by = zone_name
        # Remember which armed mode we were in so rearm can return to it (H2)
        self._armed_state_before_trigger = self._previous_state
        await self._set_state(STATE_TRIGGERED, self._changed_by)

        self.database.log_event(
            "alarm_triggered",
            zone_entity_id=zone_entity_id,
            state_from=self._previous_state,
            state_to=STATE_TRIGGERED,
        )

        config = self.database.get_config()
        alarm_duration = int(config.get("alarm_duration", 300))
        # H2: user-configurable post-alarm action
        # Values: "none" (stay triggered), "disarm" (auto-disarm), "rearm" (auto-rearm)
        auto_action = config.get("alarm_auto_action", "none")

        if auto_action in ("disarm", "rearm"):
            # M2: use get_running_loop()
            self._alarm_timer = asyncio.get_running_loop().call_later(
                alarm_duration,
                lambda: asyncio.create_task(self._auto_silence(auto_action)),
            )
        else:
            # "none" — stay triggered, just log elapsed time
            self._alarm_timer = asyncio.get_running_loop().call_later(
                alarm_duration,
                lambda: _LOGGER.info(
                    "Alarm duration elapsed — system remains triggered (auto_action=none)"
                ),
            )
        _LOGGER.critical("ALARM TRIGGERED by %s (auto_action=%s)", zone_name, auto_action)

    async def _auto_silence(self, action: str) -> None:
        """Called after alarm_duration when auto_action is 'disarm' or 'rearm'."""
        _LOGGER.info("Auto-silence triggered (action=%s)", action)
        if action == "disarm":
            await self._set_state(STATE_DISARMED, "auto-silence")
            self._bypassed_zones.clear()
            _LOGGER.info("System auto-disarmed after alarm duration")
        elif action == "rearm":
            target = self._armed_state_before_trigger
            if target in (STATE_ARMED_AWAY, STATE_ARMED_HOME):
                await self._set_state(target, "auto-rearm")
                _LOGGER.info("System auto-rearmed to %s after alarm duration", target)
            else:
                # Fallback to disarm if previous state is unknown
                await self._set_state(STATE_DISARMED, "auto-silence")
                _LOGGER.warning(
                    "auto-rearm: unknown previous state %r — falling back to disarmed", target
                )

    # ------------------------------------------------------------------ #
    #  Zone handling                                                       #
    # ------------------------------------------------------------------ #

    async def zone_triggered(self, zone_entity_id: str, zone_name: str) -> None:
        if self._state in (STATE_DISARMED, STATE_TRIGGERED):
            return
        if zone_entity_id in self._bypassed_zones:
            _LOGGER.info("Zone %s triggered but bypassed", zone_name)
            return

        zones = self.database.get_zones(self._state)
        zone_info = next((z for z in zones if z["entity_id"] == zone_entity_id), None)
        if not zone_info:
            _LOGGER.warning("Unknown zone triggered: %s", zone_entity_id)
            return

        if (zone_info["zone_type"] == ZONE_TYPE_ENTRY
                and self._state in (STATE_ARMED_AWAY, STATE_ARMED_HOME)
                and self._state != STATE_PENDING):
            await self._start_entry_delay(zone_entity_id, zone_name)
        else:
            await self._trigger_alarm(zone_entity_id, zone_name)

    # ------------------------------------------------------------------ #
    #  User management (proxies to DB, enforcing auth)                    #
    # ------------------------------------------------------------------ #

    async def add_user(
        self,
        name: str,
        pin: str,
        admin_pin: str,
        is_admin: bool = False,
        is_duress: bool = False,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        has_separate_lock_pin: bool = False,
        lock_pin: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Bootstrap: if no users exist yet, allow first admin creation freely.
        # Once any user exists, an admin PIN is always required.
        existing_users = self.database.get_users()
        if existing_users:
            admin = self._authenticate_service(admin_pin)
            if not admin or not admin.get("is_admin"):
                return {"success": False, "message": "Admin authentication required"}
        else:
            # No users yet — first user is automatically an admin
            is_admin = True
            _LOGGER.info("Bootstrap: creating first admin user (no PIN required)")

        # H5: validate name length
        if not name or len(name.strip()) == 0:
            return {"success": False, "message": "Name is required"}
        if len(name) > NAME_MAX_LEN:
            return {"success": False, "message": f"Name must be {NAME_MAX_LEN} characters or fewer"}

        # H5: validate PIN — digits only, correct length
        if not pin.isdigit() or not (PIN_MIN_LEN <= len(pin) <= PIN_MAX_LEN):
            return {"success": False, "message": f"PIN must be {PIN_MIN_LEN}–{PIN_MAX_LEN} digits"}
        if lock_pin and (not lock_pin.isdigit() or not (PIN_MIN_LEN <= len(lock_pin) <= PIN_MAX_LEN)):
            return {"success": False, "message": f"Lock PIN must be {PIN_MIN_LEN}–{PIN_MAX_LEN} digits"}

        uid = self.database.add_user(
            name, pin, is_admin, is_duress, phone, email,
            has_separate_lock_pin, lock_pin,
        )
        if uid:
            return {"success": True, "message": f"User {name} added", "user_id": uid}
        return {"success": False, "message": "Failed to add user"}

    async def remove_user(self, user_id: int, admin_pin: str) -> Dict[str, Any]:
        admin = self._authenticate_service(admin_pin)
        if not admin or not admin.get("is_admin"):
            return {"success": False, "message": "Admin authentication required"}
        if self.database.remove_user(user_id):
            return {"success": True, "message": "User deleted"}
        return {"success": False, "message": "Failed to delete user (may be last admin)"}

    async def update_user(
        self,
        user_id: int,
        admin_pin: str,
        **kwargs,
    ) -> Dict[str, Any]:
        admin = self._authenticate_service(admin_pin)
        if not admin or not admin.get("is_admin"):
            return {"success": False, "message": "Admin authentication required"}

        # H6: strip any fields the caller is not allowed to set directly
        filtered = {k: v for k, v in kwargs.items() if k in ALLOWED_UPDATE_FIELDS}
        unknown  = set(kwargs) - ALLOWED_UPDATE_FIELDS
        if unknown:
            _LOGGER.warning("update_user: ignored unknown fields: %s", unknown)

        # H5: validate incoming PIN values
        pin      = filtered.get("pin")
        lock_pin = filtered.get("lock_pin")
        name     = filtered.get("name")
        if pin and (not str(pin).isdigit() or not (PIN_MIN_LEN <= len(str(pin)) <= PIN_MAX_LEN)):
            return {"success": False, "message": f"PIN must be {PIN_MIN_LEN}–{PIN_MAX_LEN} digits"}
        if lock_pin and (not str(lock_pin).isdigit() or not (PIN_MIN_LEN <= len(str(lock_pin)) <= PIN_MAX_LEN)):
            return {"success": False, "message": f"Lock PIN must be {PIN_MIN_LEN}–{PIN_MAX_LEN} digits"}
        if name is not None and len(name) > NAME_MAX_LEN:
            return {"success": False, "message": f"Name must be {NAME_MAX_LEN} characters or fewer"}

        if self.database.update_user(user_id, **filtered):
            return {"success": True, "message": "User updated"}
        return {"success": False, "message": "Failed to update user"}

    async def bypass_zone(
        self, zone_entity_id: str, pin: str, bypass: bool = True
    ) -> Dict[str, Any]:
        user = self._authenticate(pin)
        if not user:
            return {"success": False, "message": "Invalid PIN"}
        if bypass:
            self._bypassed_zones.add(zone_entity_id)
        else:
            self._bypassed_zones.discard(zone_entity_id)
        self.database.set_zone_bypass(zone_entity_id, bypass)
        return {"success": True, "message": f"Zone {'bypassed' if bypass else 'unbypassed'}"}

    async def update_config(
        self, admin_pin: str, updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        admin = self._authenticate_service(admin_pin)
        if not admin or not admin.get("is_admin"):
            return {"success": False, "message": "Admin authentication required"}
        if self.database.update_config(updates):
            return {"success": True, "message": "Configuration updated"}
        return {"success": False, "message": "Failed to update configuration"}
