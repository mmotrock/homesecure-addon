# Changelog

## [1.0.0] - 2024-01-XX

### Added
- Initial release
- Complete alarm system integration
- Z-Wave lock management
- User management with admin panel
- Event logging
- Lovelace dashboard cards
- Web management interface
- Multi-architecture Docker builds

### Features
- PIN-based authentication
- Auto-lock on arm
- Per-lock user access control
- Dedicated logging system
- Ingress web UI

## [1.0.1] - 2026-03-06

### Fixed
- Removed invalid static file route in web_interface.py that caused
  add-on startup failure (/app/install/web/static did not exist)
- Fixed web UI "View Logs" link returning 404 error when accessed
  via Home Assistant ingress by converting absolute URLs to relative paths
- Fixed admin PIN authentication not working due to event names still
  using old 'homesecure_' prefix instead of 'homesecure_' prefix
- Fixed all remaining event name references migrated from homesecure_
  to homesecure_ (users_response, user_pin_response, config_response,
  events_response, verify_lock_access_response, etc.)
- Fixed default entity references updated from
  alarm_control_panel.homesecure to alarm_control_panel.homesecure
- Fixed Z-Wave lock PIN not being set on locks - set_lock_code now
  correctly sets userIdStatus=1 (enabled) before writing the PIN code,
  which is required by the Z-Wave USER_CODE command class
- Fixed Z-Wave lock code clearing to also set userIdStatus=0 so slots
  are properly marked as available after removal
- Fixed async_set_value calls to use value.value_id string identifier
  instead of the value object, matching the zwave-js-server-python API
- Fixed register_on_driver_ready replaced with correct
  driver_events.on("driver ready") event listener API
- Fixed PIN retrieval fallback in background lock sync to also attempt
  re-reading from the target lock itself before giving up, with a
  clearer log message when no PIN is available
- Fixed retrieve lock PIN timeout using incorrect event name

### Improved
- Added inline PIN validation with red field highlighting for alarm PIN
  and lock PIN fields - fields turn red on blur if length is invalid
  and clear automatically once corrected
- PIN validation errors now display as inline messages below the
  offending field instead of HA persistent notification popups
- Version number now automatically injected into manifest.json,
  web_interface.py, and README.md badge during build from config.yaml
  as single source of truth

### Repository
- Restructured repository layout to meet Home Assistant add-on store
  requirements (add-on files moved to homesecure/ subdirectory)
- Added repository.json to repo root
- Fixed GitHub Actions workflow paths to reflect new directory structure
- Fixed build.yaml to contain only HA add-on build configuration
- Moved GitHub Actions workflow to .github/workflows/build.yml
- Fixed ghcr.io push permissions by adding packages: write permission
- Fixed Docker image builds failing due to PEP 668 by using Python
  virtual environment in Dockerfile
- Replaced sed-based version injection with Python regex for reliability

## [1.0.2] - 2026-03-07

### Fixed
- Fixed PIN validation on new user form not showing inline field errors or
  red highlighting - the add user form (renderUserAdd) was missing id
  attributes and error div elements that the validation code required
- Fixed PIN validation listeners not attaching to the add user form by
  extracting them into a reusable attachPinValidation() method called
  after every render, so validation now works on both add and edit forms
- Fixed name field on new user form not highlighting red when left empty
- Fixed Z-Wave server URL appearing in both the addon configuration tab
  and the integration setup flow - URL is now configured in the addon
  config only and passed to the integration automatically via
  .addon_config.json, removing it from the integration config flow
- Fixed notification messages (success/error) going to HA persistent
  notifications instead of displaying inline in the admin panel

### Improved  
- Replaced HA persistent notification calls with inline toast messages
  that appear at the bottom of the admin card, providing immediate
  feedback without cluttering the HA notification center
- Integration setup flow simplified - users no longer need to enter the
  Z-Wave server URL during integration setup as it is read automatically
  from the addon configuration
- Z-Wave server URL is now read from addon options via the supervisor API
  at integration startup, with fallback to default URL if unavailable

## [2.0.0] - 2026-03-25

