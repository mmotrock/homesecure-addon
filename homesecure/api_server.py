"""
HomeSecure Container API Server
Exposes REST endpoints and a WebSocket channel that both the HA integration
and Lovelace cards consume.  All business logic lives in the coordinator and
lock manager — this file is pure routing + serialisation.

Endpoints
─────────
GET  /api/state
POST /api/arm_away      { "pin": "..." }
POST /api/arm_home      { "pin": "..." }
POST /api/disarm        { "pin": "..." }

GET  /api/users
POST /api/users         { "name", "pin", "admin_pin", "is_admin"?, "is_duress"?,
                          "phone"?, "email"?, "has_separate_lock_pin"?, "lock_pin"? }
PUT  /api/users/{id}    { "admin_pin", "name"?, "pin"?, … }
DEL  /api/users/{id}    { "admin_pin" } (body)

GET  /api/zones
POST /api/zones/{entity_id}/bypass   { "pin", "bypass": true|false }

GET  /api/locks
POST /api/locks/sync    { "admin_pin"? }

GET  /api/logs          ?limit=100&component=…&level=…

POST /api/zones/trigger { "entity_id", "zone_name"?, "state" }  ← called by HA automation
POST /api/auth          { "pin" }  ← validate PIN, returns { success, is_admin, user_name }

WS   /api/ws            ← real-time state-change stream
"""
import asyncio
import ipaddress
import json
import logging
import os
import weakref
from typing import Any, Dict, List, Optional, Set

import aiohttp
from aiohttp import web

_LOGGER = logging.getLogger(__name__)

# ── simple token auth ─────────────────────────────────────────────────────────
#   Set HOMESECURE_API_TOKEN env var to require a Bearer token on every request.
#   Leave unset to disable auth (useful during local dev / in a trusted LAN).
_API_TOKEN: Optional[str] = os.environ.get("HOMESECURE_API_TOKEN")

# ── trusted networks for the unauthenticated zone-trigger endpoint (C2) ──────
#   Comma-separated CIDR ranges.  Defaults to RFC-1918 + loopback.
#   Override via HOMESECURE_TRUSTED_NETWORKS env var.
_TRUSTED_NETS_RAW = os.environ.get(
    "HOMESECURE_TRUSTED_NETWORKS",
    "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
)
_TRUSTED_NETWORKS: List[ipaddress.IPv4Network] = []
for _cidr in _TRUSTED_NETS_RAW.split(","):
    _cidr = _cidr.strip()
    if _cidr:
        try:
            _TRUSTED_NETWORKS.append(ipaddress.ip_network(_cidr, strict=False))
        except ValueError:
            pass  # bad CIDR logged at startup in main.py


def _is_trusted_ip(ip_str: Optional[str]) -> bool:
    """Return True if ip_str falls within any configured trusted network."""
    if not ip_str:
        return False
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in _TRUSTED_NETWORKS)
    except ValueError:
        return False


def _check_auth(request: web.Request) -> bool:
    if not _API_TOKEN:
        return True
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {_API_TOKEN}"


def _auth_error() -> web.Response:
    return web.json_response({"error": "Unauthorized"}, status=401)


