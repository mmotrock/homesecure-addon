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

---

## [2.0.0] - 2026-04-05 — Complete Architecture Rewrite

This release is a complete rewrite of the HomeSecure addon. The previous version
ran entirely as a Home Assistant integration. v2.0 splits into a persistent
container service and a thin HA integration, providing reliable state across
restarts, direct Z-Wave lock management, and a full-featured Lovelace admin panel.

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

### Architecture Changes
- **New container service** — Python/aiohttp REST + WebSocket API running on port 8099,
  managing all alarm state, users, locks, and events independently of HA restarts
- **Thin HA integration** — now a simple proxy that exposes HA entities
  (`alarm_control_panel`, binary_sensor zones) and forwards commands to the container
- **SQLite database** at `/data/homesecure.db` — persists users, config, events,
  lock slots, and failed attempts across restarts; WAL mode for safe concurrent access
- **Z-Wave lock management** — direct connection to Z-Wave JS server, PIN codes
  programmed at the lock level independently of HA's Z-Wave integration
- **Two Lovelace cards** — badge card for arm/disarm and admin card for full management

### Added

#### New Container Files
- `main.py` — container entrypoint; wires all services together; runs broadcast
  loop and periodic lock sync as asyncio background tasks
- `api_server.py` — aiohttp REST + WebSocket server on port 8099; optional Bearer
  token auth via `HOMESECURE_API_TOKEN` env var; WebSocket sends `state_snapshot`
  on connect and `state_changed` on every update
- `alarm_coordinator.py` (container) — pure-Python async state machine with no HA
  dependency; asyncio timers replace HA's `async_call_later`
- `database.py` (container) — standalone SQLite handler; WAL mode; bcrypt PIN hashing
- `lock_manager.py` (container) — standalone Z-Wave JS WebSocket client with
  exponential backoff reconnection
- `migrate.py` — one-time data migration from `/config/homesecure.db` to
  `/data/homesecure.db`; runs automatically on first container startup

#### New API Endpoints
- `GET /api/bootstrap` — no auth, returns `{bootstrap_needed: bool}`
- `GET /api/debug/status` — no auth, returns user count, lockout state, alarm state
- `POST /api/debug/clear-lockout` — clears failed attempts without restarting
- `POST /api/auth` — validates a PIN with no side effects; returns `{success, is_admin, user_name}`
- `GET /api/locks/users/{id}` — per-user lock access state
- `POST /api/locks/users/{id}/enable` — enable/disable user on a specific lock
- `POST /api/locks/users/{id}/verify` — verify actual Z-Wave state for one user
- `POST /api/locks/sync-user` — sync one user to all locks with provided PIN
- `POST /api/users/{id}/remove-from-locks` — remove user codes from all locks on disable
- Full REST coverage: `GET /api/state`, `POST /api/arm_away`, `POST /api/arm_home`,
  `POST /api/disarm`, `GET|POST /api/users`, `PUT|DEL /api/users/{id}`,
  `GET /api/zones`, `POST /api/zones/{id}/bypass`, `GET /api/locks`,
  `POST /api/locks/sync`, `GET /api/logs`, `GET|POST /api/config`,
  `WS /api/ws`, `GET /health`

#### New Features
- Duress code support — triggers silent alert while appearing to disarm normally
- Optional PIN required to arm — badge card shows PIN keypad before arming
- Per-user lock slot assignment and PIN programming directly to Z-Wave locks
- Enable/disable individual user access per lock with immediate code removal
- User re-enable flow — if PIN is cached, restores lock access automatically;
  otherwise prompts admin for the user's PIN via a keypad dialog
- PIN cache populated from locks on container startup so operations work after restart
- Lock PIN persisted to database so re-enable works after container restart
- Verify lock state against database with per-user endpoint
- Audio alerts via HA `media_player` entities (configurable in Devices tab):
  - Short beep every 2 seconds during arm-away exit delay
  - Long beep when fully armed (away or home)
  - Entry beep every 2 seconds during entry delay (`pending` state)
  - Short confirmation beep on disarm
  - Three bundled MP3 files copied to `/config/www/community/homesecure/` on startup
- Expandable event log rows — click any event to show full details (user,
  full timestamp, entity, previous/new state, mode, zone, IP address)
