"""
HomeSecure HA Integration — Container API Client
Thin HTTP + WebSocket client that proxies HA calls to the HomeSecure container.
"""
import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY = 5   # seconds between WS reconnect attempts


class HomeSecureAPIClient:
    """
    REST + WebSocket client for the HomeSecure container API.

    Usage:
        client = HomeSecureAPIClient(hass, base_url, token)
        await client.async_start()          # starts WS listener
        result = await client.arm_away(pin)
        await client.async_stop()
    """

    def __init__(
        self,
        hass: HomeAssistant,
        base_url: str,
        token: Optional[str] = None,
    ):
        self._hass    = hass
        self._base    = base_url.rstrip("/")
        self._token   = token
        self._session: Optional[aiohttp.ClientSession] = None

        # State cache — updated by the WebSocket stream
        self._state: str = "unknown"
        self._changed_by: Optional[str] = None
        self._triggered_by: Optional[str] = None

        # Callbacks registered by the alarm_control_panel entity
        self._state_listeners: list[Callable] = []
        self._ws_task: Optional[asyncio.Task] = None
        self._running = False

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    async def async_connect(self) -> None:
        """Validate connectivity and fetch initial state.
        Called during HA setup — must not start long-running tasks."""
        self._session = async_get_clientsession(self._hass)
        self._running = True
        try:
            state = await self.get_state()
            self._update_state(state)
        except Exception as exc:
            _LOGGER.warning("Could not fetch initial state: %s", exc)

    def async_start_ws(self) -> None:
        """Start the WebSocket listener as a background task.
        Called after homeassistant_started so it does not block setup."""
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = self._hass.async_create_task(
                self._ws_listener_loop(), "homesecure_ws"
            )
            _LOGGER.debug("HomeSecure WebSocket listener started")

    async def async_start(self) -> None:
        """Legacy entry point — connects and starts WS immediately."""
        await self.async_connect()
        self.async_start_ws()

    async def async_stop(self) -> None:
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()

    # ------------------------------------------------------------------ #
    #  State / listener API                                                #
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

    def add_listener(self, cb: Callable) -> None:
        self._state_listeners.append(cb)

    def remove_listener(self, cb: Callable) -> None:
        if cb in self._state_listeners:
            self._state_listeners.remove(cb)

    # ------------------------------------------------------------------ #
    #  REST helpers                                                        #
    # ------------------------------------------------------------------ #

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self._base}{path}"
        async with self._session.get(url, headers=self._headers()) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _post(self, path: str, body: Dict) -> Dict[str, Any]:
        url = f"{self._base}{path}"
        async with self._session.post(
            url, json=body, headers=self._headers()
        ) as resp:
            data = await resp.json()
            if resp.status >= 400:
                raise aiohttp.ClientResponseError(
                    resp.request_info, resp.history,
                    status=resp.status, message=data.get("message", ""),
                )
            return data

    async def _put(self, path: str, body: Dict) -> Dict[str, Any]:
        url = f"{self._base}{path}"
        async with self._session.put(
            url, json=body, headers=self._headers()
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _delete(self, path: str, body: Dict) -> Dict[str, Any]:
        url = f"{self._base}{path}"
        async with self._session.delete(
            url, json=body, headers=self._headers()
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------ #
    #  Alarm operations                                                    #
    # ------------------------------------------------------------------ #

    async def get_state(self) -> Dict[str, Any]:
        return await self._get("/api/state")

    async def arm_away(self, pin: str) -> Dict[str, Any]:
        return await self._post("/api/arm_away", {"pin": pin})

    async def arm_home(self, pin: str) -> Dict[str, Any]:
        return await self._post("/api/arm_home", {"pin": pin})

    async def disarm(self, pin: str) -> Dict[str, Any]:
        return await self._post("/api/disarm", {"pin": pin})

    # ------------------------------------------------------------------ #
    #  Users                                                               #
    # ------------------------------------------------------------------ #

    async def get_users(self):
        return await self._get("/api/users")

    async def create_user(self, **kwargs):
        return await self._post("/api/users", kwargs)

    async def update_user(self, user_id: int, **kwargs):
        return await self._put(f"/api/users/{user_id}", kwargs)

    async def delete_user(self, user_id: int, admin_pin: str):
        return await self._delete(f"/api/users/{user_id}", {"admin_pin": admin_pin})

    # ------------------------------------------------------------------ #
    #  Zones / locks / config                                              #
    # ------------------------------------------------------------------ #

    async def get_zones(self, mode: Optional[str] = None):
        path = "/api/zones" + (f"?mode={mode}" if mode else "")
        return await self._get(path)

    async def bypass_zone(self, entity_id: str, pin: str, bypass: bool = True):
        return await self._post(f"/api/zones/{entity_id}/bypass",
                                {"pin": pin, "bypass": bypass})

    async def get_locks(self):
        return await self._get("/api/locks")

    async def sync_locks(self, admin_pin: str = ""):
        return await self._post("/api/locks/sync", {"admin_pin": admin_pin})

    async def get_config(self):
        return await self._get("/api/config")

    async def update_config(self, admin_pin: str, updates: Dict[str, Any]):
        return await self._post("/api/config", {"admin_pin": admin_pin, **updates})

    async def get_logs(self, limit: int = 100):
        return await self._get(f"/api/logs?limit={limit}")

    # ------------------------------------------------------------------ #
    #  WebSocket listener                                                  #
    # ------------------------------------------------------------------ #

    def _update_state(self, payload: Dict) -> None:
        """Update cached state from a state dict or WS event."""
        self._state       = payload.get("state", self._state)
        self._changed_by  = payload.get("changed_by", self._changed_by)
        self._triggered_by = payload.get("triggered_by", self._triggered_by)

    def _notify_listeners(self) -> None:
        for cb in list(self._state_listeners):
            try:
                cb()
            except Exception as exc:
                _LOGGER.error("State listener error: %s", exc)

    async def _ws_listener_loop(self) -> None:
        """Maintain a persistent WebSocket connection to the container."""
        ws_url = self._base.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/ws"
        headers = self._headers()

        while self._running:
            try:
                _LOGGER.debug("Connecting to container WS at %s", ws_url)
                async with self._session.ws_connect(
                    ws_url, headers=headers, heartbeat=30
                ) as ws:
                    _LOGGER.info("Connected to HomeSecure container WebSocket")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                payload = json.loads(msg.data)
                            except json.JSONDecodeError:
                                continue

                            msg_type = payload.get("type")

                            if msg_type in ("state_changed", "state_snapshot"):
                                self._update_state(payload)
                                self._hass.loop.call_soon_threadsafe(
                                    self._notify_listeners
                                )
                                _LOGGER.debug(
                                    "WS state: %s (by %s)",
                                    self._state, self._changed_by,
                                )
                            elif msg_type == "duress_code_used":
                                self._hass.bus.async_fire(
                                    "homesecure_duress_code_used",
                                    {
                                        "user_name": payload.get("user_name"),
                                        "user_id":   payload.get("user_id"),
                                    },
                                )

                        elif msg.type in (
                            aiohttp.WSMsgType.ERROR,
                            aiohttp.WSMsgType.CLOSE,
                        ):
                            _LOGGER.warning("WS closed/error — reconnecting")
                            break

            except aiohttp.WSServerHandshakeError as exc:
                # M6: 401/403 during WS upgrade means the token is wrong or missing.
                # Fire a HA persistent notification rather than retrying forever.
                if exc.status in (401, 403):
                    _LOGGER.error(
                        "HomeSecure WS auth failed (HTTP %d) — "
                        "check the api_token in the add-on config",
                        exc.status,
                    )
                    try:
                        await self._hass.services.async_call(
                            "persistent_notification",
                            "create",
                            {
                                "notification_id": "homesecure_auth_error",
                                "title": "HomeSecure — Authentication Error",
                                "message": (
                                    f"The HomeSecure integration cannot connect to the container "
                                    f"(HTTP {exc.status}). "
                                    "Please check that the **api_token** in the HomeSecure add-on "
                                    "config matches the token set in the integration."
                                ),
                            },
                        )
                    except Exception:
                        pass  # notification failure is non-fatal
                    # Back off for 60s before retrying so we don't spam logs
                    await asyncio.sleep(60)
                else:
                    _LOGGER.warning(
                        "WS handshake error %s — retrying in %ds", exc, RECONNECT_DELAY
                    )

            except asyncio.CancelledError:
                return
            except Exception as exc:
                _LOGGER.warning(
                    "WS connection error: %s — retrying in %ds", exc, RECONNECT_DELAY
                )

            if self._running:
                await asyncio.sleep(RECONNECT_DELAY)
