"""
HomeSecure Integration for Home Assistant
Custom security system with dedicated authentication and database
"""
import logging
import asyncio
from datetime import timedelta
from typing import Optional

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
#from homeassistant.const import STATE_LOCKED, STATE_UNLOCKED
from homeassistant.components.lock import LockState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval, async_track_state_change_event
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN, CONF_DB_PATH
from .database import AlarmDatabase
from .alarm_coordinator import AlarmCoordinator
from .lock_manager import LockManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["alarm_control_panel", "sensor", "binary_sensor"]

async def _setup_entry_point_tracking(hass: HomeAssistant, entry: ConfigEntry):
    """Set up tracking for entry point state changes."""
    database = hass.data[DOMAIN][entry.entry_id]["database"]
    
    # Track all locks
    lock_entities = hass.states.async_entity_ids('lock')
    
    @callback
    def lock_state_changed(event):
        """Handle lock state change."""
        entity_id = event.data.get('entity_id')
        old_state = event.data.get('old_state')
        new_state = event.data.get('new_state')
        
        if not new_state or not old_state:
            return
        
        # Ignore if state didn't actually change
        if old_state.state == new_state.state:
            return
        
        entity_name = new_state.attributes.get('friendly_name', entity_id)
        
        # Determine event type
        event_type = None
        if new_state.state == LockState.LOCKED and old_state.state == LockState.UNLOCKED:
            event_type = 'door_locked'
        elif new_state.state == LockState.UNLOCKED and old_state.state == LockState.LOCKED:
            event_type = 'door_unlocked'
        
        if event_type:
            # Try to determine user from lock attributes
            user_name = new_state.attributes.get('changed_by')
            user_id = None
            
            # If unlocked with code, try to match user
            if event_type == 'door_unlocked':
                code_slot = new_state.attributes.get('lock_code_slot')
                if code_slot:
                    # Look up user by slot
                    users = database.get_users()
                    for user in users:
                        if user.get('slot_number') == code_slot:
                            user_id = user['id']
                            user_name = user['name']
                            break
            
            # Log the event
            hass.async_add_executor_job(
                database.log_entry_point_event,
                event_type,
                entity_id,
                entity_name,
                user_id,
                user_name,
                {
                    'previous_state': old_state.state,
                    'new_state': new_state.state
                }
            )
            
            _LOGGER.info(f"{event_type}: {entity_name}" + 
                        (f" by {user_name}" if user_name else ""))
    
    # Track all cover entities (garage doors)
    cover_entities = hass.states.async_entity_ids('cover')
    
    @callback
    def cover_state_changed(event):
        """Handle cover/garage state change."""
        entity_id = event.data.get('entity_id')
        old_state = event.data.get('old_state')
        new_state = event.data.get('new_state')
        
        if not new_state or not old_state:
            return
        
        # Only track garage doors
        if 'garage' not in entity_id.lower():
            device_class = new_state.attributes.get('device_class')
            if device_class != 'garage':
                return
        
        # Ignore if state didn't actually change
        if old_state.state == new_state.state:
            return
        
        entity_name = new_state.attributes.get('friendly_name', entity_id)
        
        # Determine event type
        event_type = None
        if new_state.state == 'open' and old_state.state == 'closed':
            event_type = 'garage_opened'
        elif new_state.state == 'closed' and old_state.state == 'open':
            event_type = 'garage_closed'
        elif new_state.state == 'opening':
            event_type = 'garage_opening'
        elif new_state.state == 'closing':
            event_type = 'garage_closing'
        
        if event_type:
            # Log the event
            hass.async_add_executor_job(
                database.log_entry_point_event,
                event_type,
                entity_id,
                entity_name,
                None,  # Usually can't determine user for garage
                None,
                {
                    'previous_state': old_state.state,
                    'new_state': new_state.state
                }
            )
            
            _LOGGER.info(f"{event_type}: {entity_name}")
    
    # Register state change listeners
    async_track_state_change_event(hass, lock_entities, lock_state_changed)
    async_track_state_change_event(hass, cover_entities, cover_state_changed)
    
    _LOGGER.info(f"Entry point tracking set up: {len(lock_entities)} locks, {len(cover_entities)} covers")