- Debug logging toggle in addon Configuration tab (`debug_logging: false`) — forces
  Python service to DEBUG level; accessible even when admin card won't load
- Browser-side debug logging toggle in admin General tab — verbose JS console output
- `update_version.sh` script — bumps version string across all files

#### Admin Panel (homesecure-admin.js)
- Users tab — add, edit, delete users; manage per-lock access with enable/disable toggles
- Events tab — filterable event log with click-to-expand rows showing full detail
- Devices tab — select `media_player.*` entities for audio alerts; set alert volume
- Security tab — PIN lockout count/duration, post-alarm behaviour, require PIN to arm
- General tab — alarm timing, log retention, lock sync interval, debug logging toggle

#### Badge Card (homesecure-card.js)
- Visual badge with color-coded glow showing current alarm state
- Arm Home / Arm Away buttons; PIN keypad shown before arming when required
- Disarm PIN keypad
- Entry point toggles (locks, covers, switches)
- Admin panel launcher
- Audio alert playback via `media_player.play_media` service

### Changed
- `integration/__init__.py` — creates `HomeSecureAPIClient` and starts WebSocket
  listener; no coordinator, database, or services beyond arm/disarm
- `integration/alarm_control_panel.py` — reduced to ~80 lines; state driven by
  WebSocket callbacks; `require_pin_to_arm` exposed via entity attributes
- `integration/config_flow.py` — VERSION bumped to 2; collects admin name and PIN
  during setup, creates first user automatically; options flow fixed for HA 2024.11+
- `integration/manifest.json` — `requirements` set to `[]`; `iot_class` changed to
  `local_push`; `homeassistant >= 2024.1.0` requirement added; version `2.0.0`
- `run.sh` — installs integration and Lovelace cards on every startup; copies audio
  files; auto-registers Lovelace resources; reads `debug_logging` option and
  overrides `LOG_LEVEL` to `debug` if set
- `config.yaml` — version `2.0.0`; port 8099 exposed; `api_token` and
  `debug_logging` options added; `data` volume map added
- `Dockerfile` — removed nginx, web_interface.py, log_service.py; copies container
  Python files and audio files; installs pip deps for container only

### Removed
- `integration/alarm_coordinator.py` — moved to container
- `integration/database.py` — moved to container
- `integration/lock_manager.py` — moved to container
- `log_service.py` — logging folded into `main.py`
- `web_interface.py` — replaced by `api_server.py`

### Migration
On first startup after upgrading from v1.x, the container automatically:
1. Creates a backup of the old database at `/config/homesecure.db.pre_migration_backup`
2. Initialises the new schema at `/data/homesecure.db`
3. Copies users (bcrypt hashes intact — no re-enrollment needed), alarm config,
   lock slot assignments, per-lock access records, and the last 500 audit events
4. Writes `/data/.migration_done` so migration never runs again

Failed attempts are intentionally not migrated. The service PIN is regenerated fresh.

### 🔴 Critical Security Fixes
- **C1** — Arm operations now route through `authenticate_user()`, applying the same
  failed-attempt counter and lockout as disarm
- **C2** — `POST /api/zones/trigger` restricted to configurable trusted CIDR ranges
  (default: RFC-1918 + loopback); requests from outside receive `403 Forbidden`
- **C3** — SQL injection surface in `update_config()` eliminated via `VALID_CONFIG_KEYS`
  allowlist; unknown keys rejected with `400`
- **C4** — Raw PIN codes removed from `GET /api/locks` response; now returns
  `occupied_slots` (slot numbers only)

### 🟠 High Security Fixes
- **H1** — Service PIN comparison uses `hmac.compare_digest` (timing-safe)
- **H2** — Post-alarm behaviour configurable: stay triggered / auto-disarm / auto-rearm
- **H3** — Raw PINs no longer stored in `failed_attempts` table; only masked hint persisted
- **H4** — WebSocket endpoint `GET /api/ws` now requires Bearer token authentication
- **H5** — PIN and name input validation hardened (digits-only, 6–8 chars, 64-char name limit)
- **H6** — `update_user()` kwargs filtered through explicit allowlist; unknown fields dropped