### Breaking Changes
- **Container-first architecture**: All business logic (alarm state machine, user/PIN
  database, lock management, event logging) has moved from the HA integration into
  the add-on container. The HA integration is now a thin proxy only.
- **Integration must be re-added**: The config flow has changed. Remove the existing
  HomeSecure integration and re-add it. You will be prompted for the container URL
  (`http://localhost:8099` by default) and an optional API token.
- **HA services reduced**: `add_user`, `update_user`, `remove_user`, `toggle_user_enabled`,
  `sync_locks`, `verify_lock_access`, `update_config`, and all other management services
  have been removed from the HA integration. These operations now go directly to the
  container REST API (from the Lovelace cards or `rest_command` automations).
  Only `arm_away`, `arm_home`, and `disarm` remain as HA services.
- **No longer self-installs**: The add-on no longer copies itself into
  `custom_components/`. Install the integration manually from the repository.
- **Database location changed**: The database moves from `/config/homesecure.db`
  to `/data/homesecure.db` inside the container. Existing data is migrated
  automatically on first startup (see Migration section below).

### Added
- `main.py` — container entrypoint; wires all services together; runs broadcast
  loop and periodic lock sync as asyncio background tasks
- `api_server.py` — aiohttp REST + WebSocket server on port 8099; optional Bearer
  token auth via `HOMESECURE_API_TOKEN` env var; WebSocket sends `state_snapshot`
  on connect and `state_changed` on every update
- `alarm_coordinator.py` (container) — pure-Python async state machine with no HA
  dependency; asyncio timers replace HA's `async_call_later`; pushes events to an
  `asyncio.Queue` for broadcast
- `database.py` (container) — standalone SQLite handler; WAL mode for safe
  concurrent access; identical schema to the original but zero HA imports
- `lock_manager.py` (container) — standalone Z-Wave JS WebSocket client with
  exponential backoff reconnection; owns its own `aiohttp.ClientSession`
- `migrate.py` — one-time data migration from `/config/homesecure.db` to
  `/data/homesecure.db`; runs automatically on first container startup; writes
  `/data/.migration_done` flag on success so it never runs again
- `integration/api_client.py` — persistent WebSocket listener + REST helper;
  caches alarm state locally; auto-reconnects on disconnect; fires
  `homesecure_duress_code_used` HA bus event on duress codes
- Container REST API with full endpoint coverage:
  `GET /api/state`, `POST /api/arm_away`, `POST /api/arm_home`, `POST /api/disarm`,
  `GET|POST /api/users`, `PUT|DEL /api/users/{id}`, `GET /api/zones`,
  `POST /api/zones/{id}/bypass`, `GET /api/locks`, `POST /api/locks/sync`,
  `GET /api/locks/users/{id}`, `POST /api/locks/users/{id}/enable`,
  `GET /api/logs`, `GET|POST /api/config`, `WS /api/ws`, `GET /health`

### Changed
- `integration/__init__.py` — creates `HomeSecureAPIClient` and starts the
  WebSocket listener; no coordinator, no database, no services beyond arm/disarm
- `integration/alarm_control_panel.py` — reduced from ~200 lines to ~80; every
  arm/disarm is a single `await api.call()`; state driven by WebSocket callbacks
- `integration/config_flow.py` — VERSION bumped to 2; collects `container_url`
  and optional `api_token` only; validates by hitting `/health`
- `integration/sensor.py` — rewrote as thin WS subscriber; replaced zone/database
  sensors with `AlarmStateSensor`, `LastChangedBySensor`, `FailedAttemptsSensor`
- `integration/binary_sensor.py` — rewrote as thin proxy; fetches zone list from
  `/api/zones`; delegates `is_on` to the underlying HA entity state; refreshes
  bypass status on every alarm state change
- `integration/const.py` — pruned from ~70 lines to 15; removed all table names,
  event names, and service names that only the old business logic needed
- `integration/services.yaml` — reduced to 3 services: `arm_away`, `arm_home`,
  `disarm`
