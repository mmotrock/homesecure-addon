# HomeSecure Admin Panel

A comprehensive administrative interface for managing users, lock access, security settings, audio alerts, and system configuration.

## Features

- **User Management**: Add, edit, disable, and remove users
- **PIN Management**: Separate PINs for alarm and locks
- **Lock Access Control**: Per-user permissions for individual locks
- **Arm Actions**: Auto-lock doors and close garage doors on arm with configurable delays
- **Audio Alerts**: Beep tones on arming, armed, entry delay, and disarm via HA media players
- **Security**: Lockout after failed attempts, admin re-authentication
- **Audit Trail**: Track user activity and system events with expandable detail rows
- **Responsive Design**: Works on desktop, tablet, and mobile

## Installation

The add-on copies the cards to `/config/www/community/homesecure/` automatically on startup and registers them as Lovelace resources. No manual resource registration is needed.

If you need to register them manually:

1. Go to **Settings** → **Dashboards** → **⋮** → **Resources**
2. Add `/local/community/homesecure/homesecure-card.js` — type: **JavaScript Module**
3. Add `/local/community/homesecure/homesecure-admin.js` — type: **JavaScript Module**
4. Reload your browser

## Basic Configuration

```yaml
type: custom:homesecure-admin
entity: alarm_control_panel.homesecure
```

## Configuration Options

| Parameter | Type | Description |
|-----------|------|-------------|
| `entity` | string | **Required.** Entity ID of the alarm control panel |
| `api_url` | string | Container API URL. Auto-detected from HA hostname. |
| `api_token` | string | API token if configured in the add-on. Default: none |

## How the Admin Card Works (v2.1)

The admin card communicates **directly with the HomeSecure container API** (port 8099) rather than going through Home Assistant services. This means:

- Operations are faster (no HA event round-trip)
- The card works even when HA is reloading
- No HA services are needed for user/lock management

The alarm state (arm/disarm) still flows through the HA `alarm_control_panel` entity so HA automations and notifications work normally.

The API URL is auto-detected from `window.location.hostname` — no configuration needed for standard LAN installs. If you access HA through a reverse proxy or Cloudflare tunnel, port 8099 must also be proxied, or set `api_url` explicitly in the card config.

## Features Overview

### 1. Authentication

- **Admin PIN Required**: Must be an administrator to access the panel
- **Failed Attempt Tracking**: Incorrect PIN entries are counted
- **Automatic Lockout**: Configurable threshold (default 5 attempts = 5-minute lockout)
- **Re-authentication**: Required each time the panel is opened
- **Visual Feedback**: Shows remaining attempts after failures

Lockout behavior:
```
Attempts 1–4 : Warning shown with remaining attempts
Attempt 5    : Panel locked for configured duration (default 5 minutes)
Locked state : Countdown timer displayed
After timeout: Automatically unlocks
```

To clear a lockout immediately without waiting: run
`curl -X POST http://<ha-ip>:8099/api/debug/clear-lockout` from your HA terminal.

### 2. User Management

#### User List
- User avatar with initials
- Name, admin badge, phone number
- Enabled/Disabled status with quick toggle
- Click user to open edit view

#### Add New User

Required:
- Name
- PIN (6–8 digits)

Optional:
- Phone number
- Email address
- Administrator privileges
- Separate lock PIN (6–8 digits)

#### Edit Existing User

All fields are editable. Leave PIN blank to keep the existing one. Admin PIN is required to save any changes.

#### Disable/Enable Users

Toggle the switch next to any user in the list to immediately revoke or restore access without deleting the user. Settings and PIN hashes are preserved.

- **Disabling** removes the user's code from all Z-Wave locks immediately
- **Re-enabling** attempts to restore lock access automatically using the cached PIN. If no cached PIN is available (e.g. after a container restart without an initial sync), a PIN keypad dialog will prompt the admin to enter the user's PIN to restore lock access.

### 3. Lock Access Control

Located in the user edit screen. Each Z-Wave lock discovered by the container is shown with a toggle. Locks are identified by their **name as set in Z-Wave JS UI** — set meaningful names there (e.g. "Front Door", "Back Door") and they will appear here.

```
Front Door      [ ON  ]   Last synced: 2 mins ago
Back Door       [ OFF ]   Last synced: Never
Garage Side     [ ON  ]   Last synced: 5 hours ago ⚠
```