### 🟡 Medium Fixes
- **M1** — WAL journal mode enabled; event log pruned automatically after every insert
- **M2** — `asyncio.get_event_loop()` replaced with `get_running_loop()` throughout
- **M3** — Z-Wave JS reconnect loop with exponential backoff up to 5 minutes
- **M4** — `_triggered_by` cleared inside `_set_state()` before WebSocket broadcast
- **M5** — Numeric config fields validated against min/max bounds in `update_config()`
- **M6** — Integration WebSocket client surfaces auth failures as HA persistent notification

### 🔵 Robustness Fixes
- **L1** — Startup log shows token-auth status and trusted-networks CIDR list
- **L2** — `_listeners` changed from `List` to `Set`; `remove_listener()` now works
- **L4** — `GET /api/logs` limit capped at 1000 to prevent table-scan DoS
- **L5** — Bypassed zones restored from database on container startup

### Bug Fixes (stabilization)
- `datetime.now()` replaced with `datetime.utcnow()` throughout database — fixes
  phantom lockouts from UTC/local timezone mismatch with SQLite `CURRENT_TIMESTAMP`
- Arm Home/Away no longer count as failed attempts when no PIN is provided and
  `require_pin_to_arm` is false
- `database.update_user()` now accepts `enabled` parameter — fixes user toggle
- Z-Wave lock discovery now detects locks via value_id string parsing since
  `node.command_classes` returns empty in current library versions
- 2-second delay added after Z-Wave driver ready to allow node values to populate
- `get_user_lock_status()` method added to lock_manager — was missing, causing 500
  on all lock UI operations
- `_get_usercode_value()` / `_get_userid_status_value()` use value_id string parsing
- `GET /api/users` returns `{"users": [...]}` format consistently
- Internal config changes (service_pin) no longer logged as user-visible events
- `service_pin` added to valid config keys, `CREATE TABLE`, and migrations
- Z-Wave JS `driver_ready` Event passed correctly to `listen()`
- `listen()` started as background task alongside `connect()`
- CORS middleware added — fixes browser cards being blocked when calling API across ports
- `updatePinDisplay()` now enables `confirm-arm` button as well as `disarm` button
- Admin card scroll position saved and restored across renders
- Admin tab content correctly matches active tab when re-entering admin panel
- Stale localStorage lockout state cleared on load and synced from server
- `loadUsers()` calls `this.render()` after loading so user list refreshes immediately
- OptionsFlow 500 fixed — `config_entry` removed from constructor call
- Bootstrap flow — `/api/bootstrap` endpoint allows first user creation without PIN
- Config flow collects admin name and PIN during setup, creates first user automatically

### New User-Configurable Settings

#### Security Tab
| Setting | Default | Range |
|---|---|---|
| Failed attempts before lockout | 5 | 3–20 |
| Lockout duration | 300 s (5 min) | 1–60 min |
| Post-alarm behaviour | stay triggered | triggered / disarm / rearm |
| Require PIN to arm | off | on / off |

#### General Tab
| Setting | Default | Range |
|---|---|---|
| Entry delay | 30 s | 0–300 s |
| Exit delay | 60 s | 0–300 s |
| Alarm siren duration | 300 s | 30–3600 s |
| Lock sync interval | 3600 s | 1–1440 min |
| Event log retention | 90 days | 7–365 days |

> **Upgrade note:** Existing databases are automatically migrated — new columns are
> added via `ALTER TABLE` on first startup. No manual SQL required.

---

## [2.0.3] - 2026-04-11

### Added
- **Enriched event logging** — all audit log entries now include who made the
  change, what was changed, and (where applicable) what the previous value was.
  Specifically:
  - `user_added` — logs the creating admin, plus new user's permissions
    (`is_admin`, `is_duress`, `has_separate_lock_pin`, `has_phone`, `has_email`)
  - `user_updated` — logs the acting admin and a list of which fields changed
    (`pin_changed` / `lock_pin_changed` flags used instead of values — PINs are
    never stored in logs)
  - `user_deleted` — logs the acting admin and a snapshot of the deleted user's
    prior state (`was_admin`, `was_duress`, `was_enabled`)
  - `config_updated` — logs the acting admin, the new values, and the previous
    values for every changed key
  - `zone_bypass` — logs which user bypassed or unbypassed the zone and the
    bypass duration
  - `admin_login_failed` — new event type logged when an incorrect PIN is
    entered on the admin card login screen; includes running failed attempt
    count. Distinct from keypad disarm failures which go to `failed_attempts`
    table
  - All `state_change` events (arm/disarm) already captured user name and
    state correctly — no changes needed there