- `integration/strings.json` and `translations/en.json` — updated to reflect the
  two-field config flow (`container_url`, `api_token`)
- `integration/manifest.json` — `requirements` set to `[]` (bcrypt and
  zwave-js-server-python moved to container pip installs); `iot_class` changed from
  `local_polling` to `local_push`; version bumped to `2.0.0`
- `run.sh` — no longer installs the integration or copies files into `/config`;
  exports env vars (`DB_PATH`, `ZWAVE_URL`, `API_PORT`, `HOMESECURE_API_TOKEN`,
  `LOG_LEVEL`) and execs `python3 main.py`
- `config.yaml` — version bumped to `2.0.0`; `homeassistant_api` set to `false`;
  `auth_api` set to `false`; added `api_token` option; added `data` volume map
  for `/data/homesecure.db`
- `Dockerfile` — removed nginx, `install-integration.sh`, `log_service.py`, and
  `web_interface.py`; now copies the six container Python files to `/app` and
  installs pip deps for the container process only

### Removed
- `integration/alarm_coordinator.py` — moved to container
- `integration/database.py` — moved to container
- `integration/lock_manager.py` — moved to container
- `integration/monitoring.py` — not yet re-implemented in container
- `log_service.py` — logging folded into `main.py`
- `web_interface.py` — replaced by `api_server.py` + `main.py`
- `rootfs/usr/bin/install-integration.sh` — add-on no longer self-installs

### Migration
On first startup after upgrading from v1.x, the container automatically:
1. Creates a backup of the old database at `/config/homesecure.db.pre_migration_backup`
2. Initialises the new schema at `/data/homesecure.db`
3. Copies users (with bcrypt hashes intact — no re-enrollment needed), alarm config,
   lock slot assignments, per-lock access records, and the last 500 audit events
4. Writes `/data/.migration_done` so migration never runs again

Failed attempts are intentionally not migrated (stale lockout state). The service
PIN is regenerated fresh by the container on first run.

### Lovelace Cards (Phase 3)
- `homesecure-card.js` — arm/disarm commands now go directly to the container
  REST API (`POST /api/arm_home`, `/api/arm_away`, `/api/disarm`) instead of
  through HA services. Added `api_url` and `api_token` config options. Entry
  point lock/cover toggles still use HA services (native HA entities). Added
  `_apiCall()` helper with bearer token support.
- `homesecure-admin.js` — all 16 `callService` + `subscribeEvents` patterns
  replaced with direct `fetch()` calls to the container REST API. Added
  `_apiFetch()`, `_apiPost()`, `_apiPut()`, `_apiDelete()` helpers. Lock list
  now loaded from `/api/locks` instead of scanning HA states. `showNotification`
  no longer calls `persistent_notification` HA service — replaced with
  self-contained inline toast. PIN retrieval removed (PINs are bcrypt-hashed and
  cannot be recovered). Authentication now validates admin PIN directly against
  the container API. Added `api_url` and `api_token` config options.
- `www/README.md` — rewritten to document v2.0 card configuration including
  `api_url`, `api_token`, and updated arm/disarm behavior.

### Corrections & Gaps Addressed (pre-release)
- Added `POST /api/zones/trigger` endpoint to `api_server.py` — called by HA
  automations when a zone sensor opens while the alarm is armed. The container
  coordinator handles entry delay, bypass checks, and arm-mode logic. The
  endpoint is intentionally unauthenticated so HA automations do not require
  a token. Ignores closed-state payloads silently.
- Added `POST /api/auth` endpoint to `api_server.py` — validates a PIN with no
  side effects. Returns `{ success, is_admin, user_name }`. Replaces the
  previous workaround of posting to `/api/users` with `_auth_check: true` to
  verify admin credentials from the Lovelace card.
- Fixed `homesecure-admin.js` `authenticateAdmin()` to use the new `POST
  /api/auth` endpoint instead of the `/api/users` side-effect hack. Now
  correctly checks `data.success && data.is_admin` before granting access.
- Added `watchdog: true` to `config.yaml` so the HA supervisor automatically
  restarts the add-on if the container process exits unexpectedly.
