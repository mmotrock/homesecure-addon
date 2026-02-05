# HomeSecure - Complete Home Security System for Home Assistant

A professional-grade security system for Home Assistant with alarm control, Z-Wave lock integration, multi-user management, and comprehensive event logging.

![Version](https://img.shields.io/badge/version-1.0.0-blue)
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
- Dedicated logging system with queryable database
- Event tracking (arm/disarm, lock/unlock, garage, etc.)
- Per-component log filtering
- 30-day log retention
- Web UI for log viewing

### 📱 User Interface
- Beautiful Lovelace dashboard card
- Admin panel for user/lock management
- Real-time status display
- Entry point monitoring with battery levels
- Mobile-responsive design

### 🚪 Automation
- Auto-lock doors on arm
- Auto-close garage doors on arm
- Configurable delays for locks and garages
- Mobile and SMS notifications
- Custom automation triggers

## 📦 Installation

### Quick Install

1. **Add Repository to Home Assistant**
   - Go to **Supervisor** → **Add-on Store** → **⋮** → **Repositories**
   - Add: `https://bitbucket.org/YOUR_USERNAME/homesecure-addon`
   - Click **Add**

2. **Install Add-on**
   - Find **HomeSecure** in the add-on store
   - Click **Install** (takes 2-5 minutes)

3. **Configure**
   - Click **Configuration** tab
   - Set admin name and PIN (6-8 digits)
   - Set Z-Wave JS Server URL (default usually works)
   - Click **Save**

4. **Start Add-on**
   - Click **Info** tab → **Start**
   - Enable **Start on boot** and **Watchdog**

5. **Restart Home Assistant**
   - Settings → System → Restart

6. **Add Integration**
   - Settings → Devices & Services → **Add Integration**
   - Search "HomeSecure"
   - Enter admin name and PIN from step 3
   - Complete setup

7. **Add Lovelace Cards**
   - Settings → Dashboards → Resources
   - Add: `/local/homesecure-card.js` (JavaScript Module)
   - Add: `/local/homesecure-admin.js` (JavaScript Module)
   - Edit dashboard → Add Card → "HomeSecure Card"

## 🎯 Quick Start

### Basic Usage

**Arm the System:**
- Tap the badge on your dashboard
- Click **Arm Home** or **Arm Away** (no PIN required)

**Disarm:**
- Tap the badge
- Enter your 6-8 digit PIN
- Click checkmark

**Admin Panel:**
- Click the ⚕ button on the alarm card
- Enter admin PIN
- Manage users, locks, view events, configure settings

### Adding Users

1. Open admin panel (⚕ button)
2. Go to **Users** tab
3. Click **Add User**
4. Enter name and PIN
5. Optionally enable separate lock PIN
6. Click **Create User**

User automatically syncs to all locks!

### Managing Lock Access

1. Open admin panel → Users
2. Select a user
3. Scroll to **Per-Lock Access Control**
4. Toggle locks on/off for that user
5. Click **Verify Status** to check actual lock state

## 🔧 Configuration

### Add-on Configuration

```yaml
admin_name: "Admin"           # Default administrator name
admin_pin: "123456"           # 6-8 digit admin PIN
zwave_server_url: "ws://..." # Z-Wave JS Server WebSocket URL
log_level: "info"             # debug, info, warning, error
```

### System Configuration

Configure via admin panel or services:

```yaml
service: homesecure.update_config
data:
  admin_pin: "123456"
  entry_delay: 30              # seconds
  exit_delay: 60               # seconds
  alarm_duration: 300          # seconds
  auto_lock_on_arm_away: true
  lock_delay_away: 60          # seconds
  auto_close_on_arm_away: true
  close_delay_away: 60         # seconds
```

## 📖 Documentation

- **[Setup Guide](SETUP_FROM_SCRATCH.md)** - Complete build instructions
- **[Quick Build](QUICK_BUILD.md)** - Fast reference for building
- **[Troubleshooting](TROUBLESHOOTING.md)** - Common issues and solutions
- **[File Structure](FILE_STRUCTURE.md)** - Repository layout
- **[Changelog](CHANGELOG.md)** - Version history

## 🔌 Services

### Alarm Control

```yaml
# Arm Away
service: homesecure.arm_away
data:
  pin: "123456"

# Arm Home  
service: homesecure.arm_home
data:
  pin: "123456"

# Disarm
service: homesecure.disarm
data:
  pin: "123456"
```

### User Management

```yaml
# Add User
service: homesecure.add_user
data:
  name: "John Doe"
  pin: "654321"
  admin_pin: "123456"
  is_admin: false
  has_separate_lock_pin: true
  lock_pin: "111111"

# Update User
service: homesecure.update_user
data:
  user_id: 2
  name: "Jane Doe"
  phone: "+15551234567"
  admin_pin: "123456"

# Remove User
service: homesecure.remove_user
data:
  user_id: 2
  admin_pin: "123456"
```

### Lock Management

```yaml
# Verify Lock Access
service: homesecure.verify_user_lock_access
data:
  user_id: 2

# Sync to New Locks
service: homesecure.sync_user_to_new_locks
data:
  user_id: 2

# Get User PIN from Lock
service: homesecure.get_user_pin
data:
  user_id: 2
```

## 🏗️ Architecture

### Components

**Add-on Container:**
- Runs independently of Home Assistant
- Installs integration and cards automatically
- Provides web management interface
- Aggregates logs to database
- Manages lock synchronization

**Home Assistant Integration:**
- Alarm control panel entity
- Sensors and binary sensors
- Service calls for all functions
- State management and coordination
- Event logging

**Lovelace Cards:**
- Main alarm control card
- Admin management panel
- Real-time status updates
- User and lock management

### Data Flow

```
User Interaction (Card)
    ↓
Home Assistant Services
    ↓
Integration (Alarm Coordinator)
    ↓
Database ← → Lock Manager ← → Z-Wave JS
    ↓
Event Logging → Log Service → Web UI
```

## 🔒 Security Features

- **PIN Authentication**: 6-8 digit PINs with bcrypt hashing
- **Service PIN**: Internal secure authentication for automation
- **Failed Attempt Lockout**: 5 attempts = 5 minute lockout
- **Duress Codes**: Silent alert codes for emergencies
- **Audit Logging**: Complete event history with user attribution
- **Per-Lock Access**: Granular control over lock permissions

## 🎨 Screenshots

### Alarm Card
![Alarm Card](docs/images/alarm-card.png)

### Admin Panel
![Admin Panel](docs/images/admin-panel.png)

### Web Management
![Web UI](docs/images/web-ui.png)

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📝 License

MIT License - See [LICENSE](LICENSE) file

## 🙏 Acknowledgments

- Home Assistant community
- Z-Wave JS team
- All contributors

## 📞 Support

- **Issues**: [Bitbucket Issues](https://bitbucket.org/YOUR_USERNAME/homesecure-addon/issues)
- **Documentation**: This repository
- **Community**: Home Assistant forums

## ⚠️ Disclaimer

HomeSecure is a DIY security system intended for personal use. While designed with security best practices, it should not be relied upon as the sole security measure for your home. Always follow local regulations and consider professional monitoring services for critical security needs.

**Not suitable for:**
- Commercial security installations
- Life-safety applications
- Professional monitoring services (without additional integration)

**Recommended for:**
- Home automation enthusiasts
- DIY home security
- Integration with existing professional systems
- Smart home access control

## 🚀 Roadmap

### v1.1.0 (Planned)
- [ ] Professional monitoring integration
- [ ] SMS notification support
- [ ] Video camera integration
- [ ] Mobile app companion

### v1.2.0 (Future)
- [ ] Zigbee lock support
- [ ] Bluetooth lock support
- [ ] Geofencing integration
- [ ] Voice assistant integration

## 📊 System Requirements

- **Home Assistant**: 2024.1.0 or later
- **Memory**: 256MB minimum (512MB recommended)
- **Storage**: 100MB for add-on, 50MB for logs
- **Z-Wave**: Z-Wave JS integration (for lock features)
- **Network**: Local network access to Z-Wave JS server

## 🔄 Update Instructions

When updates are available:

1. Supervisor → HomeSecure → Update
2. Wait for update to complete
3. Restart add-on if prompted
4. Check changelog for breaking changes
5. Test all functionality

## 💡 Tips & Best Practices

1. **Backup Database**: Regularly backup `/config/homesecure.db`
2. **Test Codes**: Verify lock codes after adding users
3. **Monitor Logs**: Check for sync errors in web UI
4. **Use Separate PINs**: Different PINs for alarm vs locks
5. **Enable Auto-Lock**: Automatically secure doors on arm
6. **Set Up Duress**: Configure a duress code for emergencies
7. **Regular Updates**: Keep add-on updated for security patches

---

**Built with ❤️ for the Home Assistant Community**