- **Last-admin disable protection** — the system now prevents the last enabled
  admin account from being disabled, at both the database layer
  (`update_user()`, `set_user_enabled()`) and the coordinator layer. The admin
  card also checks before calling the API and shows an immediate error message.
- **Self-disable prevention** — an admin can no longer disable their own
  account. The coordinator rejects the request server-side; the admin card
  also blocks it client-side using the authenticated user's ID stored at login.

### Fixed
- **Admin card scroll position jumps to top** on field changes (e.g. selecting
  an entity or updating a delay in the Arm Actions section). The scroll
  position was being saved correctly before re-render but restored
  synchronously before the browser had completed layout, so the assignment was
  discarded. Fixed by wrapping the restore in `requestAnimationFrame()` so it
  runs after the browser paints.
- **Total events counter always showed zero** in the Events tab stats panel
  even when the by-type breakdown showed non-zero counts. `loadEventStats()`
  was building the stats object with key `total` but the render function read
  `total_events` — key mismatch caused it to always fall back to `0`. Key
  unified to `total_events`.
- **Arm action entity and action dropdowns** require a long-press to open in
  some browsers / HA versions. The card's parent layer was intercepting the
  initial `mousedown`/`pointerdown` before the browser could pass it to the
  native `<select>`. Fixed by adding `stopPropagation()` on both events for
  all `<select>` elements in the arm actions rows.

### Changed
- **No schema migration required** — all new logging data is stored in the
  existing `details` TEXT column as JSON. No `ALTER TABLE` needed.
- **Addon config** — `zwave_server_url`, `log_level`, and `debug_logging`
  options are now hidden behind the "Show unused optional configuration
  options" toggle in the HA addon config UI via the `advanced` block.
  Reduces clutter for users who don't need to change these defaults.

## [2.0.2] - 2026-04-07

### Added
- **Arm Actions** — Security tab now has an "Arm Actions" section with separate
  configuration for Arm Home and Arm Away. Each action specifies an entity
  (`lock.*` or `cover.*`), an action (Lock / Close), and a delay in seconds
  from when the arm command is received. Actions fire server-side via the HA
  supervisor API so they work regardless of which source triggers the arm
  (card, HA service, automation, voice).
- **Audio alerts** via HA `media_player` entities — Devices tab in admin panel
  allows selecting one or more media players for alarm tones. Three bundled
  MP3 files copied to `/config/www/community/homesecure/` on startup:
  `beep_short.mp3` (150ms, arm countdown + disarm confirm),
  `beep_long.mp3` (600ms, armed confirmation),
  `beep_entry.mp3` (400ms lower pitch, entry delay warning).
  Badge card plays tones on state transitions: short beep every 2s during
  arming, long beep on armed, entry beep every 2s during pending, short
  confirm on disarm.
- **Expandable event log rows** — clicking any event row in the Events tab
  expands it to show full details: user, full timestamp, entity, previous
  state, new state, mode, zone, IP address, and any other available fields.
- **Debug logging in addon config tab** — `debug_logging: false` option added
  to `config.yaml`. When enabled, overrides `log_level` and forces the Python
  service to `DEBUG` level. Accessible even when the admin card won't load.
- **`POST /api/locks/sync-user`** — sync one user to all locks with a provided
  PIN; used by the re-enable PIN dialog.
- **`POST /api/users/{id}/remove-from-locks`** — remove a user's codes from
  all locks; called automatically when a user is disabled.
- **`POST /api/locks/users/{id}/verify`** — targeted verify for one user
  rather than a full sync of all users; used by the Verify Status button.
- **`GET /api/locks/users/{id}`** — returns per-lock access state for one user.
- **`POST /api/debug/clear-lockout`** — clears failed attempts without restart.

