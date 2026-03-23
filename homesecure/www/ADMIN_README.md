# HomeSecure Admin Panel

A comprehensive administrative interface for managing users, lock access, security settings, and system configuration.

## Features

- **User Management**: Add, edit, disable, and remove users
- **PIN Management**: Separate PINs for alarm and locks
- **Lock Access Control**: Per-user permissions for individual locks
- **Security**: Lockout after failed attempts, admin re-authentication
- **Audit Trail**: Track user activity and system events
- **Responsive Design**: Works on desktop, tablet, and mobile

## Installation

The add-on copies the cards to `/config/www/` automatically on startup. You just need to register them as Lovelace resources:

1. Go to **Settings** → **Dashboards** → **Resources**
2. Click **Add Resource**
3. Add `/local/homesecure-card.js` — type: **JavaScript Module**
4. Add `/local/homesecure-admin.js` — type: **JavaScript Module**
5. Reload your browser

## Basic Configuration

```yaml
type: custom:homesecure-admin
entity: alarm_control_panel.homesecure
```

## Configuration Options

| Parameter | Type | Description |
|-----------|------|-------------|
| `entity` | string | **Required.** Entity ID of the alarm control panel |
| `api_url` | string | Container API URL. Default: `http://localhost:8099` |
| `api_token` | string | API token if configured in the add-on. Default: none |

## How the Admin Card Works (v2.1)

In v2.1 the admin card communicates **directly with the HomeSecure container API** (`http://localhost:8099`) rather than going through Home Assistant services. This means:

- Operations are faster (no HA event round-trip)
- The card works even when HA is reloading
- No HA services are needed for user/lock management

The alarm state (arm/disarm) still flows through the HA `alarm_control_panel` entity so HA automations and notifications work normally.

## Features Overview

### 1. Authentication

- **Admin PIN Required**: Must be an administrator to access the panel
- **Failed Attempt Tracking**: Incorrect PIN entries are counted
- **Automatic Lockout**: 5 failed attempts = 5-minute lockout
- **Re-authentication**: Required each time the panel is opened
- **Visual Feedback**: Shows remaining attempts after failures

Lockout behavior:
```
Attempts 1–4 : Warning shown with remaining attempts
Attempt 5    : Panel locked for 5 minutes
Locked state : Countdown timer displayed
After 5 min  : Automatically unlocks
```

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
- Per-lock access toggles

#### Edit Existing User

All fields are editable. Leave PIN blank to keep the existing one. Admin PIN is required to save any changes.

#### Disable/Enable Users

Toggle the switch next to any user in the list to immediately revoke or restore access without deleting the user. Settings and PIN hashes are preserved. Disabled users are removed from all lock slots automatically.

### 3. Lock Access Control

Located in the user edit screen. Each Z-Wave lock discovered by the container is shown with a toggle:

```
Front Door Lock     [ ON  ]
Back Door Lock      [ OFF ]
Garage (if cover)   [ ON  ]
```

- Toggling on writes the user's code to that lock via Z-Wave JS
- Toggling off clears the code from that slot
- Changes update the database immediately and sync to Z-Wave in the background
- A sync status indicator shows the last sync result

### 4. PIN Management

**Alarm PIN**
- Used for arming/disarming
- 6–8 digits, bcrypt hashed
- Cannot be viewed after creation

**Lock PIN (optional)**
- Separate from the alarm PIN
- Used only for physical lock access
- Useful for: giving cleaning services lock access without alarm access, or limiting what children can do

### 5. Settings Tab

Configure system timing directly from the admin panel:

- Entry delay (seconds)
- Exit delay (seconds)
- Alarm duration (seconds)
- Auto-lock on arm away/home
- Lock and garage delays
- Mobile/SMS notification toggles

Changes are posted to `/api/config` on the container immediately.

### 6. Events Tab

View the recent event log pulled from `/api/logs`:

- State changes (arm/disarm/trigger)
- Lock/unlock events with user attribution
- Failed authentication attempts
- Zone triggers
- Configuration changes

Filter by event type or date range.

## User Workflow Examples

### Adding a Family Member

1. Open admin panel → enter admin PIN
2. Click **Add User**
3. Name: `Sarah`, PIN: `234567`
4. Toggle **Separate PIN for Locks**: ON, Lock PIN: `890123`
5. Enable **Front Door** and **Garage** access
6. Click **Create User** — syncs to locks automatically

### Adding a Cleaning Service

1. Open admin panel → enter admin PIN
2. Click **Add User**
3. Name: `Cleaning Service`, PIN: `555555`
4. Toggle **Separate PIN for Locks**: ON, Lock PIN: `666666`
5. Enable **Front Door** only — leave all others OFF
6. Click **Create User**

### Temporarily Disabling a User

1. Find the user in the list
2. Toggle the switch next to their name
3. Access is revoked immediately — lock code is cleared
4. Toggle again to re-enable and re-sync

### Changing Which Locks a User Can Access

1. Click user → Edit
2. Scroll to lock access section
3. Toggle locks on/off
4. Changes apply immediately

## Security Best Practices

- Use unique PINs for each user — avoid sequential or repeating digits
- 8-digit PINs are stronger than 6-digit
- Use separate lock PINs for users who should have physical access but not alarm control
- Disable users promptly when access should end (preserves audit trail vs. deletion)
- Keep the number of admin users small
- If your HA instance is externally accessible, set an API token in the add-on configuration

## Technical Details

### Authentication Flow

```
1. User enters admin PIN in the card
2. POST /api/users (or other endpoint) with admin_pin in body
3. Container verifies PIN with bcrypt
4. Success → operation proceeds
5. Failure → failed attempt logged, lockout checked
```

### Data Storage

All data lives in the container at `/data/homesecure.db` (SQLite):

| Table | Contents |
|-------|----------|
| `alarm_users` | Users, bcrypt PIN hashes, contact info |
| `alarm_config` | Timing + notification settings |
| `alarm_events` | Full audit log |
| `user_lock_slots` | Z-Wave slot assignments per user |
| `user_lock_access` | Per-lock enable/disable state + sync status |
| `failed_attempts` | Recent failed PIN attempts |

### Container API Endpoints Used by the Card

```
POST /api/arm_away      { pin }
POST /api/arm_home      { pin }
POST /api/disarm        { pin }
GET  /api/users
POST /api/users         { name, pin, admin_pin, ... }
PUT  /api/users/{id}    { admin_pin, name?, pin?, ... }
DEL  /api/users/{id}    { admin_pin }
GET  /api/locks
POST /api/locks/users/{id}/enable  { lock_entity_id, enabled }
GET  /api/logs
GET  /api/config
POST /api/config        { admin_pin, entry_delay, ... }
WS   /api/ws            real-time state stream
```

## Troubleshooting

### Cannot Access Admin Panel
- Verify you are using an admin-level PIN
- Check for lockout — wait 5 minutes or restart the add-on
- Confirm the container is running (check add-on logs)

### Users Not Loading
- Confirm the container is running: `http://localhost:8099/health`
- Check the add-on log for database errors
- Verify the `api_url` card config matches the actual container URL

### Lock Sync Not Working
- Check the add-on log for Z-Wave JS connection errors
- Verify the `zwave_server_url` in add-on configuration is correct
- Confirm Z-Wave JS add-on is running and the lock is included
- Use the **Verify Status** button to check actual lock state vs. database

### Changes Not Persisting
- Wait for the confirmation toast message
- Check the add-on log for API errors
- Confirm the container has write access to `/data/`

## Browser Compatibility

Chrome/Edge, Firefox, Safari, iOS Safari, Chrome Mobile — all fully supported.

## License

Part of the HomeSecure system for Home Assistant. MIT License.
