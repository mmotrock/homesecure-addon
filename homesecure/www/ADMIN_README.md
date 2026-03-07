# Secure Alarm Admin Panel

A comprehensive administrative interface for managing users, devices, security settings, and system configuration for the Secure Alarm System.

## Features

- **User Management**: Add, edit, disable, and remove users
- **PIN Management**: Separate PINs for alarm and locks
- **Lock Access Control**: Per-user permissions for individual locks/garages
- **Security Features**: Lockout after failed attempts, admin re-authentication
- **Audit Trail**: Track user activity and changes
- **Responsive Design**: Works on desktop, tablet, and mobile

## Installation

1. Copy `homesecure-admin.js` to `/config/www/homesecure-admin.js`
2. Add to Lovelace resources:
   - Go to Settings → Dashboards → Resources
   - Click "Add Resource"
   - URL: `/local/homesecure-admin.js`
   - Resource type: `JavaScript Module`

## Basic Configuration

```yaml
type: custom:homesecure-admin
entity: alarm_control_panel.homesecure
```

## Configuration Options

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `entity` | string | **Required.** Entity ID of your secure alarm control panel (e.g., `alarm_control_panel.homesecure`) |

**Note:** The admin panel has minimal configuration - it automatically adapts to your system's users, locks, and settings.

## Features Overview

### 1. Authentication

#### Security Features
- **Admin PIN Required**: Must be administrator to access panel
- **Failed Attempt Tracking**: Tracks incorrect PIN entries
- **Automatic Lockout**: 5 failed attempts = 5-minute lockout
- **Persistent Lockout**: Lockout persists across browser sessions
- **Re-authentication**: Required each time panel is opened
- **Visual Feedback**: Shows remaining attempts after failures

#### Lockout Behavior
```
Attempt 1-4: Shows warning with remaining attempts
Attempt 5: Locks panel for 5 minutes
Locked: Displays countdown timer
After 5 min: Automatically unlocks
```

### 2. User Management

#### User List View

**Display Information:**
- User avatar with initials
- User name
- Admin badge (if applicable)
- Phone number (if configured)
- Enabled/Disabled status badge
- Quick enable/disable toggle

**Actions:**
- Click user to edit details
- Toggle enabled/disabled without opening
- Disabled users are grayed out and can't be edited

#### Add New User

**Required Fields:**
- Name (e.g., "John Smith")
- PIN (6-8 digits)

**Optional Fields:**
- Phone number (for notifications)
- Email address (for notifications)
- Administrator privileges toggle
- Separate lock PIN option
- Lock PIN (6-8 digits, if enabled)
- Lock/garage access permissions

**Validation:**
- PIN must be 6-8 digits
- Lock PIN must be 6-8 digits (if enabled)
- All fields are validated before submission
- Admin PIN required to create user

#### Edit Existing User

**Editable Fields:**
- Name
- PIN (leave blank to keep existing)
- Phone number
- Email address
- Administrator status
- Separate lock PIN toggle
- Lock PIN (shows ••••••, enter new to change)
- Lock/garage access permissions

**Actions:**
- Save changes
- Delete user (with confirmation)
- Cancel (return to list)

**Security:**
- Admin PIN required for all changes
- PIN changes are immediate
- Deleted users cannot be recovered

#### Disable/Enable Users

**Purpose:**
- Temporarily revoke access without deleting
- Useful for temporary workers, guests
- Preserves user settings and history

**Behavior:**
- Disabled users cannot authenticate
- Settings and PINs are preserved
- Can re-enable at any time
- Shown in list with "Disabled" badge

### 3. Lock Access Control

#### Features
- Per-user lock/garage permissions
- Visual toggle for each lock
- Automatic detection of lock entities
- Separate from alarm PIN access

#### Configuration
Located in user edit screen, below lock PIN field.

**Display:**
```
Determine which locks the user can access

[Front Door Lock]          [Toggle: ON ]
[Back Door Lock]           [Toggle: OFF]
[Garage Door]              [Toggle: ON ]
[Side Gate Lock]           [Toggle: OFF]
```

**Detected Entities:**
- `lock.*` entities (door locks, smart locks)
- `cover.*` entities (garage doors, gates)

**No Locks Found:**
Displays message: "No locks or garage doors found in your system."

#### Access Permissions
- Each user can have different access
- Admin users don't automatically have all access
- Toggle on = user can lock/unlock with their lock PIN
- Toggle off = user cannot control that lock

### 4. PIN Management

#### Alarm PIN
- Used for arming/disarming the alarm
- Required for all users
- 6-8 digits
- BCrypt hashed in database
- Cannot be viewed after creation

#### Lock PIN (Optional)
- Separate from alarm PIN for security
- Optional per user
- Used only for locking/unlocking
- 6-8 digits
- Shows ••••••when set
- Enter new PIN to change

**Use Cases for Separate Lock PIN:**
- Give cleaning service lock access without alarm access
- Kids can unlock doors but not disarm alarm
- Different security levels for different actions

### 5. Tab Navigation

#### Users Tab
- User list and management
- Add, edit, disable, delete users
- Configure lock access
- Primary admin function

#### Devices Tab
**Coming Soon:** Device management features
- Zone sensors
- Keypads
- Sirens
- Integration status

#### Security Tab
**Coming Soon:** Security settings
- Failed attempt configuration
- Lockout duration
- Duress code settings
- Audit log viewer