class APIServer:
    """aiohttp-based REST + WebSocket server for the HomeSecure container."""

    def __init__(self, coordinator, lock_manager, database):
        self.coordinator   = coordinator
        self.lock_manager  = lock_manager
        self.database      = database

        self._app  = web.Application(middlewares=[self._error_middleware])
        self._ws_clients: Set[web.WebSocketResponse] = weakref.WeakSet()

        self._setup_routes()

    # ------------------------------------------------------------------ #
    #  Middleware                                                          #
    # ------------------------------------------------------------------ #

    @web.middleware
    async def _error_middleware(self, request: web.Request, handler):
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception as exc:
            _LOGGER.error("Unhandled error in %s %s: %s", request.method, request.path, exc,
                          exc_info=True)
            return web.json_response({"error": "Internal server error"}, status=500)

    # ------------------------------------------------------------------ #
    #  Routes                                                              #
    # ------------------------------------------------------------------ #

    def _setup_routes(self):
        r = self._app.router
        r.add_get ("/api/state",                        self._get_state)
        r.add_post("/api/arm_away",                     self._arm_away)
        r.add_post("/api/arm_home",                     self._arm_home)
        r.add_post("/api/disarm",                       self._disarm)

        r.add_get ("/api/users",                        self._get_users)
        r.add_post("/api/users",                        self._create_user)
        r.add_put ("/api/users/{user_id}",              self._update_user)
        r.add_delete("/api/users/{user_id}",            self._delete_user)

        r.add_get ("/api/zones",                        self._get_zones)
        r.add_post("/api/zones/{entity_id}/bypass",     self._bypass_zone)
        r.add_post("/api/zones/trigger",                self._zone_trigger)

        r.add_post("/api/auth",                         self._auth_check)

        r.add_get ("/api/locks",                        self._get_locks)
        r.add_post("/api/locks/sync",                   self._sync_locks)
        r.add_get ("/api/locks/users/{user_id}",        self._get_user_lock_status)
        r.add_post("/api/locks/users/{user_id}/enable", self._set_user_lock_enabled)

        r.add_get ("/api/logs",                         self._get_logs)
        r.add_get ("/api/config",                       self._get_config)
        r.add_post("/api/config",                       self._update_config)

        r.add_get ("/api/ws",                           self._websocket_handler)

        # Health / ingress
        r.add_get ("/",                                 self._index)
        r.add_get ("/health",                           self._health)

    # ------------------------------------------------------------------ #
    #  State                                                               #
    # ------------------------------------------------------------------ #

    async def _get_state(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        return web.json_response(self.coordinator.state_dict())

    # ------------------------------------------------------------------ #
    #  Alarm operations                                                    #
    # ------------------------------------------------------------------ #

    async def _arm_away(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        body = await self._json(request)
        pin  = body.get("pin", "")
        result = await self.coordinator.arm_away(pin)
        return web.json_response(result, status=200 if result["success"] else 400)

    async def _arm_home(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        body = await self._json(request)
        pin  = body.get("pin", "")
        result = await self.coordinator.arm_home(pin)
        return web.json_response(result, status=200 if result["success"] else 400)

    async def _disarm(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        body = await self._json(request)
        pin  = body.get("pin", "")
        result = await self.coordinator.disarm(pin)
        return web.json_response(result, status=200 if result["success"] else 400)

    # ------------------------------------------------------------------ #
    #  Users                                                               #
    # ------------------------------------------------------------------ #

    async def _get_users(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        users = self.database.get_users()
        # Never expose pin hashes
        safe = [{k: v for k, v in u.items() if "hash" not in k} for u in users]
        return web.json_response(safe)

    async def _create_user(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        body = await self._json(request)
        result = await self.coordinator.add_user(
            name               = body.get("name", ""),
            pin                = body.get("pin", ""),
            admin_pin          = body.get("admin_pin", ""),
            is_admin           = body.get("is_admin", False),
            is_duress          = body.get("is_duress", False),
            phone              = body.get("phone"),
            email              = body.get("email"),
            has_separate_lock_pin = body.get("has_separate_lock_pin", False),
            lock_pin           = body.get("lock_pin"),
        )
        if result["success"]:
            user_id = result["user_id"]
            pin     = body.get("lock_pin") if body.get("has_separate_lock_pin") else body.get("pin")
            if pin:
                self.lock_manager.cache_pin(user_id, pin)
                asyncio.create_task(
                    self.lock_manager.sync_user_to_locks(
                        user_id,
                        pin     = None if body.get("has_separate_lock_pin") else pin,
                        lock_pin= pin  if body.get("has_separate_lock_pin") else None,
                    )
                )
        return web.json_response(result, status=201 if result["success"] else 400)

    async def _update_user(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        user_id = int(request.match_info["user_id"])
        body    = await self._json(request)
        admin_pin = body.pop("admin_pin", "")
        result = await self.coordinator.update_user(user_id, admin_pin, **body)
        if result["success"] and ("pin" in body or "lock_pin" in body):
            pin = body.get("lock_pin") or body.get("pin")
            if pin:
                self.lock_manager.cache_pin(user_id, pin)
                asyncio.create_task(
                    self.lock_manager.sync_user_to_locks(
                        user_id,
                        pin     = None if "lock_pin" in body else pin,
                        lock_pin= pin  if "lock_pin" in body else None,
                    )
                )
        return web.json_response(result, status=200 if result["success"] else 400)

    async def _delete_user(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        user_id   = int(request.match_info["user_id"])
        body      = await self._json(request)
        admin_pin = body.get("admin_pin", "")
        result    = await self.coordinator.remove_user(user_id, admin_pin)
        if result["success"]:
            asyncio.create_task(self.lock_manager.remove_user_from_locks(user_id))
        return web.json_response(result, status=200 if result["success"] else 400)

    # ------------------------------------------------------------------ #
    #  Zones                                                               #
    # ------------------------------------------------------------------ #

    async def _get_zones(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        mode  = request.query.get("mode")
        zones = self.database.get_zones(mode)
        return web.json_response(zones)

    async def _bypass_zone(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        entity_id = request.match_info["entity_id"]
        body      = await self._json(request)
        result    = await self.coordinator.bypass_zone(
            entity_id, body.get("pin", ""), body.get("bypass", True)
        )
        return web.json_response(result, status=200 if result["success"] else 400)

    async def _zone_trigger(self, request: web.Request) -> web.Response:
        """
        Called by an HA automation whenever a zone sensor changes to an
        open/active state.  Intentionally unauthenticated so HA automations
        don't need a token — but C2: restricted to trusted RFC-1918 networks
        so internet-facing callers cannot spoof triggers.
        """
        # C2: only accept zone triggers from trusted networks
        remote_ip = request.remote
        if not _is_trusted_ip(remote_ip):
            _LOGGER.warning(
                "Zone trigger rejected from untrusted IP %s", remote_ip
            )
            return web.json_response(
                {"error": "Request origin not in trusted networks"}, status=403
            )

        body      = await self._json(request)
        entity_id = body.get("entity_id", "")
        zone_name = body.get("zone_name") or entity_id
        state     = body.get("state", "")

        if not entity_id:
            return web.json_response({"error": "entity_id required"}, status=400)

        OPEN_STATES = {"on", "open", "detected", "unlocked", "true", "1"}
        if state.lower() not in OPEN_STATES:
            return web.json_response({"status": "ignored", "reason": "zone closed"})

        _LOGGER.info("Zone trigger received: %s (%s) from %s", entity_id, state, remote_ip)
        await self.coordinator.zone_triggered(entity_id, zone_name)
        return web.json_response({"status": "ok"})

    async def _auth_check(self, request: web.Request) -> web.Response:
        """
        Validate a PIN without side effects.  Used by the admin card to
        authenticate before performing write operations.

        Body:  { "pin": "123456" }
        Returns:
            200 { "success": true,  "is_admin": true,  "user_name": "Admin" }
            401 { "success": false, "error": "Invalid PIN or not an admin" }
        """
        if not _check_auth(request): return _auth_error()
        body = await self._json(request)
        pin  = body.get("pin", "")
        if not pin:
            return web.json_response({"error": "pin required"}, status=400)

        user = self.database.authenticate_user(pin)
        if user and user.get("is_admin"):
            return web.json_response({
                "success":   True,
                "is_admin":  True,
                "user_name": user.get("name", ""),
                "user_id":   user.get("id"),
            })
        elif user:
            return web.json_response(
                {"success": False, "error": "PIN valid but user is not an admin"},
                status=403,
            )
        else:
            return web.json_response(
                {"success": False, "error": "Invalid PIN"},
                status=401,
            )

    # ------------------------------------------------------------------ #
    #  Locks                                                               #
    # ------------------------------------------------------------------ #

    async def _get_locks(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        status = await self.lock_manager.get_lock_status()
        return web.json_response(status)

    async def _sync_locks(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        body      = await self._json(request)
        admin_pin = body.get("admin_pin", "")
        # Verify admin
        admin = self.database.authenticate_user_service(
            admin_pin, self.database.get_config().get("service_pin", "")
        )
        if not admin:
            return web.json_response({"error": "Admin authentication required"}, status=403)
        results = await self.lock_manager.sync_all_users()
        return web.json_response(results)

    async def _get_user_lock_status(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        user_id = int(request.match_info["user_id"])
        status  = await self.lock_manager.get_user_lock_status(user_id)
        return web.json_response(status)

    async def _set_user_lock_enabled(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        user_id = int(request.match_info["user_id"])
        body    = await self._json(request)
        ok = await self.lock_manager.set_user_lock_enabled(
            user_id,
            body.get("lock_entity_id", ""),
            bool(body.get("enabled", False)),
        )
        return web.json_response({"success": ok}, status=200 if ok else 500)

    # ------------------------------------------------------------------ #
    #  Logs                                                                #
    # ------------------------------------------------------------------ #

    async def _get_logs(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        # L4: cap limit to prevent full-table-scan DoS
        limit = min(int(request.query.get("limit", 100)), 1000)
        events = self.database.get_recent_events(limit)
        return web.json_response(events)

    # ------------------------------------------------------------------ #
    #  Config                                                              #
    # ------------------------------------------------------------------ #

    async def _get_config(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        cfg = self.database.get_config()
        # strip the service_pin from the response
        cfg.pop("service_pin", None)
        return web.json_response(cfg)

    async def _update_config(self, request: web.Request) -> web.Response:
        if not _check_auth(request): return _auth_error()
        body      = await self._json(request)
        admin_pin = body.pop("admin_pin", "")
        result    = await self.coordinator.update_config(admin_pin, body)
        return web.json_response(result, status=200 if result["success"] else 400)

    # ------------------------------------------------------------------ #
    #  WebSocket                                                           #
    # ------------------------------------------------------------------ #

    async def _websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        # H4: WebSocket must be authenticated the same as every REST endpoint
        if not _check_auth(request):
            raise web.HTTPUnauthorized(reason="Bearer token required")

        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self._ws_clients.add(ws)
        _LOGGER.info("WebSocket client connected (%d total)", len(self._ws_clients))

        # Send current state immediately on connect
        await ws.send_json({"type": "state_snapshot", **self.coordinator.state_dict()})

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    # Clients can send { "type": "ping" } — respond with pong
                    try:
                        data = json.loads(msg.data)
                        if data.get("type") == "ping":
                            await ws.send_json({"type": "pong"})
                    except json.JSONDecodeError:
                        pass
                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    break
        finally:
            self._ws_clients.discard(ws)
            _LOGGER.info("WebSocket client disconnected (%d remaining)", len(self._ws_clients))

        return ws

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        """Broadcast an event to all connected WebSocket clients."""
        if not self._ws_clients:
            return
        text = json.dumps(payload)
        dead = set()
        for ws in list(self._ws_clients):
            try:
                await ws.send_str(text)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._ws_clients.discard(ws)

    # ------------------------------------------------------------------ #
    #  Misc                                                                #
    # ------------------------------------------------------------------ #

    async def _index(self, _: web.Request) -> web.Response:
        return web.Response(
            text="HomeSecure API v1 — see /api/ws for real-time updates",
            content_type="text/plain",
        )

    async def _health(self, _: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "alarm_state": self.coordinator.state,
            "zwave_connected": self.lock_manager._zwave_client is not None,
        })

    # ------------------------------------------------------------------ #
    #  Startup / shutdown                                                  #
    # ------------------------------------------------------------------ #

    async def start(self, host: str = "0.0.0.0", port: int = 8099) -> None:
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        _LOGGER.info("HomeSecure API server listening on %s:%d", host, port)

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _json(request: web.Request) -> Dict:
        try:
            return await request.json()
        except Exception:
            return {}