- **Toggling on** writes the user's PIN to that lock via Z-Wave JS
- **Toggling off** clears the code from that slot
- Changes update the database immediately; Z-Wave sync happens in the background
- **Verify Status** — reads the actual Z-Wave state and compares to the database
- **Sync to New** — re-syncs the user to any locks they are enabled on

#### Setting Lock Names

Lock names come from Z-Wave JS UI. To set a meaningful name:
1. Open Z-Wave JS UI (add-on sidebar)
2. Click the lock node
3. Set the **Name** field (e.g. "Front Door")
4. Restart the HomeSecure add-on to reload the names

### 4. PIN Management

**Alarm PIN**
- Used for arming/disarming the alarm system
- 6–8 digits, bcrypt hashed — cannot be viewed after creation
- Counted toward lockout on incorrect entry

**Lock PIN (optional)**
- Separate from the alarm PIN
- Programmed to Z-Wave locks only — does not work for alarm arm/disarm
- Useful for giving cleaning services lock access without alarm access, or for users who should only have physical access

### 5. Security Tab

#### PIN Lockout
| Setting | Default | Range |
|---------|---------|-------|
| Failed attempts before lockout | 5 | 3–20 |
| Lockout duration | 5 minutes | 1–60 minutes |

#### Post-Alarm Behaviour
What happens after the alarm siren duration expires:
- **Stay triggered** — alarm stays active until manually disarmed (default)
- **Auto-disarm** — system disarms itself after the siren duration
- **Auto-rearm** — system returns to the armed mode it was in before the alarm

#### Require PIN to Arm
When enabled, pressing Arm Home or Arm Away on the badge card shows a PIN keypad before sending the arm command. The PIN is validated server-side.

#### Arm Actions
Automatically lock doors or close garage doors when arming. Configured separately for Arm Home and Arm Away.

For each action:
- **Entity** — select any `lock.*` or `cover.*` entity from HA
- **Action** — Lock, Close, or No action
- **Delay** — seconds from when the arm command is received (0 = immediate)

Example Arm Away configuration:
```
Front Door Lock    Lock    0 sec    (locks immediately)
Back Door Lock     Lock    30 sec   (30 second delay)
Double Garage      Close   120 sec  (2 minute delay to exit)
```

Actions fire server-side via the HA supervisor API, so they work regardless of which source triggers the arm (badge card, HA automation, voice assistant).

### 6. General Tab

Configure system timing:

| Setting | Default | Range |
|---------|---------|-------|
| Entry delay | 30 s | 0–300 s |
| Exit delay | 60 s | 0–300 s |
| Alarm siren duration | 300 s | 30–3600 s |
| Lock sync interval | 60 min | 1–1440 min |
| Event log retention | 90 days | 7–365 days |

**Debug Mode** — enables verbose browser console logging for both cards. Useful for diagnosing issues with the card UI. Server-side debug logging is configured in the add-on Configuration tab (`debug_logging: true`).

### 7. Devices Tab

Select which HA media player entities receive alarm audio alerts.

**Alert tones:**
- 🔔 **Arming Away** — short beep every 2 seconds during exit delay, one long beep when fully armed
- 🏠 **Arm Home** — one long beep immediately
- ⚠️ **Entry delay** — longer beep every 2 seconds until disarmed or triggered
- ✅ **Disarm** — one short confirmation beep

To use tablet speakers via the HA Companion app, enable the Media Player sensor in the Companion app settings. The tablet will then appear as a `media_player.*` entity in HA and show up in this list.

**Volume** — sets the playback volume (10–100%). Applied to all selected devices.

### 8. Events Tab

View the recent event log pulled from `/api/logs`:

- State changes (arm/disarm/trigger/pending)
- Lock/unlock events with user attribution
- Failed authentication attempts
- Zone triggers
- Configuration changes
- User add/edit/delete

**Filtering:** by event type or date range.

**Expanding rows:** click any event row to expand it and see full detail — user, exact timestamp, entity, previous state, new state, mode, zone, IP address.

## User Workflow Examples

### Adding a Family Member

1. Open admin panel → enter admin PIN
2. Click **Add User**
3. Name: `Sarah`, PIN: `234567`
4. Optional: toggle **Separate PIN for Locks** → ON, Lock PIN: `890123`
5. Click **Create User** — PIN is synced to all locks where access is enabled

### Enabling Specific Lock Access

1. Click a user → opens edit view
2. Scroll to the lock access section
3. Toggle individual locks on/off
4. Sync happens in the background — check Verify Status to confirm

### Adding a Cleaning Service