#### General Tab
**Coming Soon:** System settings
- Entry/exit delays
- Alarm duration
- Notification settings
- System information

## User Workflow Examples

### Adding a Family Member

1. Open admin panel (gear icon)
2. Enter admin PIN
3. Click "Add User"
4. Enter name: "Sarah"
5. Enter PIN: "123456"
6. Enter phone: "+15551234567"
7. Toggle "Separate PIN for Locks": ON
8. Enter lock PIN: "789012"
9. Enable "Front Door Lock" access
10. Enable "Garage Door" access
11. Click "Create User"

### Adding a Cleaning Service

1. Open admin panel
2. Enter admin PIN
3. Click "Add User"
4. Enter name: "Cleaning Service"
5. Enter PIN: "555555"
6. Toggle "Separate PIN for Locks": ON
7. Enter lock PIN: "666666"
8. Enable "Front Door Lock" only
9. Leave admin toggle OFF
10. Click "Create User"

### Temporarily Disabling a User

1. Find user in list
2. Toggle switch next to user (no need to open)
3. User immediately loses access
4. User shows "Disabled" badge
5. Toggle again to re-enable

### Changing Lock Access

1. Click user to edit
2. Scroll to "Determine which locks the user can access"
3. Toggle locks on/off as needed
4. Changes save immediately
5. Click "Back to Users"

## Security Best Practices

### PIN Security
- Use unique PINs for each user
- 8 digits more secure than 6
- Avoid sequential numbers (123456)
- Avoid repeating numbers (111111)
- Change PINs periodically

### Lock PIN Strategy
- Different from alarm PIN
- Only give to trusted individuals
- Change when person leaves access
- Monitor lock usage logs

### User Management
- Disable users instead of deleting (preserves audit trail)
- Review user list regularly
- Remove access immediately when not needed
- Limit number of admin users

### Admin Access
- Keep admin PIN private
- Change admin PIN if compromised
- Only grant admin to trusted individuals
- Admin can modify all settings

## Technical Details

### Data Storage
- User data stored in SQLite database
- PINs hashed with bcrypt (one-way encryption)
- Lock access stored in `user_lock_access` table
- Failed attempts tracked in `failed_attempts` table

### Authentication Flow
```
1. User enters PIN
2. PIN hashed with bcrypt
3. Compared to stored hash
4. Match = authenticated
5. No match = failed attempt logged
6. 5 failures = 5-minute lockout
```

### Lock Access Storage
```sql
user_lock_access table:
- user_id: User ID
- lock_entity_id: Entity ID of lock/garage
- created_at: When access was granted
```

### Lockout Mechanism
- Failed attempts stored with timestamp
- Count attempts in last 5 minutes
- >= 5 attempts = locked out
- Lockout stored in localStorage
- Persists across browser restarts
- Auto-clears after 5 minutes

## Troubleshooting

### Cannot Access Admin Panel
- Verify you're using admin PIN
- Check for lockout (wait 5 minutes)
- Clear browser cache
- Check browser console for errors

### Users Not Loading
- Check database connectivity
- Verify `homesecure.get_users` service exists
- Check Home Assistant logs
- Try reloading integration

### Lock Access Not Saving
- Verify locks exist in Home Assistant
- Check entity IDs are correct
- Ensure admin PIN is correct
- Check browser console for errors

### Visual Editor Not Working
- Clear browser cache
- Reload Lovelace resources
- Check JavaScript console
- Try manual YAML configuration

### Changes Not Persisting
- Wait for confirmation message
- Check database file permissions
- Review Home Assistant logs
- Verify service calls succeed

## API / Service Calls

The admin panel uses these Home Assistant services:

### User Management
```yaml
# Get all users
service: homesecure.get_users

# Add user
service: homesecure.add_user
data:
  name: "John Doe"
  pin: "123456"
  admin_pin: "admin_pin_here"
  is_admin: false
  phone: "+15551234567"
  email: "john@example.com"
  has_separate_lock_pin: true
  lock_pin: "789012"

# Update user
service: homesecure.update_user
data:
  user_id: 2
  name: "Jane Doe"
  admin_pin: "admin_pin_here"

# Remove user
service: homesecure.remove_user
data:
  user_id: 2
  admin_pin: "admin_pin_here"

# Toggle user enabled
service: homesecure.toggle_user_enabled
data:
  user_id: 2
  enabled: false
  admin_pin: "admin_pin_here"
```

### Lock Access
```yaml
# Set lock access
service: homesecure.set_user_lock_access
data:
  user_id: 2
  lock_entity_id: "lock.front_door"
  can_access: true
  admin_pin: "admin_pin_here"

# Get user's lock access (automatic with get_users)
```

### Authentication
```yaml
# Authenticate admin
service: homesecure.authenticate_admin
data:
  pin: "123456"

# Response via event: homesecure_auth_result
```

## Browser Compatibility

- Chrome/Edge: Full support ✓
- Firefox: Full support ✓
- Safari: Full support ✓
- iOS Safari: Full support ✓
- Chrome Mobile: Full support ✓

## Version History

### 1.0.2
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

## Support

For issues, feature requests, or contributions:
- GitHub: https://github.com/mmotrock/ha-homesecure
- Home Assistant Community: [Link to forum thread]

## License

This admin panel is part of the Secure Alarm System integration for Home Assistant.