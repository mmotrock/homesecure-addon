# HomeSecure - Complete Home Security System for Home Assistant

A professional-grade security system for Home Assistant with alarm control, Z-Wave lock integration, multi-user management, and comprehensive event logging.

<<<<<<< HEAD
![Version](https://img.shields.io/badge/version-2.1.0-blue)
=======
![Version](https://img.shields.io/badge/version-2.0.2-blue)
>>>>>>> fix/v2.0.1
![License](https://img.shields.io/badge/license-MIT-green)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-orange)

## ✨ Features

### 🛡️ Security System
- Advanced alarm control panel with multiple arming modes
- Entry/exit delays with customizable timing
- Zone bypass functionality
- Duress code support for silent alerts
- Failed authentication lockout protection

### 🔐 Lock Management
- Full Z-Wave lock integration via Z-Wave JS
- Automatic user code synchronization across all locks
- Per-lock access control (enable/disable users on specific locks)
- Separate PINs for alarm and locks (optional)
- Lock code verification and sync monitoring

### 👥 User Management
- Multiple users with individual PINs
- Admin and standard user roles
- User enable/disable without deletion
- Complete audit trail of user actions
- Phone and email contact information

### 📊 Logging & Monitoring
- Event tracking (arm/disarm, lock/unlock, garage, zone triggers, etc.)
- Queryable REST API for event history
- Real-time state updates via WebSocket
- Web UI log viewer

### 📱 User Interface
- Lovelace dashboard card
- Admin panel for user/lock management
- Real-time status display
- Mobile-responsive design

### 🚪 Automation
- Auto-lock doors on arm
- Auto-close garage doors on arm
- Configurable delays for locks and garages
- Mobile and SMS notifications
- Custom automation triggers via HA events

## 🏗️ Architecture

HomeSecure v2.0 uses a container-first architecture. All security logic runs inside the add-on container and exposes a REST/WebSocket API. The HA integration is a thin proxy — it reflects state and forwards commands, but contains no business logic of its own.

```
┌─────────────────────────────────────────┐
│         HomeSecure Container            │
│                                         │
│  Alarm State Machine  │  REST + WS API  │
│  User/PIN Database    │  Lock Manager   │
│  Z-Wave JS Client     │  Event Log      │
└──────────────┬──────────────────────────┘
               │ HTTP + WebSocket
               ▼
┌─────────────────────────────────────────┐
│      HA Integration (thin proxy)        │
│   alarm_control_panel  │  sensors       │
│   binary_sensors       │  events        │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│       Lovelace Cards (browser)          │
│   homesecure-card.js                    │
│   homesecure-admin.js                   │
└─────────────────────────────────────────┘
```

### Container API

The container exposes a REST + WebSocket API on port 8099:

```
GET  /api/state          → current alarm state
POST /api/arm_away       { "pin": "..." }
POST /api/arm_home       { "pin": "..." }
POST /api/disarm         { "pin": "..." }
GET  /api/users          → list users
POST /api/users          → add user
PUT  /api/users/{id}     → update user
DEL  /api/users/{id}     → remove user
GET  /api/zones          → list zones
GET  /api/locks          → lock status
POST /api/locks/sync     → sync all users to locks
GET  /api/logs           → recent events
GET  /api/config         → current config
POST /api/config         → update config
WS   /api/ws             → real-time state stream
GET  /health             → health check
```

## 📦 Installation

### Quick Install

1. **Add Repository to Home Assistant**
   - Go to **Settings** → **Add-ons** → **Add-on Store** → **⋮** → **Repositories**
   - Add: `https://github.com/mmotrock/homesecure-addon`
   - Click **Add**

2. **Install Add-on**
   - Find **HomeSecure** in the add-on store
   - Click **Install** (takes 2-5 minutes to build)

3. **Configure Add-on**
   - Click the **Configuration** tab
   - Set your Z-Wave JS Server URL (default usually works)
   - Optionally set an API token for security
   - Click **Save**

4. **Start Add-on**
   - Click **Info** tab → **Start**
   - Enable **Start on boot** and **Watchdog**

5. **Add Integration**
   - Settings → Devices & Services → **Add Integration**
   - Search **HomeSecure**
   - Enter the container URL (default: `http://localhost:8099`)
   - Enter API token if configured
   - Complete setup

6. **Add Lovelace Cards**
   - Settings → Dashboards → Resources
   - Add: `/local/homesecure-card.js` (JavaScript Module)
   - Add: `/local/homesecure-admin.js` (JavaScript Module)
   - Edit dashboard → Add Card → search **HomeSecure**

### Upgrading from v1.x

If you are upgrading from v1.0.x, your existing data is automatically migrated on first startup:

- ✅ All users and bcrypt PIN hashes (no re-enrollment needed)
- ✅ Alarm configuration (delays, notification settings)
- ✅ Lock slot assignments
- ✅ Per-lock access permissions
- ✅ Last 500 audit events

A backup of the original database is created at `/config/homesecure.db.pre_migration_backup` before migration runs. After migration completes successfully, the container writes a flag file so it never runs again.

**After upgrading:**
1. Remove and re-add the HomeSecure integration (config flow has changed)
2. The add-on no longer installs itself into `custom_components/` — install the integration manually from the repository

## 🎯 Quick Start

### Basic Usage

**Arm the System:**
- Tap the badge on your dashboard
- Click **Arm Home** or **Arm Away**

**Disarm:**
- Tap the badge
- Enter your 6-8 digit PIN

**Admin Panel:**
- Click the ⚙ button on the alarm card
- Enter admin PIN
- Manage users, locks, view events, configure settings

### Adding Users

1. Open admin panel (⚙ button)
2. Go to **Users** tab
3. Click **Add User**
4. Enter name and PIN
5. Optionally enable separate lock PIN
6. Click **Create User**

User automatically syncs to all Z-Wave locks.

### Managing Lock Access

1. Open admin panel → Users
2. Select a user
3. Scroll to **Per-Lock Access Control**
4. Toggle locks on/off for that user

## 🔧 Configuration

### Add-on Configuration

```yaml
zwave_server_url: "ws://a0d7b954-zwavejs2mqtt:3000"  # Z-Wave JS Server URL
log_level: "info"                                      # debug|info|warning|error
api_token: ""                                          # Optional — leave blank to disable
```

### System Configuration

Configure timing and notification settings via the admin panel or directly against the container API:

```bash
curl -X POST http://localhost:8099/api/config \
  -H "Content-Type: application/json" \
  -d '{
    "admin_pin": "123456",
    "entry_delay": 30,
    "exit_delay": 60,
    "alarm_duration": 300,
    "auto_lock_on_arm_away": true,
    "lock_delay_away": 60,
    "auto_close_on_arm_away": true,
    "close_delay_away": 60
  }'
```

Or from an HA automation using `rest_command`:

```yaml
rest_command:
  homesecure_update_config:
    url: "http://localhost:8099/api/config"
    method: POST
    content_type: "application/json"
    payload: '{"admin_pin": "{{ pin }}", "entry_delay": {{ delay }}}'
```

## 🔌 HA Services

These HA services are available for use in automations and scripts. All other operations (user management, lock sync, config) are performed directly against the container REST API.

```yaml
# Arm Away
service: homesecure.arm_away
data:
  pin: "123456"          # optional — uses internal service PIN if omitted

# Arm Home
service: homesecure.arm_home
data:
  pin: "123456"

# Disarm
service: homesecure.disarm
data:
  pin: "123456"          # required
```

## 🔒 Security Features

- **PIN Authentication**: 6-8 digit PINs with bcrypt hashing
- **Service PIN**: Auto-generated internal PIN for HA automation calls
- **API Token**: Optional bearer token for the container REST API
- **Failed Attempt Lockout**: 5 attempts triggers a 5-minute lockout
- **Duress Codes**: Silent alert codes that appear to disarm normally
- **Audit Logging**: Complete event history with user attribution
- **Per-Lock Access**: Granular control over which users access which locks

## 📖 Documentation

- **[Changelog](CHANGELOG.md)** — Version history
- **[Admin Panel Guide](www/ADMIN_README.md)** — Managing users and locks

## 📊 System Requirements

- **Home Assistant**: 2024.1.0 or later
- **Memory**: 256MB minimum (512MB recommended)
- **Storage**: 100MB for add-on, database grows with event history
- **Z-Wave**: Z-Wave JS add-on (for lock features)

## 💡 Tips & Best Practices

1. **Enable Watchdog**: Ensures the add-on restarts automatically if it crashes
2. **Set an API Token**: Protects the container API if your HA instance is exposed externally
3. **Use Separate PINs**: Different PINs for alarm vs locks limits exposure if one is compromised
4. **Set Up a Duress Code**: Configure a duress code for emergency situations
5. **Monitor Sync Errors**: Check `/api/locks` periodically to verify lock codes are in sync
6. **Backup the Database**: `/data/homesecure.db` is the single source of truth in v2.0

## 🤝 Contributing

Contributions welcome! Please fork, create a feature branch, test thoroughly, and submit a pull request.

## 📝 License

MIT License — See [LICENSE](LICENSE) file

## ⚠️ Disclaimer

HomeSecure is a DIY security system for personal use. It should not be relied upon as the sole security measure for your home. Always follow local regulations and consider professional monitoring for critical security needs.

---

**Built with ❤️ for the Home Assistant Community**