### Fixed
- **Arm without PIN no longer triggers failed attempt counter** — when
  `require_pin_to_arm` is false and no PIN is provided, arming succeeds
  without touching the failed-attempts counter. Previously every arm button
  click counted as a failed auth attempt, causing phantom lockouts.
- **UTC timezone mismatch** — all `datetime.now()` calls replaced with
  `datetime.utcnow()` to match SQLite `CURRENT_TIMESTAMP` (UTC). Previously
  the timezone offset caused failed attempts to appear recent long after they
  had expired, causing lockouts to persist far longer than configured.
- **`database.update_user()` now accepts `enabled` parameter** — was causing
  a 500 error when toggling user enable/disable.
- **Z-Wave lock discovery** — detects locks via value_id string parsing
  (`nodeId-CC-endpoint-property-key`) since `node.command_classes` returns
  empty in current zwave-js-server-python versions. 2-second delay added
  after driver ready to allow node values to fully populate.
- **`get_user_lock_status()` added to lock_manager** — was missing, causing
  500 on all lock UI operations.
- **`GET /api/users` returns `{"users": [...]}` format consistently.**
- **Internal config changes** (service_pin) no longer logged as user-visible
  config_updated events.
- **CORS middleware** — fixes browser cards being blocked when calling the
  container API across ports (HA on 8123, container on 8099).
- **Admin card tab content** — correctly matches the active tab when
  re-entering the admin panel. Previously `_currentView` state from the Users
  tab leaked into other tabs, showing the user list regardless of which tab
  was active.
- **Admin card scroll position** saved and restored across renders.
- **`updatePinDisplay()`** now enables the `confirm-arm` button as well as
  the `disarm` button — previously the arm PIN keypad's enter button was
  never enabled.
- **Stale localStorage lockout state** cleared on card load and synced from
  server.
- **`loadUsers()` calls `render()`** after loading so the user list refreshes
  immediately without requiring a separate interaction.
- **User enable/disable toggle** now uses `PUT` (was incorrectly `POST`).
- **Lock PIN cache** populated from locks on container startup so
  enable/disable operations work after restart without re-entering PINs.
- **Lock PIN persisted to DB** after sync so re-enable works after container
  restart.
- **Re-enable flow** — when re-enabling a user, if cached PIN is available the
  lock access is restored automatically; otherwise a PIN keypad dialog prompts
  the admin for the user's PIN.
- **Entry point config editor** — field changes now create new object
  references so HA detects and saves changes correctly (direct mutation was
  silently ignored by HA's config-changed event handler).
- **OptionsFlow 500** — `config_entry` removed from constructor call; HA sets
  `self.config_entry` automatically in 2024.11+.
- **Bootstrap flow** — `/api/bootstrap` endpoint allows first user creation
  without PIN; config flow collects admin name and PIN during setup.
- **`_get_usercode_value()` / `_get_userid_status_value()`** use value_id
  string parsing for reliable operation across library versions.
- **`sync_user_to_locks()` guard** for no managed locks prevents None slot
  crash in log statement.

### Changed
- **Require PIN to arm** — badge card now shows a PIN keypad before sending
  the arm command when `require_pin_to_arm` is enabled. Arm buttons show
  "· PIN required" subtitle hint. Server config fetched once on card load.
- **User disable** — now calls `POST /api/users/{id}/remove-from-locks`
  automatically to clear lock codes when a user is disabled.
- **Verify Status button** — now calls the targeted per-user verify endpoint
  with 30s timeout instead of the full sync endpoint. Much faster.
- **Sync to New button** — calls verify then reloads lock access state with
  visual feedback on completion.
- **Devices tab** — replaced "Coming Soon" placeholder with real media player
  selection UI and volume control.
- **`run.sh`** — reads `debug_logging` option and overrides `LOG_LEVEL` to
  `debug` if set; copies audio MP3 files to Lovelace directory on startup.
- **`config.yaml`** — `debug_logging: false` option added; port 8099 exposed
  for direct LAN browser access.
- **Debug console output** — `console.log` / `console.warn` removed from
  normal card operation. All logging now goes through `_hs` shared logger
  which is silent by default and verbose only when debug mode is enabled
  (admin General tab toggle or `localStorage.setItem('homesecure_debug','1')`).