def get_service_pin(hass: HomeAssistant, entry_id: str) -> str:
    """Get the secure service PIN for this integration instance."""
    # Retrieve from config entry data
    entry = None
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.entry_id == entry_id:
            entry = config_entry
            break
    
    if not entry:
        _LOGGER.error(f"Config entry {entry_id} not found")
        raise ValueError("Integration not properly configured")
    
    service_pin = entry.data.get("service_pin")
    
    # Debug logging
    _LOGGER.debug(f"Config entry data keys: {list(entry.data.keys())}")
    _LOGGER.debug(f"Service PIN exists: {service_pin is not None}")
    
    if not service_pin:
        _LOGGER.error(f"Service PIN not found in config entry. Available keys: {list(entry.data.keys())}")
        _LOGGER.error("This likely means the integration was set up before the service PIN feature was added.")
        _LOGGER.error("Please remove and re-add the integration to generate a service PIN.")
        raise ValueError("Service PIN not configured")
    
    return service_pin


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the HomeSecure component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HomeSecure from a config entry."""
    
    _LOGGER.info(f"Setting up HomeSecure with entry_id: {entry.entry_id}")
    _LOGGER.debug(f"Config entry data: {list(entry.data.keys())}")
    
    # Migrate old config entries that don't have service_pin
    if "service_pin" not in entry.data:
        _LOGGER.warning("Service PIN not found in config entry - migrating...")
        await _migrate_add_service_pin(hass, entry)
    
    # Initialize database
    db_path = hass.config.path(f"{DOMAIN}.db")
    database = AlarmDatabase(db_path)
    
    # Ensure admin user exists
    await hass.async_add_executor_job(_ensure_admin_user, database, entry)
    
    # Verify service PIN exists
    service_pin = entry.data.get("service_pin")
    if not service_pin:
        _LOGGER.error("Service PIN missing from config entry after migration!")
        _LOGGER.error(f"Available keys in config entry: {list(entry.data.keys())}")
        _LOGGER.error("Please remove and re-add the integration.")
        return False
    
    _LOGGER.info(f"Service PIN verified (length: {len(service_pin)})")
    
    # Initialize coordinator with entry_id
    coordinator = AlarmCoordinator(hass, database, entry.entry_id)
    
    # Initialize lock manager
    zwave_url = entry.data.get("zwave_server_url", "ws://localhost:3000")
    #zwave_url = entry.data.get("zwave_server_url", "ws://a0d7b954-zwavejs2mqtt.local.hass.io:3000")
    lock_manager = LockManager(hass, database, coordinator, zwave_url)
    await lock_manager.async_setup()
    
    # Store in hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "database": database,
        "coordinator": coordinator,
        "lock_manager": lock_manager,
        "entry": entry,  # Store reference to entry
    }
    
    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register services
    await async_setup_services(hass)

    # Set up entry point tracking
    await _setup_entry_point_tracking(hass, entry)
    
    # Start periodic lock sync task
    database = hass.data[DOMAIN][entry.entry_id]["database"]
    lock_manager = hass.data[DOMAIN][entry.entry_id]["lock_manager"]
    
    sync_interval = await hass.async_add_executor_job(database.get_lock_sync_config)
    
    async def _periodic_sync_task():
        """Background task for periodic lock syncing."""
        while True:
            try:
                await asyncio.sleep(sync_interval)
                _LOGGER.debug(f"Running periodic lock sync (interval: {sync_interval}s)")
                await lock_manager.periodic_lock_sync()
            except asyncio.CancelledError:
                _LOGGER.info("Periodic lock sync task cancelled")
                break
            except Exception as e:
                _LOGGER.error(f"Error in periodic lock sync: {e}")
    
    # Store task reference so it can be cancelled/restarted
    hass.data[DOMAIN]["lock_sync_task"] = hass.async_create_task(_periodic_sync_task())
    
    _LOGGER.info(f"HomeSecure initialized successfully (lock sync interval: {sync_interval}s)")
    
    return True


async def _migrate_add_service_pin(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate old config entries by adding a service PIN."""
    import secrets
    
    # Generate a secure 8-digit service PIN
    service_pin = ''.join(str(secrets.randbelow(10)) for _ in range(8))
    
    # Create new data dict with service PIN
    new_data = {**entry.data, "service_pin": service_pin}
    
    # Update the config entry
    hass.config_entries.async_update_entry(entry, data=new_data)
    
    _LOGGER.info(f"✓ Migration complete: Service PIN added to config entry (length: {len(service_pin)})")
    _LOGGER.info("Config entry updated with secure service PIN for internal operations")


