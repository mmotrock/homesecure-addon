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