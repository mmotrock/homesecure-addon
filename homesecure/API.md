# HomeSecure Container API Reference

The HomeSecure container exposes a REST + WebSocket API on port **8099**.  
All business logic lives in the container — the HA integration and Lovelace  
cards are thin clients that talk exclusively through this API.

---

## Contents

- [Authentication](#authentication)
- [Base URL](#base-url)
- [Common Response Fields](#common-response-fields)
- [Endpoints](#endpoints)
  - [Health](#health)
  - [Alarm State](#alarm-state)
  - [Alarm Operations](#alarm-operations)
  - [Authentication Check](#authentication-check)
  - [Users](#users)
  - [Zones](#zones)
  - [Locks](#locks)
  - [Logs](#logs)
  - [Config](#config)
  - [WebSocket](#websocket)
- [Alarm States Reference](#alarm-states-reference)
- [Event Types Reference](#event-types-reference)
- [Error Responses](#error-responses)

---

## Authentication

Token authentication is **optional**.  
Set the `api_token` option in the add-on config to enable it.  
When enabled, every request (except `POST /api/zones/trigger`) must include:

```
Authorization: Bearer <your_token>
```

Requests missing a valid token return `401 Unauthorized`.  
When `api_token` is left blank, all endpoints are open — suitable for a  
trusted local network.

---

## Base URL

```
http://localhost:8099
```

Change `localhost` to the add-on host IP if your HA instance and the add-on  
run on different machines.

---

## Common Response Fields

Write operations (`POST`, `PUT`, `DELETE`) always return a result object:

```json
{ "success": true }
{ "success": false, "error": "Human-readable reason" }
```

HTTP status reflects success: `200`/`201` on success, `400`/`401`/`403`/`500`  
on failure.

---

## Endpoints

---

### Health

#### `GET /health`

Unauthenticated. Used by the HA supervisor watchdog and the build smoke test.

**Response `200`:**
```json
{
  "status": "ok",
  "alarm_state": "disarmed",
  "zwave_connected": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"ok"` if the process is running |
| `alarm_state` | string | Current alarm state (see [Alarm States Reference](#alarm-states-reference)) |
| `zwave_connected` | bool | Whether the Z-Wave JS WebSocket connection is active |

---

### Alarm State

#### `GET /api/state`

Returns the current alarm state.

**Response `200`:**
```json
{
  "state": "disarmed",
  "changed_by": "Alice",
  "triggered_by": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `state` | string | Current alarm state |
| `changed_by` | string\|null | Name of the user who last changed the state |
| `triggered_by` | string\|null | Entity ID of the zone that triggered the alarm, or `null` |

---

### Alarm Operations

All three arm/disarm endpoints accept an optional `pin` field. If the system  
requires a PIN to arm (configurable), omit or leave blank to use the service  
PIN. Disarm always requires a valid user PIN.

---

#### `POST /api/arm_away`

Arms the system in away mode. Starts the exit delay timer.

**Request body:**
```json
{ "pin": "123456" }
```

| Field | Required | Description |
|-------|----------|-------------|
| `pin` | No | User or service PIN. Leave blank to use the container service PIN. |

**Response `200`:**
```json
{ "success": true }
```

**Response `400`:**
```json
{ "success": false, "error": "Already armed" }
```

---

#### `POST /api/arm_home`

Arms the system in home mode. Activates immediately (no exit delay).

**Request body:**
```json
{ "pin": "123456" }
```

**Response `200`:**
```json
{ "success": true }
```

---

#### `POST /api/disarm`

Disarms the system. Requires a valid user PIN.

**Request body:**
```json
{ "pin": "123456" }
```

**Response `200`:**
```json
{ "success": true }
```

**Response `400`:**
```json
{ "success": false, "error": "Invalid PIN" }
```

> **Duress codes:** If the PIN belongs to a user with `is_duress: true`, the  
> system disarms normally (so no alert is visible to an intruder) but the HA  
> integration fires a `homesecure_duress_code_used` event on the HA event bus.

---

### Authentication Check

#### `POST /api/auth`

Validates a PIN without side effects. Used by the admin Lovelace card before  
performing write operations. Does not arm, disarm, or modify any data.

**Request body:**
```json
{ "pin": "123456" }
```

**Response `200` — valid admin PIN:**
```json
{
  "success": true,
  "is_admin": true,
  "user_name": "Alice",
  "user_id": 1
}
```

**Response `403` — valid PIN but user is not an admin:**
```json
{ "success": false, "error": "PIN valid but user is not an admin" }
```

**Response `401` — wrong PIN:**
```json
{ "success": false, "error": "Invalid PIN" }
```

---

### Users

#### `GET /api/users`

Returns all users. PIN hashes are never included in the response.

**Response `200`:**
```json
[
  {
    "id": 1,
    "name": "Alice",
    "is_admin": 1,
    "is_duress": 0,
    "enabled": 1,
    "phone": "+15551234567",
    "email": "alice@example.com",
    "has_separate_lock_pin": 0,
    "created_at": "2025-01-15T10:00:00",
    "last_used": "2025-03-01T08:30:00",
    "use_count": 42,
    "slot_number": 1
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Unique user ID |
| `name` | string | Display name |
| `is_admin` | 0\|1 | Whether the user has admin privileges |
| `is_duress` | 0\|1 | Whether this is a duress/panic PIN |
| `enabled` | 0\|1 | Whether the user can authenticate |
| `phone` | string\|null | Phone number for notifications |
| `email` | string\|null | Email address for notifications |
| `has_separate_lock_pin` | 0\|1 | Whether the user has a separate PIN for locks |
| `created_at` | ISO timestamp | When the user was created |
| `last_used` | ISO timestamp\|null | When the user last authenticated |
| `use_count` | int | Total number of authentications |
| `slot_number` | int\|null | Z-Wave lock slot number assigned to this user |

---

#### `POST /api/users`

Creates a new user. Requires an admin PIN.

**Request body:**
```json
{
  "admin_pin": "999999",
  "name": "Bob",
  "pin": "456789",
  "is_admin": false,
  "is_duress": false,
  "phone": "+15559876543",
  "email": "bob@example.com",
  "has_separate_lock_pin": true,
  "lock_pin": "112233"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `admin_pin` | Yes | PIN of an admin user authorising the action |
| `name` | Yes | Display name |
| `pin` | Yes | Alarm PIN (6–8 digits, bcrypt hashed at rest) |
| `is_admin` | No | Grant admin privileges. Default `false` |
| `is_duress` | No | Mark as a duress/panic PIN. Default `false` |
| `phone` | No | Phone number for notifications |
| `email` | No | Email address |
| `has_separate_lock_pin` | No | Use a different PIN for lock access. Default `false` |
| `lock_pin` | No | Lock PIN — required if `has_separate_lock_pin` is `true` |

**Response `201`:**
```json
{ "success": true, "user_id": 5 }
```

> After creation the container immediately attempts to sync the user's PIN to  
> all Z-Wave locks they have access to (async, non-blocking).

---

#### `PUT /api/users/{id}`

Updates an existing user. Only fields included in the body are changed.  
Requires an admin PIN.

**Request body:**
```json
{
  "admin_pin": "999999",
  "name": "Robert",
  "pin": "654321",
  "phone": "+15550001111",
  "email": "robert@example.com",
  "is_admin": false,
  "enabled": true,
  "has_separate_lock_pin": true,
  "lock_pin": "998877"
}
```

All fields except `admin_pin` are optional. Omit `pin` / `lock_pin` to leave  
them unchanged.

**Response `200`:**
```json
{ "success": true }
```

---

#### `DELETE /api/users/{id}`

Permanently deletes a user. The last admin user cannot be deleted.  
Requires an admin PIN.

**Request body:**
```json
{ "admin_pin": "999999" }
```

**Response `200`:**
```json
{ "success": true }
```

> After deletion the container removes the user's PIN from all Z-Wave locks  
> asynchronously.

---

### Zones

#### `GET /api/zones`

Returns all registered zone sensors.

**Query parameters:**

| Parameter | Description |
|-----------|-------------|
| `mode` | Filter by arm mode: `armed_away` or `armed_home`. Omit for all zones. |

**Response `200`:**
```json
[
  {
    "id": 1,
    "entity_id": "binary_sensor.front_door",
    "zone_name": "Front Door",
    "zone_type": "entry",
    "enabled_away": 1,
    "enabled_home": 1,
    "bypassed": 0,
    "bypass_until": null,
    "last_state_change": "2025-03-01T07:45:00"
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `entity_id` | string | HA entity ID of the sensor |
| `zone_name` | string | Display name |
| `zone_type` | string | `"entry"` (triggers entry delay) or `"instant"` (triggers immediately) |
| `enabled_away` | 0\|1 | Active when armed away |
| `enabled_home` | 0\|1 | Active when armed home |
| `bypassed` | 0\|1 | Currently bypassed |
| `bypass_until` | ISO timestamp\|null | When the bypass expires (null = indefinite) |

---

#### `POST /api/zones/{entity_id}/bypass`

Bypasses or un-bypasses a zone. Requires a valid user PIN.  
The `entity_id` path parameter must be URL-encoded  
(e.g. `binary_sensor.front_door` → `binary_sensor.front_door`).

**Request body:**
```json
{ "pin": "123456", "bypass": true }
```

| Field | Required | Description |
|-------|----------|-------------|
| `pin` | Yes | Valid user PIN |
| `bypass` | Yes | `true` to bypass, `false` to restore |

**Response `200`:**
```json
{ "success": true }
```

---

#### `POST /api/zones/trigger`

Called by HA automations when a zone sensor opens while the alarm is armed.  
**This endpoint is intentionally unauthenticated** — HA automations on the  
local network do not need a token to call it.

The coordinator handles all safety logic internally: it ignores triggers when  
disarmed, ignores bypassed zones, and decides between entry delay and  
immediate trigger based on zone type and current arm mode.

**Request body:**
```json
{
  "entity_id": "binary_sensor.front_door",
  "zone_name": "Front Door",
  "state": "on"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `entity_id` | Yes | HA entity ID of the sensor |
| `zone_name` | No | Human-readable name. Falls back to `entity_id` if omitted |
| `state` | Yes | Sensor state. Open/active values: `on`, `open`, `detected`, `unlocked`, `true`, `1`. Any other value is treated as closed and ignored silently. |

**Response `200` — trigger processed:**
```json
{ "status": "ok" }
```

**Response `200` — closed state, nothing to do:**
```json
{ "status": "ignored", "reason": "zone closed" }
```

> See `automations-template.yaml` in the repository root for ready-to-use  
> HA automation templates and the required `rest_command` configuration.

---

### Locks

#### `GET /api/locks`

Returns all Z-Wave locks discovered from the Z-Wave JS controller, along with  
their current connection status.

**Response `200`:**
```json
{
  "locks": [
    {
      "entity_id": "lock.node_5",
      "name": "Front Door Lock",
      "node_id": 5,
      "state": "locked",
      "available": true
    }
  ]
}
```

---

#### `POST /api/locks/sync`

Triggers a full re-sync of all user PINs to all Z-Wave locks. Runs  
asynchronously. Requires an admin PIN.

**Request body:**
```json
{ "admin_pin": "999999" }
```

**Response `200`:**
```json
{ "success": true }
```

> Sync also runs automatically on a configurable interval (default 1 hour,  
> set via `lock_sync_interval` in config).

---

#### `GET /api/locks/users/{user_id}`

Returns the lock access configuration for a specific user — which locks they  
can access and the last sync status for each.

**Response `200`:**
```json
{
  "lock_access": {
    "lock.node_5": {
      "enabled": true,
      "last_synced": "2025-03-01T06:00:00",
      "last_sync_success": true,
      "last_sync_error": null
    },
    "lock.node_7": {
      "enabled": false,
      "last_synced": null,
      "last_sync_success": true,
      "last_sync_error": null
    }
  }
}
```

---

#### `POST /api/locks/users/{user_id}/enable`

Grants or revokes a user's access to a specific lock. Updates the database  
immediately and triggers an async Z-Wave sync.

**Request body:**
```json
{
  "lock_entity_id": "lock.node_5",
  "enabled": true
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `lock_entity_id` | Yes | Entity ID of the lock |
| `enabled` | Yes | `true` to grant access, `false` to revoke |

**Response `200`:**
```json
{ "success": true }
```

---

### Logs

#### `GET /api/logs`

Returns recent alarm events in reverse chronological order.

**Query parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `limit` | `100` | Maximum number of events to return |

**Response `200`:**
```json
{
  "events": [
    {
      "id": 512,
      "event_type": "disarmed",
      "user_id": 1,
      "user_name": "Alice",
      "timestamp": "2025-03-09T08:30:00",
      "state_from": "armed_away",
      "state_to": "disarmed",
      "zone_entity_id": null,
      "details": null,
      "is_duress": 0
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `event_type` | string | See [Event Types Reference](#event-types-reference) |
| `user_id` | int\|null | ID of the user who triggered the event |
| `user_name` | string\|null | Name of the user |
| `state_from` | string\|null | Previous alarm state (for state change events) |
| `state_to` | string\|null | New alarm state (for state change events) |
| `zone_entity_id` | string\|null | Entity ID of the zone involved (for zone events) |
| `details` | string\|null | JSON-encoded additional detail, event-type specific |
| `is_duress` | 0\|1 | Whether the event was triggered by a duress PIN |

---

### Config

#### `GET /api/config`

Returns the current system configuration. The `service_pin` field is always  
stripped from the response.

**Response `200`:**
```json
{
  "entry_delay": 30,
  "exit_delay": 60,
  "alarm_duration": 300,
  "notification_mobile": 1,
  "notification_sms": 0,
  "sms_numbers": null,
  "lock_delay_home": 0,
  "lock_delay_away": 60,
  "close_delay_home": 0,
  "close_delay_away": 60,
  "auto_lock_on_arm_home": 0,
  "auto_lock_on_arm_away": 1,
  "auto_close_on_arm_home": 0,
  "auto_close_on_arm_away": 1,
  "lock_entities": null,
  "garage_entities": null,
  "lock_sync_interval": 3600,
  "updated_at": "2025-03-01T00:00:00"
}
```

| Field | Unit | Description |
|-------|------|-------------|
| `entry_delay` | seconds | Time to disarm before alarm triggers after entry |
| `exit_delay` | seconds | Time to leave before armed_away activates |
| `alarm_duration` | seconds | How long the alarm sounds before auto-silencing |
| `lock_delay_home` | seconds | Delay before auto-locking on arm home |
| `lock_delay_away` | seconds | Delay before auto-locking on arm away |
| `close_delay_home` | seconds | Delay before auto-closing garage on arm home |
| `close_delay_away` | seconds | Delay before auto-closing garage on arm away |
| `lock_sync_interval` | seconds | How often to re-sync PINs to Z-Wave locks (default 3600) |
| `auto_lock_on_arm_away` | 0\|1 | Lock doors automatically when arming away |
| `auto_close_on_arm_away` | 0\|1 | Close garage automatically when arming away |

---

#### `POST /api/config`

Updates one or more configuration fields. Requires an admin PIN.  
Only fields included in the body are changed.

**Request body:**
```json
{
  "admin_pin": "999999",
  "entry_delay": 45,
  "exit_delay": 90,
  "lock_sync_interval": 1800
}
```

**Response `200`:**
```json
{ "success": true }
```

---

### WebSocket

#### `GET /api/ws`

Upgrades to a WebSocket connection. The server pushes a message every time  
the alarm state changes. The HA integration and any other subscriber stay  
in sync without polling.

**On connect — state snapshot:**

Immediately after connecting, the server sends the current state so clients  
don't need to also call `GET /api/state`:

```json
{
  "type": "state_snapshot",
  "state": "disarmed",
  "changed_by": "Alice",
  "triggered_by": null
}
```

**On state change — state_changed event:**

```json
{
  "type": "state_changed",
  "state": "armed_away",
  "previous_state": "disarmed",
  "changed_by": "Alice",
  "triggered_by": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | `"state_snapshot"` or `"state_changed"` |
| `state` | string | New alarm state |
| `previous_state` | string\|null | Previous alarm state (`state_changed` only) |
| `changed_by` | string\|null | User name or `null` for timer-driven transitions |
| `triggered_by` | string\|null | Zone entity ID if state is `triggered`, otherwise `null` |

**Client → server — ping/pong:**

Clients may send a ping at any time to verify the connection is alive:

```json
{ "type": "ping" }
```

Server responds:

```json
{ "type": "pong" }
```

The server also sends an aiohttp-level WebSocket heartbeat every 30 seconds  
to prevent idle connection drops.

---

## Alarm States Reference

| State | Description |
|-------|-------------|
| `disarmed` | System is off. No zones are monitored. |
| `arming` | Exit delay is counting down before `armed_away` activates. |
| `armed_home` | Home mode. Only zones with `enabled_home=1` are monitored. |
| `armed_away` | Away mode. All zones with `enabled_away=1` are monitored. |
| `pending` | Entry delay counting down — disarm now to prevent alarm. |
| `triggered` | Alarm is sounding. |

State transition diagram:

```
disarmed ──arm_home──► armed_home
disarmed ──arm_away──► arming ──(exit delay)──► armed_away
armed_home ──zone open──► triggered
armed_away ──zone open (entry)──► pending ──(entry delay)──► triggered
armed_away ──zone open (instant)──► triggered
pending ──disarm──► disarmed
triggered ──disarm──► disarmed
triggered ──(alarm_duration)──► disarmed
any armed ──disarm──► disarmed
```

---

## Event Types Reference

| Event Type | Description |
|------------|-------------|
| `state_change` | Alarm state changed (arm, disarm, trigger) |
| `armed_away` | System armed in away mode |
| `armed_home` | System armed in home mode |
| `disarmed` | System disarmed |
| `triggered` | Alarm triggered by a zone |
| `zone_bypass` | A zone was bypassed or un-bypassed |
| `user_added` | A new user was created |
| `user_updated` | A user's details were changed |
| `user_removed` | A user was deleted |
| `config_updated` | System configuration was changed |
| `failed_attempt` | An incorrect PIN was entered |
| `lock_sync` | Z-Wave lock PIN sync ran (success or failure) |

---

## Error Responses

All error responses follow a consistent shape:

```json
{ "error": "Human-readable description" }
```

| HTTP Status | Meaning |
|-------------|---------|
| `400` | Bad request — missing required field, invalid PIN, invalid state transition |
| `401` | Unauthorized — missing or invalid Bearer token, or wrong PIN |
| `403` | Forbidden — PIN is valid but lacks the required privilege (e.g. non-admin) |
| `500` | Internal server error — unhandled exception, logged to the add-on log |