1. Click **Add User**
2. Name: `Cleaning`, PIN: `555555`
3. Toggle **Separate PIN for Locks** → ON, Lock PIN: `666666`
4. Enable **Front Door** only — leave all others OFF
5. Click **Create User**

### Temporarily Disabling a User

1. Find the user in the list
2. Toggle the switch next to their name to OFF
3. Lock codes are cleared immediately
4. Toggle ON to re-enable — lock codes are restored if PIN is cached, otherwise a PIN prompt appears

### Configuring Arm Away to Lock All Doors

1. Go to **Security** tab
2. Scroll to **Arm Actions** → **Arm Away**
3. Click **+ Add action** for each door lock
4. Set Entity, Action = Lock, and desired Delay
5. Click **Save Security Settings**

## Security Best Practices

- Use unique PINs for each user — avoid sequential or repeating digits
- 8-digit PINs are stronger than 6-digit
- Use separate lock PINs for users who should have physical access but not alarm control
- Disable users promptly when access should end (preserves audit trail vs. deletion)
- Keep the number of admin users small
- If your HA instance is externally accessible, set an `api_token` in the add-on configuration

## Technical Details

### Authentication Flow

```
1. User enters admin PIN in the card
2. POST /api/auth  { pin }
3. Container verifies PIN with bcrypt
4. Success → admin session granted for this page load
5. Failure → failed attempt logged, lockout checked
```

### Data Storage

All data lives in the container at `/data/homesecure.db` (SQLite):

| Table | Contents |
|-------|----------|
| `alarm_users` | Users, bcrypt PIN hashes, contact info, enabled state |
| `alarm_config` | All settings including timing, security, arm actions |
| `alarm_events` | Full audit log (pruned per retention setting) |
| `user_lock_slots` | Z-Wave slot assignments per user |
| `user_lock_access` | Per-lock enable/disable state + sync status |
| `failed_attempts` | Recent failed PIN attempts |

### Container API Endpoints Used by the Card

```
POST /api/auth                          { pin }
GET  /api/users
POST /api/users                         { name, pin, admin_pin, ... }
PUT  /api/users/{id}                    { admin_pin, name?, pin?, enabled?, ... }
DEL  /api/users/{id}                    { admin_pin }
POST /api/users/{id}/remove-from-locks  {}
GET  /api/locks
GET  /api/locks/users/{id}
POST /api/locks/users/{id}/enable       { lock_entity_id, enabled }
POST /api/locks/users/{id}/verify       {}
POST /api/locks/sync-user               { user_id, pin }
GET  /api/logs                          ?limit=N&days=N&event_types=...
GET  /api/config
POST /api/config                        { admin_pin, setting_key: value, ... }
GET  /api/debug/status
POST /api/debug/clear-lockout
WS   /api/ws                            real-time state stream
```

## Troubleshooting

### Cannot Access Admin Panel
- Verify you are using an admin-level PIN
- Check for lockout — wait for the countdown or run `curl -X POST http://<ha-ip>:8099/api/debug/clear-lockout`
- Confirm the container is running (check add-on logs)
- Check browser console (F12) for connection errors

### Users Not Loading
- Confirm the container is running: `curl http://<ha-ip>:8099/health`
- Check the add-on log for database errors
- Verify `api_url` in card config points to the correct host and port

### Lock Sync Not Working
- Check add-on log for Z-Wave JS connection errors
- Verify `zwave_server_url` in add-on configuration is correct
- Confirm Z-Wave JS add-on is running and the lock is paired/included
- Use **Verify Status** button to check actual lock state vs. database
- Check that lock names are set in Z-Wave JS UI

### Arm Actions Not Firing
- Check add-on logs for `Arm action:` lines — these appear when actions execute
- Verify `hassio_api: true` is in the add-on `config.yaml`
- Confirm the `lock.*` or `cover.*` entity IDs are correct
- The `SUPERVISOR_TOKEN` must be available — this is automatic when `hassio_api: true`

### Audio Alerts Not Playing
- Confirm a media player is selected and saved in the Devices tab
- Check that the MP3 files exist at `/config/www/community/homesecure/`
- Verify the media player entity is available in HA states
- For tablet speakers, enable the Media Player sensor in the HA Companion app

### Changes Not Persisting
- Wait for the confirmation toast notification
- Check the add-on log for API errors
- Confirm the container has write access to `/data/`

## Browser Compatibility

Chrome/Edge, Firefox, Safari, iOS Safari, Chrome Mobile — all fully supported.

## License

Part of the HomeSecure system for Home Assistant. MIT License.