- Added integration install notice to `run.sh` — on every startup the script
  checks for `/config/custom_components/homesecure/__init__.py` and prints a
  prominent boxed warning in the add-on log with step-by-step install
  instructions if the integration is not found. Silences to a single info line
  once detected.
- Added `automations-template.yaml` to the repository root — provides
  ready-to-use HA automation templates for zone triggers (one per sensor),
  auto-lock on arm away/home, auto-close garage on arm, and duress code alerts.
  Also includes the required `rest_command` block for `configuration.yaml`.
  All values that require customisation are marked with `<ANGLE BRACKETS>`.
- Replaced `www/ADMIN_README.md` with updated v2.0 version documenting the
  direct container API communication model, new `api_url` and `api_token`
  config options, and updated troubleshooting steps.
  
### 🔴 Critical Fixes
- **C1 — Arm operations now rate-limited**
  `arm_away()` and `arm_home()` now route through `authenticate_user()`, applying the
  same failed-attempt counter and lockout as disarm. Previously only disarm was protected.

- **C2 — Zone trigger endpoint restricted to trusted networks**
  `POST /api/zones/trigger` now checks the caller's IP against a configurable list of
  trusted CIDR ranges (default: all RFC-1918 + loopback). Requests from outside those
  ranges receive `403 Forbidden`. Configure via `HOMESECURE_TRUSTED_NETWORKS` env var.

- **C3 — SQL injection surface in `update_config()` eliminated**
  Column names are now validated against an explicit `VALID_CONFIG_KEYS` allowlist before
  being interpolated into SQL. Unknown keys are rejected with a logged error and `400`.

- **C4 — Raw PIN codes removed from `GET /api/locks` response**
  Lock status no longer returns `codes: { slot: "123456" }`. The response now contains
  `occupied_slots: [1, 3, …]` (slot numbers only) and `total_slots: 30`.

### 🟠 High Fixes
- **H1 — Service PIN comparison uses `hmac.compare_digest`**
  Timing-safe comparison prevents timing-oracle attacks on the service PIN in both
  `authenticate_user_service()` (database layer) and `arm_away/arm_home` (coordinator).

- **H2 — Post-alarm behaviour is now user-configurable** *(Security tab)*
  Previously the alarm timer expiry was silently logged and nothing happened.
  Admins can now choose one of three behaviours:
  - **Stay triggered** — alarm stays active until manually disarmed (default)
  - **Auto-disarm** — system disarms itself after the siren duration
  - **Auto-rearm** — system returns to the armed mode it was in before the alarm

- **H3 — Raw PINs no longer stored in `failed_attempts` table**
  Only a masked hint (e.g. `"1****"`) is persisted, preserving audit usefulness
  without exposing near-correct PINs.

- **H4 — WebSocket endpoint now requires authentication**
  `GET /api/ws` was previously unauthenticated. Bearer token auth is now enforced
  before the WebSocket handshake is completed.

- **H5 — PIN and name input validation hardened**
  All PIN fields now validate digits-only, 6–8 character length, and bcrypt 72-byte
  truncation safety. Name fields capped at 64 characters. Validated in both the
  coordinator (server-side) and the admin card (client-side).

- **H6 — `update_user()` kwargs filtered through explicit allowlist**
  Unknown fields passed to the coordinator's `update_user()` are now silently dropped
  and logged rather than forwarded to the database. Allowed fields: `name`, `pin`,
  `phone`, `email`, `enabled`, `is_admin`, `is_duress`, `has_separate_lock_pin`,
  `lock_pin`.

### 🟡 Medium Fixes
- **M1 — WAL journal mode enabled; event log now pruned automatically**
  All SQLite connections use `PRAGMA journal_mode=WAL` and `synchronous=NORMAL`.
  `log_event()` now calls `_prune_events()` after every insert, deleting events older
  than `log_retention_days` and capping the table at 10,000 rows.

- **M2 — `asyncio.get_event_loop()` replaced with `get_running_loop()`**
  Removed deprecated calls in `arm_away()`, `arm_home()`, `_start_entry_delay()`,
  and `_trigger_alarm()`.