def _ensure_admin_user(database: AlarmDatabase, entry: ConfigEntry) -> None:
    """Ensure admin user exists from config entry."""
    try:
        users = database.get_users()
        _LOGGER.info(f"_ensure_admin_user: Found {len(users)} existing users")
        
        if len(users) == 0:
            admin_name = entry.data.get("admin_name", "Admin")
            admin_pin = entry.data.get("admin_pin", "123456")
            
            _LOGGER.info(f"Creating initial admin user: {admin_name}")
            
            user_id = database.add_user(
                name=admin_name,
                pin=admin_pin,
                is_admin=True,
                is_duress=False
            )
            
            if user_id:
                _LOGGER.info(f"✓ Admin user '{admin_name}' created with ID {user_id}")
            else:
                _LOGGER.error(f"✗ Failed to create admin user!")
        else:
            _LOGGER.info(f"Skipping admin creation - {len(users)} users exist")
    except Exception as e:
        _LOGGER.error(f"Error in _ensure_admin_user: {e}", exc_info=True)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        # Cancel periodic sync task
        if "lock_sync_task" in hass.data[DOMAIN]:
            hass.data[DOMAIN]["lock_sync_task"].cancel()
        
        # NEW: Disconnect from Z-Wave JS Server
        lock_manager = hass.data[DOMAIN][entry.entry_id]["lock_manager"]
        if lock_manager._owns_client:
            await lock_manager.async_shutdown()
        
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register services for the alarm system."""
    
    def get_data():
        """Get database and coordinator."""
        entry_id = list(hass.data[DOMAIN].keys())[0]
        return hass.data[DOMAIN][entry_id]
    
    def get_service_pin_for_call() -> str:
        """Get service PIN for current call."""
        entry_id = list(hass.data[DOMAIN].keys())[0]
        return get_service_pin(hass, entry_id)
    
    async def handle_arm_away(call: ServiceCall) -> None:
        """Handle arm away service call."""
        data = get_data()
        coordinator = data["coordinator"]
        
        pin = call.data.get("pin")
        user_code = call.data.get("code")
        
        result = await coordinator.arm_away(pin, user_code)
        
        if not result["success"]:
            _LOGGER.warning(f"Arm away failed: {result['message']}")
    
    async def handle_arm_home(call: ServiceCall) -> None:
        """Handle arm home service call."""
        data = get_data()
        coordinator = data["coordinator"]
        
        pin = call.data.get("pin")
        user_code = call.data.get("code")
        
        result = await coordinator.arm_home(pin, user_code)
        
        if not result["success"]:
            _LOGGER.warning(f"Arm home failed: {result['message']}")
    
    async def handle_disarm(call: ServiceCall) -> None:
        """Handle disarm service call."""
        data = get_data()
        coordinator = data["coordinator"]
        
        pin = call.data.get("pin")
        user_code = call.data.get("code")
        
        result = await coordinator.disarm(pin, user_code)
        
        if not result["success"]:
            _LOGGER.warning(f"Disarm failed: {result['message']}")
    
    async def handle_add_user(call: ServiceCall) -> None:
        """Handle add user service call."""
        data = get_data()
        coordinator = data["coordinator"]
        lock_manager = data["lock_manager"]
        
        name = call.data.get("name")
        pin = call.data.get("pin")
        admin_pin = call.data.get("admin_pin")
        is_admin = call.data.get("is_admin", False)
        is_duress = call.data.get("is_duress", False)
        phone = call.data.get("phone")
        email = call.data.get("email")
        has_separate_lock_pin = call.data.get("has_separate_lock_pin", False)
        lock_pin = call.data.get("lock_pin")
        
        # If no admin_pin provided, use service PIN
        if not admin_pin:
            admin_pin = get_service_pin_for_call()
            _LOGGER.debug("Using service PIN for user creation")
        
        _LOGGER.info(f"Service: add_user called for {name}")
        
        result = await coordinator.add_user(
            name, pin, admin_pin, is_admin, is_duress,
            phone, email, has_separate_lock_pin, lock_pin
        )
        
        if result["success"]:
            _LOGGER.info(f"✓ User {name} added successfully")
            
            # Cache the PIN and sync to locks
            user_id = result.get("user_id")
            if user_id:
                if has_separate_lock_pin and lock_pin:
                    lock_manager.cache_pin(user_id, lock_pin, is_lock_pin=True)
                    await lock_manager.sync_user_to_locks(user_id, lock_pin=lock_pin)
                else:
                    lock_manager.cache_pin(user_id, pin, is_lock_pin=False)
                    await lock_manager.sync_user_to_locks(user_id, pin=pin)
            
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": f"User '{name}' added and synced to {len(lock_manager.get_managed_locks())} lock(s)",
                    "title": "User Added",
                },
            )
        else:
            _LOGGER.warning(f"✗ Add user failed: {result['message']}")
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": f"Failed to add user: {result['message']}",
                    "title": "Add User Failed",
                },
            )
    
    async def handle_remove_user(call: ServiceCall) -> None:
        """Handle remove user service call."""
        data = get_data()
        coordinator = data["coordinator"]
        database = data["database"]
        
        user_id = call.data.get("user_id")
        admin_pin = call.data.get("admin_pin")
        
        # If no admin_pin provided, use service PIN
        if not admin_pin:
            admin_pin = get_service_pin_for_call()
        
        # Log the deletion attempt
        _LOGGER.info(f"Attempting to delete user {user_id}")
        
        # Get user info before deletion for logging
        users = await hass.async_add_executor_job(database.get_users)
        user_to_delete = next((u for u in users if u['id'] == user_id), None)
        
        if user_to_delete:
            _LOGGER.info(f"User to delete: {user_to_delete['name']} (admin: {user_to_delete['is_admin']}, enabled: {user_to_delete['enabled']})")
        
        result = await coordinator.remove_user(user_id, admin_pin)
        
        if result["success"]:
            _LOGGER.info(f"✓ User {user_id} deleted successfully")
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": f"User deleted successfully and removed from locks",
                    "title": "User Deleted",
                },
            )
        else:
            _LOGGER.warning(f"✗ Delete user failed: {result['message']}")
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": f"Failed to delete user: {result['message']}",
                    "title": "Delete Failed",
                },
            )
    
    async def handle_get_users(call: ServiceCall) -> None:
        """Handle get users service call."""
        data = get_data()
        database = data["database"]
        
        users = await hass.async_add_executor_job(database.get_users)
        
        _LOGGER.info(f"Retrieved {len(users)} users")
        
        # Fire event with users
        hass.bus.async_fire(f"{DOMAIN}_users_response", {
            "users": users
        })
    
    async def handle_update_user(call: ServiceCall) -> None:
        """Handle update user service call."""
        data = get_data()
        coordinator = data["coordinator"]
        
        user_id = call.data.get("user_id")
        name = call.data.get("name")
        pin = call.data.get("pin")
        phone = call.data.get("phone")
        email = call.data.get("email")
        is_admin = call.data.get("is_admin", False)
        has_separate_lock_pin = call.data.get("has_separate_lock_pin", False)
        lock_pin = call.data.get("lock_pin")
        admin_pin = call.data.get("admin_pin")
        
        # If no admin_pin provided, use service PIN
        if not admin_pin:
            admin_pin = get_service_pin_for_call()
        
        result = await coordinator.update_user(
            user_id, name, pin, phone, email, is_admin,
            has_separate_lock_pin, lock_pin, admin_pin
        )
        
        if result["success"]:
            # If PIN changed, cache and sync to locks
            if lock_pin:
                lock_manager.cache_pin(user_id, lock_pin, is_lock_pin=True)
                await lock_manager.sync_user_to_locks(user_id, lock_pin=lock_pin)
            elif pin:
                lock_manager.cache_pin(user_id, pin, is_lock_pin=False)
                await lock_manager.sync_user_to_locks(user_id, pin=pin)
            
            _LOGGER.info(f"User {user_id} updated successfully")
        else:
            _LOGGER.warning(f"Update user failed: {result['message']}")
    
    async def handle_bypass_zone(call: ServiceCall) -> None:
        """Handle bypass zone service call."""
        data = get_data()
        coordinator = data["coordinator"]
        
        zone_entity_id = call.data.get("zone_entity_id")
        pin = call.data.get("pin")
        bypass = call.data.get("bypass", True)
        
        result = await coordinator.bypass_zone(zone_entity_id, pin, bypass)
        
        if result["success"]:
            _LOGGER.info(f"Zone {zone_entity_id} bypass set to {bypass}")
        else:
            _LOGGER.warning(f"Bypass zone failed: {result['message']}")
    
    async def handle_update_config(call: ServiceCall) -> None:
        """Handle update configuration service call."""
        data = get_data()
        coordinator = data["coordinator"]
        
        admin_pin = call.data.get("admin_pin")
        
        # If no admin_pin provided, use service PIN
        if not admin_pin:
            admin_pin = get_service_pin_for_call()
        
        config_updates = {
            k: v for k, v in call.data.items()
            if k not in ["admin_pin"]
        }
        
        _LOGGER.info(f"Updating config with: {list(config_updates.keys())}")
        
        result = await coordinator.update_config(admin_pin, config_updates)
        
        if result["success"]:
            _LOGGER.info("Configuration updated successfully")
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": "Configuration updated successfully",
                    "title": "Config Updated",
                },
            )
        else:
            _LOGGER.warning(f"Update config failed: {result['message']}")
    
    async def handle_authenticate_admin(call: ServiceCall) -> None:
        """Authenticate admin PIN and fire result event."""
        data = get_data()
        database = data["database"]
        
        pin = call.data.get("pin")
        
        _LOGGER.info(f"Admin authentication attempt with PIN length {len(pin)}")
        
        # Authenticate the user directly
        user = await hass.async_add_executor_job(
            database.authenticate_user,
            pin,
            None
        )
        
        success = user is not None and user.get('is_admin', False)
        
        _LOGGER.info(f"Admin auth result: success={success}, user={user.get('name') if user else None}, is_admin={user.get('is_admin') if user else False}")
        
        # Fire event with result
        hass.bus.async_fire(f"{DOMAIN}_auth_result", {
            "success": success,
            "is_admin": user.get('is_admin', False) if user else False,
            "user_name": user.get('name') if user else None
        })
    
    async def handle_bootstrap_admin(call: ServiceCall) -> None:
        """Bootstrap admin user - emergency use only."""
        data = get_data()
        database = data["database"]
        
        users = await hass.async_add_executor_job(database.get_users)
        
        admin_name = call.data.get("name", "Admin")
        admin_pin = call.data.get("pin", "123456")
        
        _LOGGER.info(f"Bootstrap admin called - {len(users)} users exist")
        
        user_id = await hass.async_add_executor_job(
            database.add_user,
            admin_name,
            admin_pin,
            True,  # is_admin
            False  # is_duress
        )
        
        if user_id:
            _LOGGER.info(f"✓ Admin '{admin_name}' bootstrapped with ID {user_id}")
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": f"Admin user '{admin_name}' created with ID {user_id}",
                    "title": "Bootstrap Success",
                },
            )
        else:
            _LOGGER.error("✗ Bootstrap admin failed")
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": "Failed to create admin user",
                    "title": "Bootstrap Failed",
                },
            )

    async def handle_toggle_user_enabled(call: ServiceCall) -> None:
        """Handle toggle user enabled service call."""
        data = get_data()
        database = data["database"]
        
        user_id = call.data.get("user_id")
        enabled = call.data.get("enabled")
        admin_pin = call.data.get("admin_pin")
        
        # If no admin_pin provided, use service PIN
        if not admin_pin:
            admin_pin = get_service_pin_for_call()
        
        # Verify admin PIN using service authentication
        user = await hass.async_add_executor_job(
            database.authenticate_user_service,
            admin_pin,
            get_service_pin_for_call()
        )
        
        if not user:
            _LOGGER.warning("Toggle user enabled failed: Admin authentication required")
            return
        
        # Update enabled field directly
        conn = database.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE alarm_users
                SET enabled = ?
                WHERE id = ?
            ''', (int(enabled), user_id))
            conn.commit()
            success = True
        except Exception as e:
            _LOGGER.error(f"Error toggling user enabled: {e}")
            success = False
        finally:
            conn.close()
        
        if success:
            _LOGGER.info(f"User {user_id} enabled status set to {enabled}")
            
            # Sync to locks if being enabled (remove if disabled)
            if not enabled:
                await lock_manager.remove_user_from_locks(user_id)

    #async def handle_set_user_lock_access(call: ServiceCall) -> None:
    #   """Handle set user lock access service call."""
    #    data = get_data()
    #    database = data["database"]
    #    
    #    user_id = call.data.get("user_id")
    #    lock_entity_id = call.data.get("lock_entity_id")
    #    can_access = call.data.get("can_access")
    #    admin_pin = call.data.get("admin_pin")
    #    
    #    # If no admin_pin provided, use service PIN
    #    if not admin_pin:
    #        admin_pin = get_service_pin_for_call()
    #    
    #    # Verify admin PIN
    #    user = await hass.async_add_executor_job(
    #        database.authenticate_user_service,
    #        admin_pin,
    #        get_service_pin_for_call()
    #    )
    #    
    #    if not user:
    #        _LOGGER.warning("Set user lock access failed: Admin authentication required")
    #        return
    #    
    #    success = await hass.async_add_executor_job(
    #        database.set_user_lock_access,
    #        user_id,
    #        lock_entity_id,
    #        can_access
    #    )
    #    
    #    if success:
    #        _LOGGER.info(f"User {user_id} lock access updated for {lock_entity_id}")
    
    async def handle_cleanup_disabled_users(call: ServiceCall) -> None:
        """Permanently delete all disabled users (admin only)."""
        data = get_data()
        database = data["database"]
        
        admin_pin = call.data.get("admin_pin")
        
        # If no admin_pin provided, use service PIN
        if not admin_pin:
            admin_pin = get_service_pin_for_call()
        
        # Verify admin PIN
        user = await hass.async_add_executor_job(
            database.authenticate_user_service,
            admin_pin,
            get_service_pin_for_call()
        )
        
        if not user:
            _LOGGER.warning("Cleanup disabled users failed: Admin authentication required")
            return
        
        # Get all disabled users
        users = await hass.async_add_executor_job(database.get_users)
        disabled_users = [u for u in users if not u['enabled']]
        
        _LOGGER.info(f"Found {len(disabled_users)} disabled users to clean up")
        
        # Delete each disabled user
        conn = database.get_connection()
        cursor = conn.cursor()
        try:
            for user_info in disabled_users:
                _LOGGER.info(f"Permanently deleting disabled user: {user_info['name']} (ID: {user_info['id']})")
                cursor.execute('''
                    DELETE FROM alarm_users
                    WHERE id = ?
                ''', (user_info['id'],))
            
            conn.commit()
            
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": f"Cleaned up {len(disabled_users)} disabled user(s)",
                    "title": "Cleanup Complete",
                },
            )
            
            _LOGGER.info(f"✓ Cleanup complete: {len(disabled_users)} disabled users permanently deleted")
        except Exception as e:
            _LOGGER.error(f"Error during cleanup: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    async def handle_get_config(call: ServiceCall) -> None:
        """Get current configuration and fire event."""
        data = get_data()
        database = data["database"]
        
        config = await hass.async_add_executor_job(database.get_config)
        
        _LOGGER.info(f"Retrieved configuration")
        
        # Fire event with config
        hass.bus.async_fire(f"{DOMAIN}_config_response", {
            "config": config
        })

    async def handle_sync_locks(call: ServiceCall) -> None:
        """Manually sync all users to all locks."""
        data = get_data()
        lock_manager = data["lock_manager"]
        admin_pin = call.data.get("admin_pin")
        
        # If no admin_pin provided, use service PIN
        if not admin_pin:
            admin_pin = get_service_pin_for_call()
        
        # Verify admin PIN
        database = data["database"]
        user = await hass.async_add_executor_job(
            database.authenticate_user_service,
            admin_pin,
            get_service_pin_for_call()
        )
        
        if not user:
            _LOGGER.warning("Sync locks failed: Admin authentication required")
            return
        
        _LOGGER.info("Starting manual lock sync...")
        results = await lock_manager.sync_all_users()
        
        message = f"Synced {results['synced']} users"
        if results['skipped'] > 0:
            message += f", skipped {results['skipped']} (no PIN available)"
        if results['errors']:
            message += f"\n\nErrors:\n" + "\n".join(results['errors'][:5])
        
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "message": message,
                "title": "Lock Sync Complete",
            },
        )

    async def handle_get_lock_status(call: ServiceCall) -> None:
        """Get detailed lock status."""
        data = get_data()
        lock_manager = data["lock_manager"]
        
        status = await lock_manager.get_lock_status()
        
        _LOGGER.info(f"Lock status: {status}")
        
        hass.bus.async_fire(f"{DOMAIN}_lock_status_response", status)
    
    async def handle_sync_user_to_new_locks(call: ServiceCall) -> None:
        """Sync a user to newly added locks."""
        data = get_data()
        lock_manager = data["lock_manager"]
        
        user_id = call.data.get("user_id")
        
        _LOGGER.info(f"Syncing user {user_id} to new locks...")
        result = await lock_manager.sync_user_to_new_locks(user_id)
        
        if result["success"]:
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": result["message"],
                    "title": "Sync to New Locks",
                },
            )
        else:
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": f"Failed: {result['message']}",
                    "title": "Sync Failed",
                },
            )
    
    async def handle_get_user_lock_status(call: ServiceCall) -> None:
        """Get lock enablement status for a user."""
        data = get_data()
        lock_manager = data["lock_manager"]
        
        user_id = call.data.get("user_id")
        
        status = await lock_manager.get_user_lock_status(user_id)
        
        hass.bus.async_fire(f"{DOMAIN}_user_lock_status_response", {
            "user_id": user_id,
            "lock_status": status
        })
    
    async def handle_set_user_lock_enabled(call: ServiceCall) -> None:
        """Enable/disable a user on a specific lock."""
        data = get_data()
        lock_manager = data["lock_manager"]
        
        user_id = call.data.get("user_id")
        lock_entity_id = call.data.get("lock_entity_id")
        enabled = call.data.get("enabled")
        
        success = await lock_manager.set_user_lock_enabled(user_id, lock_entity_id, enabled)
        
        if success:
            _LOGGER.info(f"Set user {user_id} enabled={enabled} on {lock_entity_id}")
        else:
            _LOGGER.error(f"Failed to set user lock enabled status")
    
    async def handle_get_user_pin(call: ServiceCall) -> None:
        """Get the actual PIN for a user from Z-Wave JS."""
        data = get_data()
        lock_manager = data["lock_manager"]
        
        user_id = call.data.get("user_id")
        
        pin = await lock_manager.get_user_pin_from_lock(user_id)
        
        hass.bus.async_fire(f"{DOMAIN}_user_pin_response", {
            "user_id": user_id,
            "pin": pin
        })
    
    #async def handle_get_lock_status(call: ServiceCall) -> None:
    #    """Get detailed lock status."""
    #    data = get_data()
    #    lock_manager = data["lock_manager"]
    #    
    #    status = await lock_manager.get_lock_status()
    #    
    #    _LOGGER.info(f"Lock status: {status}")
    #    
    #    hass.bus.async_fire(f"{DOMAIN}_lock_status_response", status)

    async def handle_get_user_lock_access(call: ServiceCall) -> None:
        """Get user's lock access from database (instant)."""
        data = get_data()
        database = data["database"]
        
        user_id = call.data.get("user_id")
        
        lock_access = await hass.async_add_executor_job(
            database.get_user_lock_access,
            user_id
        )
        
        hass.bus.async_fire(f"{DOMAIN}_user_lock_access_response", {
            "user_id": user_id,
            "lock_access": lock_access
        })
    
    async def handle_set_user_lock_enabled(call: ServiceCall) -> None:
        """Enable/disable a user on a specific lock (updates DB immediately, syncs async)."""
        data = get_data()
        lock_manager = data["lock_manager"]
        
        user_id = call.data.get("user_id")
        lock_entity_id = call.data.get("lock_entity_id")
        enabled = call.data.get("enabled")
        
        success = await lock_manager.set_user_lock_enabled(user_id, lock_entity_id, enabled)
        
        if success:
            _LOGGER.info(f"Updated lock access: user {user_id}, lock {lock_entity_id}, enabled {enabled}")
            # Fire event to notify UI
            hass.bus.async_fire(f"{DOMAIN}_lock_access_updated", {
                "user_id": user_id,
                "lock_entity_id": lock_entity_id,
                "enabled": enabled
            })
        else:
            _LOGGER.error(f"Failed to update lock access")
    
    async def handle_verify_user_lock_access(call: ServiceCall) -> None:
        """Verify user's lock access against Z-Wave JS (queries actual state)."""
        data = get_data()
        lock_manager = data["lock_manager"]
        
        user_id = call.data.get("user_id")
        
        _LOGGER.info(f"Verifying lock access for user {user_id}")
        result = await lock_manager.verify_user_lock_access(user_id)
        
        # Fire event with results
        hass.bus.async_fire(f"{DOMAIN}_verify_lock_access_response", {
            "user_id": user_id,
            "result": result
        })
        
        # Show notification if differences found
        if result.get('differences'):
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": f"Found {len(result['differences'])} difference(s) between database and locks. Database updated to match actual lock state.",
                    "title": "Lock Access Verified",
                },
            )
    
    async def handle_get_user_pin(call: ServiceCall) -> None:
        """Get the actual PIN for a user from Z-Wave JS."""
        data = get_data()
        lock_manager = data["lock_manager"]
        
        user_id = call.data.get("user_id")
        
        pin = None
        try:
            # Use asyncio.wait_for to ensure this doesn't hang
            pin = await asyncio.wait_for(
                lock_manager.get_user_pin_from_lock(user_id),
                timeout=5.0  # 5 second timeout
            )
        except asyncio.TimeoutError:
            _LOGGER.warning(f"Timeout getting PIN for user {user_id}")
        except Exception as e:
            _LOGGER.warning(f"Error getting PIN for user {user_id}: {e}")
        
        # ALWAYS fire event, even if pin is None
        hass.bus.async_fire(f"{DOMAIN}_user_pin_response", {
            "user_id": user_id,
            "pin": pin
        })
    
    async def handle_set_lock_sync_interval(call: ServiceCall) -> None:
        """Set the periodic lock sync interval."""
        data = get_data()
        database = data["database"]
        
        interval = call.data.get("interval")
        
        success = await hass.async_add_executor_job(
            database.set_lock_sync_config,
            interval
        )
        
        if success:
            # Restart periodic sync task with new interval
            if "lock_sync_task" in hass.data[DOMAIN]:
                hass.data[DOMAIN]["lock_sync_task"].cancel()
            
            hass.data[DOMAIN]["lock_sync_task"] = hass.async_create_task(
                _periodic_lock_sync_task(interval)
            )
            
            _LOGGER.info(f"Lock sync interval updated to {interval} seconds")
            
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "message": f"Lock sync interval set to {interval} seconds ({interval//60} minutes)",
                    "title": "Settings Updated",
                },
            )
    
    async def _periodic_lock_sync_task(interval: int):
        """Background task for periodic lock syncing."""
        data = get_data()
        lock_manager = data["lock_manager"]
        
        while True:
            try:
                await asyncio.sleep(interval)
                _LOGGER.debug(f"Running periodic lock sync (interval: {interval}s)")
                await lock_manager.periodic_lock_sync()
            except asyncio.CancelledError:
                _LOGGER.info("Periodic lock sync task cancelled")
                break
            except Exception as e:
                _LOGGER.error(f"Error in periodic lock sync: {e}")
                # Continue running even if one iteration fails  

    async def handle_get_events(call: ServiceCall) -> None:
        """Get filtered events."""
        data = get_data()
        database = data["database"]
        
        event_types = call.data.get("event_types")
        if event_types and isinstance(event_types, str):
            event_types = [t.strip() for t in event_types.split(',')]
        
        entity_id = call.data.get("entity_id")
        user_id = call.data.get("user_id")
        limit = call.data.get("limit", 100)
        days = call.data.get("days", 7)
        
        # Calculate date range
        start_date = datetime.now() - timedelta(days=days) if days else None
        
        events = await hass.async_add_executor_job(
            database.get_events_filtered,
            event_types,
            entity_id,
            user_id,
            start_date,
            None,
            limit
        )
        
        # Fire event with results
        hass.bus.async_fire(f"{DOMAIN}_events_response", {
            "events": events,
            "count": len(events),
            "filters": {
                "event_types": event_types,
                "entity_id": entity_id,
                "user_id": user_id,
                "days": days
            }
        })

    async def handle_get_event_types(call: ServiceCall) -> None:
        """Get all event types."""
        data = get_data()
        database = data["database"]
        
        event_types = await hass.async_add_executor_job(
            database.get_event_types
        )
        
        hass.bus.async_fire(f"{DOMAIN}_event_types_response", {
            "event_types": event_types
        })

    async def handle_get_event_stats(call: ServiceCall) -> None:
        """Get event statistics."""
        data = get_data()
        database = data["database"]
        
        days = call.data.get("days", 7)
        
        stats = await hass.async_add_executor_job(
            database.get_event_stats,
            days
        )
        
        hass.bus.async_fire(f"{DOMAIN}_event_stats_response", stats)
    
    # Register all services
    hass.services.async_register(
        DOMAIN, "arm_away", handle_arm_away,
        schema=vol.Schema({
            vol.Required("pin"): cv.string,
            vol.Optional("code"): cv.string,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "arm_home", handle_arm_home,
        schema=vol.Schema({
            vol.Required("pin"): cv.string,
            vol.Optional("code"): cv.string,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "disarm", handle_disarm,
        schema=vol.Schema({
            vol.Required("pin"): cv.string,
            vol.Optional("code"): cv.string,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "add_user", handle_add_user,
        schema=vol.Schema({
            vol.Required("name"): cv.string,
            vol.Required("pin"): cv.string,
            vol.Optional("admin_pin"): cv.string,  # Optional - uses service PIN if not provided
            vol.Optional("is_admin", default=False): cv.boolean,
            vol.Optional("is_duress", default=False): cv.boolean,
            vol.Optional("phone"): cv.string,
            vol.Optional("email"): cv.string,
            vol.Optional("has_separate_lock_pin", default=False): cv.boolean,
            vol.Optional("lock_pin"): cv.string,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "remove_user", handle_remove_user,
        schema=vol.Schema({
            vol.Required("user_id"): cv.positive_int,
            vol.Optional("admin_pin"): cv.string,  # Optional - uses service PIN if not provided
        })
    )
    
    hass.services.async_register(
        DOMAIN, "get_users", handle_get_users,
        schema=vol.Schema({})
    )
    
    hass.services.async_register(
        DOMAIN, "update_user", handle_update_user,
        schema=vol.Schema({
            vol.Required("user_id"): cv.positive_int,
            vol.Optional("name"): cv.string,
            vol.Optional("pin"): cv.string,
            vol.Optional("phone"): cv.string,
            vol.Optional("email"): cv.string,
            vol.Optional("is_admin"): cv.boolean,
            vol.Optional("has_separate_lock_pin"): cv.boolean,
            vol.Optional("lock_pin"): cv.string,
            vol.Optional("admin_pin"): cv.string,  # Optional - uses service PIN if not provided
        })
    )
    
    hass.services.async_register(
        DOMAIN, "bypass_zone", handle_bypass_zone,
        schema=vol.Schema({
            vol.Required("zone_entity_id"): cv.entity_id,
            vol.Required("pin"): cv.string,
            vol.Optional("bypass", default=True): cv.boolean,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "update_config", handle_update_config,
        schema=vol.Schema({
            vol.Optional("admin_pin"): cv.string,  # Optional - uses service PIN if not provided
            vol.Optional("entry_delay"): cv.positive_int,
            vol.Optional("exit_delay"): cv.positive_int,
            vol.Optional("alarm_duration"): cv.positive_int,
            vol.Optional("trigger_doors"): cv.string,
            vol.Optional("notification_mobile"): cv.boolean,
            vol.Optional("notification_sms"): cv.boolean,
            vol.Optional("sms_numbers"): cv.string,
            vol.Optional("auto_lock_on_arm_home"): cv.boolean,
            vol.Optional("auto_lock_on_arm_away"): cv.boolean,
            vol.Optional("auto_close_on_arm_home"): cv.boolean,
            vol.Optional("auto_close_on_arm_away"): cv.boolean,
            vol.Optional("lock_delay_home"): cv.positive_int,
            vol.Optional("lock_delay_away"): cv.positive_int,
            vol.Optional("close_delay_home"): cv.positive_int,
            vol.Optional("close_delay_away"): cv.positive_int,
            vol.Optional("lock_entities"): cv.string,
            vol.Optional("garage_entities"): cv.string,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "bootstrap_admin", handle_bootstrap_admin,
        schema=vol.Schema({
            vol.Optional("name", default="Admin"): cv.string,
            vol.Optional("pin", default="123456"): cv.string,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "authenticate_admin", handle_authenticate_admin,
        schema=vol.Schema({
            vol.Required("pin"): cv.string,
        })
    )

    hass.services.async_register(
        DOMAIN, "toggle_user_enabled", handle_toggle_user_enabled,
        schema=vol.Schema({
            vol.Required("user_id"): cv.positive_int,
            vol.Required("enabled"): cv.boolean,
            vol.Optional("admin_pin"): cv.string,  # Optional - uses service PIN if not provided
        })
    )

    #hass.services.async_register(
    #    DOMAIN, "set_user_lock_access", handle_set_user_lock_access,
    #    schema=vol.Schema({
    #        vol.Required("user_id"): cv.positive_int,
    #        vol.Required("lock_entity_id"): cv.entity_id,
    #        vol.Required("can_access"): cv.boolean,
    #        vol.Optional("admin_pin"): cv.string,  # Optional - uses service PIN if not provided
    #    })
    #)
    
    hass.services.async_register(
        DOMAIN, "cleanup_disabled_users", handle_cleanup_disabled_users,
        schema=vol.Schema({
            vol.Optional("admin_pin"): cv.string,  # Optional - uses service PIN if not provided
        })
    )
    
    hass.services.async_register(
        DOMAIN, "get_config", handle_get_config,
        schema=vol.Schema({})
    )

    hass.services.async_register(
        DOMAIN, "sync_locks", handle_sync_locks,
        schema=vol.Schema({
            vol.Optional("admin_pin"): cv.string,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "get_lock_status", handle_get_lock_status,
        schema=vol.Schema({})
    )
    
    hass.services.async_register(
        DOMAIN, "sync_user_to_new_locks", handle_sync_user_to_new_locks,
        schema=vol.Schema({
            vol.Required("user_id"): cv.positive_int,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "get_user_lock_status", handle_get_user_lock_status,
        schema=vol.Schema({
            vol.Required("user_id"): cv.positive_int,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "set_user_lock_enabled", handle_set_user_lock_enabled,
        schema=vol.Schema({
            vol.Required("user_id"): cv.positive_int,
            vol.Required("lock_entity_id"): cv.entity_id,
            vol.Required("enabled"): cv.boolean,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "get_user_pin", handle_get_user_pin,
        schema=vol.Schema({
            vol.Required("user_id"): cv.positive_int,
        })
    )

    hass.services.async_register(
        DOMAIN, "get_user_lock_access", handle_get_user_lock_access,
        schema=vol.Schema({
            vol.Required("user_id"): cv.positive_int,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "set_user_lock_enabled", handle_set_user_lock_enabled,
        schema=vol.Schema({
            vol.Required("user_id"): cv.positive_int,
            vol.Required("lock_entity_id"): cv.entity_id,
            vol.Required("enabled"): cv.boolean,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "verify_user_lock_access", handle_verify_user_lock_access,
        schema=vol.Schema({
            vol.Required("user_id"): cv.positive_int,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "get_user_pin", handle_get_user_pin,
        schema=vol.Schema({
            vol.Required("user_id"): cv.positive_int,
        })
    )
    
    hass.services.async_register(
        DOMAIN, "set_lock_sync_interval", handle_set_lock_sync_interval,
        schema=vol.Schema({
            vol.Required("interval"): cv.positive_int,
        })
    )

    hass.services.async_register(
        DOMAIN, "get_events", handle_get_events,
        schema=vol.Schema({
            vol.Optional("event_types"): cv.string,  # Comma-separated
            vol.Optional("entity_id"): cv.entity_id,
            vol.Optional("user_id"): cv.positive_int,
            vol.Optional("days", default=7): cv.positive_int,
            vol.Optional("limit", default=100): cv.positive_int,
        })
    )

    hass.services.async_register(
        DOMAIN, "get_event_types", handle_get_event_types,
        schema=vol.Schema({})
    )

    hass.services.async_register(
        DOMAIN, "get_event_stats", handle_get_event_stats,
        schema=vol.Schema({
            vol.Optional("days", default=7): cv.positive_int,
        })
    )
    
    _LOGGER.info("All services registered successfully")