- **M3 — Z-Wave JS reconnect loop added**
  `LockManager` now starts a background `_reconnect_loop()` task that polls every
  30 seconds and reconnects to Z-Wave JS if the client is `None`, with exponential
  backoff up to 5 minutes.

- **M4 — `_triggered_by` cleared inside `_set_state()` on disarm**
  Previously cleared in `disarm()` after `_set_state()`, meaning the WebSocket
  broadcast could race with the clear. Now cleared before the broadcast fires.

- **M5 — Numeric config fields validated against min/max bounds**
  `update_config()` checks all numeric fields against a `CONFIG_BOUNDS` dict before
  writing to the database. Negative delays and out-of-range values are rejected with
  a `400` error.

- **M6 — Integration WebSocket client surfaces auth failures as HA notification**
  `_ws_listener_loop()` now catches `WSServerHandshakeError` with status 401/403
  and fires a HA persistent notification pointing the user to check their `api_token`
  config, then backs off 60 seconds. Previously it retried every 5 seconds forever.

### 🔵 Low / Robustness Fixes
- **L1 — Startup log clarified**
  `main.py` now logs token-auth status ("ENABLED" / "DISABLED") and the active
  trusted-networks CIDR list on startup.

- **L2 — `_listeners` type corrected from `List` to `Set`**
  `list.discard()` does not exist and would crash at runtime. Changed to a `set`
  so `remove_listener()` works correctly.

- **L4 — `GET /api/logs` limit capped at 1000**
  Prevents a full table-scan denial-of-service via `?limit=999999`.

- **L5 — Bypassed zones restored from database on container startup**
  `AlarmCoordinator.__init__` now loads persisted bypass state from the database so
  zones that were bypassed before a restart remain bypassed after it.

---

### ✨ New User-Configurable Settings
All settings are saved via `POST /api/config` with admin PIN authentication.

#### Security Tab (admin card)
| Setting | DB column | Default | Range |
|---|---|---|---|
| Failed attempts before lockout | `max_failed_attempts` | 5 | 3–20 |
| Lockout duration | `lockout_duration` | 300 s (5 min) | 1–60 min |
| Post-alarm behaviour | `alarm_auto_action` | `none` | `none` / `disarm` / `rearm` |
| Require PIN to arm | `require_pin_to_arm` | off | on / off |

#### General Tab (admin card)
| Setting | DB column | Default | Range |
|---|---|---|---|
| Entry delay | `entry_delay` | 30 s | 0–300 s |
| Exit delay | `exit_delay` | 60 s | 0–300 s |
| Alarm siren duration | `alarm_duration` | 300 s | 30–3600 s |
| Lock sync interval | `lock_sync_interval` | 3600 s | 1–1440 min |
| Event log retention | `log_retention_days` | 90 days | 7–365 days |

> **Upgrade note:** Existing databases are automatically migrated — the five new
> columns are added via `ALTER TABLE` on first startup. No manual SQL required.

---

### 🖥️ Admin Card (homesecure-admin.js) — v2.0
- **Security tab fully implemented** — was previously a "Coming Soon" placeholder.
  All four security settings rendered as purpose-built controls:
  - PIN lockout count and duration as numeric inputs with inline range hints
  - Post-alarm action as a radio-button card group with plain-English descriptions
  - "Require PIN to arm" as a toggle with clear on/off explanation
  - Single "Save Security Settings" button commits all four values atomically

- **General tab expanded** — added Alarm Timing card (entry/exit/alarm-duration),
  Log Retention card; Lock Sync section reorganised into its own card.
  Each sub-section has its own save button to avoid accidental bulk saves.

- **`loadConfig()` crash fixed** — the method contained a malformed
  `await` inside a `new Promise()` constructor which threw a syntax error
  at runtime and left the General tab permanently loading.

- **`_pendingRequirePin` state** — the "Require PIN to arm" toggle now tracks
  its unsaved state independently so re-renders during tab switching do not
  lose the user's selection before they press Save.
