"""Alarm coordinator for managing alarm state and logic."""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time, async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    STATE_ALARM_DISARMED,
    STATE_ALARM_ARMED_HOME,
    STATE_ALARM_ARMED_AWAY,
    STATE_ALARM_PENDING,
    STATE_ALARM_TRIGGERED,
    STATE_ALARM_ARMING,
    EVENT_ALARM_ARMED,
    EVENT_ALARM_DISARMED,
    EVENT_ALARM_TRIGGERED,
    EVENT_ALARM_DURESS,
    ZONE_TYPE_ENTRY,
)
from .database import AlarmDatabase

_LOGGER = logging.getLogger(__name__)


class AlarmCoordinator:
    """Coordinator for managing alarm system state and logic."""
    
    def __init__(self, hass: HomeAssistant, database: AlarmDatabase, entry_id: str):
        """Initialize the coordinator."""
        self.hass = hass
        self.database = database
        self.entry_id = entry_id
        self._state = STATE_ALARM_DISARMED
        self._previous_state = None
        self._triggered_by = None
        self._changed_by = None
        self._entry_timer = None
        self._exit_timer = None
        self._alarm_timer = None
        self._listeners: List[Callable] = []
        self._bypassed_zones: set = set()
    
    def _get_service_pin(self) -> str:
        """Get the service PIN for this coordinator's instance."""
        from . import get_service_pin
        return get_service_pin(self.hass, self.entry_id)
        
    @property
    def state(self) -> str:
        """Return current alarm state."""
        return self._state
    
    @property
    def changed_by(self) -> Optional[str]:
        """Return who last changed the alarm state."""
        return self._changed_by
    
    @property
    def triggered_by(self) -> Optional[str]:
        """Return what triggered the alarm."""
        return self._triggered_by
    
    def add_listener(self, listener: Callable) -> None:
        """Add a state change listener."""
        self._listeners.append(listener)
    
    def remove_listener(self, listener: Callable) -> None:
        """Remove a state change listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)
    
    async def _notify_listeners(self) -> None:
        """Notify all listeners of state change."""
        for listener in self._listeners:
            await listener()
    
    async def _set_state(self, new_state: str, changed_by: Optional[str] = None) -> None:
        """Set alarm state and notify listeners."""
        old_state = self._state
        self._previous_state = old_state
        self._state = new_state
        
        if changed_by:
            self._changed_by = changed_by
        
        # Log state change
        await self.hass.async_add_executor_job(
            self.database.log_event,
            "state_change",
            None,
            changed_by,
            old_state,
            new_state
        )
        
        # Fire event
        self.hass.bus.async_fire(f"{DOMAIN}_state_changed", {
            "state": new_state,
            "previous_state": old_state,
            "changed_by": changed_by,
        })
        
        await self._notify_listeners()
        
        _LOGGER.info(f"Alarm state changed: {old_state} -> {new_state}")
    
    async def _authenticate(self, pin: str, user_code: Optional[str] = None) -> Optional[Dict]:
        """
        Authenticate user with PIN for keypad use.
        This function is ONLY for user PINs, NOT the service PIN.
        """
        user = await self.hass.async_add_executor_job(
            self.database.authenticate_user,
            pin,
            user_code
        )
        
        if user:
            # Clear failed attempts on successful auth
            await self.hass.async_add_executor_job(
                self.database.clear_failed_attempts
            )
            
            # Check for duress code
            if user['is_duress']:
                _LOGGER.warning(f"DURESS CODE USED by {user['name']}")
                self.hass.bus.async_fire(EVENT_ALARM_DURESS, {
                    "user_name": user['name'],
                    "user_id": user['id'],
                    "timestamp": datetime.now().isoformat(),
                })
                
                # Send silent notification
                await self._send_duress_notification(user['name'])
        
        return user
    
    async def _authenticate_service(self, pin: str) -> Optional[Dict]:
        """
        Authenticate for service calls - can use service PIN or user admin PIN.
        Service PIN will NOT work at keypads.
        """
        service_pin = self._get_service_pin()
        
        user = await self.hass.async_add_executor_job(
            self.database.authenticate_user_service,
            pin,
            service_pin
        )
        
        if user and user.get('id') == -1:
            # This is service authentication
            _LOGGER.debug("Service PIN used for authentication")
        elif user and user.get('is_admin'):
            # This is a regular admin user
            _LOGGER.debug(f"Admin user {user['name']} authenticated")
            # Clear failed attempts on successful auth
            await self.hass.async_add_executor_job(
                self.database.clear_failed_attempts
            )
        
        return user
    
    async def arm_away(self, pin: str, user_code: Optional[str] = None) -> Dict[str, Any]:
        """Arm the system in away mode."""
        try:
            # First check if it's the service PIN (for internal operations)
            service_pin = self._get_service_pin()
            if pin == service_pin:
                # Service authentication - create pseudo-user
                user = {
                    'id': -1,
                    'name': 'Service',
                    'is_admin': True,
                    'is_duress': False,
                }
            else:
                # User authentication (for keypad/service calls with user PIN)
                user = await self._authenticate(pin, user_code)
            
            if not user:
                return {"success": False, "message": "Invalid PIN"}
            
            if self._state in [STATE_ALARM_ARMED_AWAY, STATE_ALARM_ARMING]:
                return {"success": False, "message": "System already arming or armed"}
            
            # Start exit delay
            config = await self.hass.async_add_executor_job(self.database.get_config)
            exit_delay = config.get('exit_delay', 60)
            
            # Use 'Service' as the name for internal service calls
            changed_by = user['name'] if user['id'] != -1 else 'Service'
            await self._set_state(STATE_ALARM_ARMING, changed_by)
            
            # Cancel any existing timers
            self._cancel_timers()
            
            # Set exit timer
            self._exit_timer = async_call_later(
                self.hass,
                exit_delay,
                self._complete_arming_away
            )
            
            _LOGGER.info(f"Arming away initiated by {changed_by}, {exit_delay}s delay")
            
            return {
                "success": True,
                "message": f"Arming away in {exit_delay} seconds",
                "delay": exit_delay
            }
        except Exception as e:
            _LOGGER.error(f"Error in arm_away: {e}", exc_info=True)
            return {"success": False, "message": f"Error: {str(e)}"}

    async def arm_home(self, pin: str, user_code: Optional[str] = None) -> Dict[str, Any]:
        """Arm the system in home mode."""
        try:
            # First check if it's the service PIN (for internal operations)
            service_pin = self._get_service_pin()
            if pin == service_pin:
                # Service authentication - create pseudo-user
                user = {
                    'id': -1,
                    'name': 'Service',
                    'is_admin': True,
                    'is_duress': False,
                }
            else:
                # User authentication (for keypad/service calls with user PIN)
                user = await self._authenticate(pin, user_code)
            
            if not user:
                return {"success": False, "message": "Invalid PIN"}
            
            if self._state == STATE_ALARM_ARMED_HOME:
                return {"success": False, "message": "System already armed home"}
            
            # Cancel any existing timers
            self._cancel_timers()
            
            # Use 'Service' as the name for internal service calls
            changed_by = user['name'] if user['id'] != -1 else 'Service'
            
            # Arm home has no exit delay (you're already home)
            await self._set_state(STATE_ALARM_ARMED_HOME, changed_by)
            
            # Auto-lock doors if configured
            await self._auto_lock_doors("armed_home")
            
            # Fire armed event
            self.hass.bus.async_fire(EVENT_ALARM_ARMED, {
                "mode": "armed_home",
                "changed_by": changed_by,
            })
            
            _LOGGER.info(f"Armed home by {changed_by}")
            
            return {"success": True, "message": "Armed home"}
        except Exception as e:
            _LOGGER.error(f"Error in arm_home: {e}", exc_info=True)
            return {"success": False, "message": f"Error: {str(e)}"}
    
    async def disarm(self, pin: str, user_code: Optional[str] = None) -> Dict[str, Any]:
        """Disarm the system."""
        try:
            user = await self._authenticate(pin, user_code)
            
            if not user:
                return {"success": False, "message": "Invalid PIN"}
            
            # Cancel all timers
            self._cancel_timers()
            
            # If duress code, appear to disarm but alert
            if user['is_duress']:
                await self._set_state(STATE_ALARM_DISARMED, user['name'])
                # Duress notification already sent in _authenticate
            else:
                await self._set_state(STATE_ALARM_DISARMED, user['name'])
            
            self._triggered_by = None
            self._bypassed_zones.clear()
            
            # Fire disarmed event
            self.hass.bus.async_fire(EVENT_ALARM_DISARMED, {
                "changed_by": user['name'],
            })
            
            _LOGGER.info(f"Disarmed by {user['name']}")
            
            return {"success": True, "message": "Disarmed"}
        except Exception as e:
            _LOGGER.error(f"Error in disarm: {e}", exc_info=True)
            return {"success": False, "message": f"Error: {str(e)}"}
    
    async def _complete_arming_away(self, _now: datetime = None) -> None:
        """Complete the arming process after exit delay."""
        try:
            await self._set_state(STATE_ALARM_ARMED_AWAY, self._changed_by)
            
            # Auto-lock doors if configured
            await self._auto_lock_doors("armed_away")
            
            # Fire armed event
            self.hass.bus.async_fire(EVENT_ALARM_ARMED, {
                "mode": "armed_away",
                "changed_by": self._changed_by,
            })
            
            _LOGGER.info("Armed away complete")
        except Exception as e:
            _LOGGER.error(f"Error completing arming away: {e}", exc_info=True)
    
    async def zone_triggered(self, zone_entity_id: str, zone_name: str) -> None:
        """Handle zone trigger."""
        # Ignore if disarmed or already triggered
        if self._state in [STATE_ALARM_DISARMED, STATE_ALARM_TRIGGERED]:
            return
        
        # Check if zone is bypassed
        if zone_entity_id in self._bypassed_zones:
            _LOGGER.info(f"Zone {zone_name} triggered but bypassed")
            return
        
        # Get zone info
        zones = await self.hass.async_add_executor_job(
            self.database.get_zones,
            self._state
        )
        
        zone_info = next((z for z in zones if z['entity_id'] == zone_entity_id), None)
        
        if not zone_info:
            _LOGGER.warning(f"Unknown zone triggered: {zone_entity_id}")
            return
        
        # If it's an entry zone and we're armed, start entry delay
        if zone_info['zone_type'] == ZONE_TYPE_ENTRY and self._state in [STATE_ALARM_ARMED_AWAY, STATE_ALARM_ARMED_HOME]:
            if self._state != STATE_ALARM_PENDING:
                await self._start_entry_delay(zone_entity_id, zone_name)
        else:
            # Instant trigger for non-entry zones
            await self._trigger_alarm(zone_entity_id, zone_name)
    
    async def _start_entry_delay(self, zone_entity_id: str, zone_name: str) -> None:
        """Start entry delay timer."""
        config = await self.hass.async_add_executor_job(self.database.get_config)
        entry_delay = config.get('entry_delay', 30)
        
        await self._set_state(STATE_ALARM_PENDING, self._changed_by)
        self._triggered_by = zone_name
        
        # Cancel existing entry timer if any
        if self._entry_timer:
            self._entry_timer()
        
        # Set new entry timer
        self._entry_timer = async_call_later(
            self.hass,
            entry_delay,
            lambda _: asyncio.create_task(self._trigger_alarm(zone_entity_id, zone_name))
        )
        
        _LOGGER.warning(f"Entry delay started: {zone_name}, {entry_delay}s to disarm")
    
    async def _trigger_alarm(self, zone_entity_id: str, zone_name: str) -> None:
        """Trigger the alarm."""
        if self._state == STATE_ALARM_TRIGGERED:
            return
        
        self._triggered_by = zone_name
        await self._set_state(STATE_ALARM_TRIGGERED, self._changed_by)
        
        # Log trigger
        await self.hass.async_add_executor_job(
            self.database.log_event,
            "alarm_triggered",
            None,
            None,
            self._previous_state,
            STATE_ALARM_TRIGGERED,
            zone_entity_id
        )
        
        # Fire triggered event
        self.hass.bus.async_fire(EVENT_ALARM_TRIGGERED, {
            "zone": zone_name,
            "zone_entity_id": zone_entity_id,
        })
        
        # Send notifications
        await self._send_alarm_notification(zone_name)
        
        # Set alarm duration timer
        config = await self.hass.async_add_executor_job(self.database.get_config)
        alarm_duration = config.get('alarm_duration', 300)
        
        self._alarm_timer = async_call_later(
            self.hass,
            alarm_duration,
            self._alarm_timeout
        )
        
        _LOGGER.critical(f"ALARM TRIGGERED by {zone_name}")
    
    async def _alarm_timeout(self, _now: datetime = None) -> None:
        """Handle alarm timeout (stays triggered but stops siren)."""
        _LOGGER.info("Alarm timeout reached")
    
    def _cancel_timers(self) -> None:
        """Cancel all active timers."""
        if self._entry_timer:
            self._entry_timer()
            self._entry_timer = None
        
        if self._exit_timer:
            self._exit_timer()
            self._exit_timer = None
        
        if self._alarm_timer:
            self._alarm_timer()
            self._alarm_timer = None
    
    async def _auto_lock_doors(self, mode: str) -> None:
        """Automatically lock doors and close garages when arming."""
        try:
            config = await self.hass.async_add_executor_job(self.database.get_config)
            
            # Check if auto-lock is enabled for this mode
            if mode == "armed_home":
                auto_lock = config.get('auto_lock_on_arm_home', False)
                auto_close = config.get('auto_close_on_arm_home', False)
                lock_delay = config.get('lock_delay_home', 0)
                close_delay = config.get('close_delay_home', 0)
            else:  # armed_away
                auto_lock = config.get('auto_lock_on_arm_away', True)
                auto_close = config.get('auto_close_on_arm_away', True)
                lock_delay = config.get('lock_delay_away', 60)
                close_delay = config.get('close_delay_away', 60)
            
            # Get entities from config
            lock_entities_str = config.get('lock_entities', '')
            garage_entities_str = config.get('garage_entities', '')
            
            lock_entities = [e.strip() for e in lock_entities_str.split(',') if e.strip()] if lock_entities_str else []
            garage_entities = [e.strip() for e in garage_entities_str.split(',') if e.strip()] if garage_entities_str else []
            
            # If no entities configured, discover them
            if not lock_entities and not garage_entities:
                _LOGGER.debug("No lock/garage entities configured, auto-discovering...")
                # Auto-discover locks
                lock_entities = [
                    entity_id for entity_id in self.hass.states.async_entity_ids('lock')
                ]
                # Auto-discover garage doors
                garage_entities = [
                    entity_id for entity_id in self.hass.states.async_entity_ids('cover')
                    if 'garage' in entity_id.lower() or 
                    self.hass.states.get(entity_id).attributes.get('device_class') == 'garage'
                ]
            
            # Lock doors
            if auto_lock and lock_entities:
                _LOGGER.info(f"Auto-locking {len(lock_entities)} door(s) with {lock_delay}s delay")
                
                async def lock_doors(_now: datetime = None):
                    for entity_id in lock_entities:
                        state = self.hass.states.get(entity_id)
                        if state and state.state == 'unlocked':
                            _LOGGER.info(f"Locking {entity_id}")
                            await self.hass.services.async_call(
                                'lock',
                                'lock',
                                {'entity_id': entity_id},
                                blocking=False
                            )
                
                if lock_delay > 0:
                    async_call_later(self.hass, lock_delay, lock_doors)
                else:
                    await lock_doors()
            
            # Close garage doors
            if auto_close and garage_entities:
                _LOGGER.info(f"Auto-closing {len(garage_entities)} garage door(s) with {close_delay}s delay")
                
                async def close_garages(_now: datetime = None):
                    for entity_id in garage_entities:
                        state = self.hass.states.get(entity_id)
                        if state and state.state == 'open':
                            _LOGGER.info(f"Closing {entity_id}")
                            await self.hass.services.async_call(
                                'cover',
                                'close_cover',
                                {'entity_id': entity_id},
                                blocking=False
                            )
                
                if close_delay > 0:
                    async_call_later(self.hass, close_delay, close_garages)
                else:
                    await close_garages()
                    
        except Exception as e:
            _LOGGER.error(f"Error in auto-lock: {e}", exc_info=True)
    
    async def _send_alarm_notification(self, zone_name: str) -> None:
        """Send alarm trigger notifications."""
        config = await self.hass.async_add_executor_job(self.database.get_config)
        
        message = f"🚨 ALARM TRIGGERED: {zone_name}"
        
        # Mobile notification
        if config.get('notification_mobile', True):
            await self.hass.services.async_call(
                'notify',
                'mobile_app_all',
                {
                    'message': message,
                    'title': 'Security Alert',
                    'data': {
                        'priority': 'high',
                        'ttl': 0,
                        'channel': 'alarm',
                    }
                },
                blocking=False
            )
        
        # SMS notification
        if config.get('notification_sms', False):
            sms_numbers = config.get('sms_numbers', '')
            if sms_numbers:
                for number in sms_numbers.split(','):
                    await self._send_sms(number.strip(), message)
    
    async def _send_duress_notification(self, user_name: str) -> None:
        """Send silent duress code notification."""
        message = f"⚠️ DURESS CODE USED by {user_name}"
        
        await self.hass.services.async_call(
            'notify',
            'mobile_app_all',
            {
                'message': message,
                'title': 'Security Alert - Silent',
                'data': {
                    'priority': 'high',
                    'ttl': 0,
                    'channel': 'duress',
                }
            },
            blocking=False
        )
    
    async def _send_sms(self, phone_number: str, message: str) -> None:
        """Send SMS notification."""
        try:
            await self.hass.services.async_call(
                'notify',
                'sms',
                {
                    'target': phone_number,
                    'message': message,
                },
                blocking=False
            )
        except Exception as e:
            _LOGGER.error(f"Failed to send SMS: {e}")
    
    async def add_user(self, name: str, pin: str, admin_pin: str,
                  is_admin: bool = False, is_duress: bool = False,
                  phone: Optional[str] = None, email: Optional[str] = None,
                  has_separate_lock_pin: bool = False, lock_pin: Optional[str] = None) -> Dict[str, Any]:
        """Add a new user."""
        # Verify admin PIN using service authentication
        admin_user = await self._authenticate_service(admin_pin)
        
        if not admin_user or not admin_user.get('is_admin'):
            return {"success": False, "message": "Admin authentication required"}
        
        # Validate PIN length
        if len(pin) < 6 or len(pin) > 8:
            return {"success": False, "message": "PIN must be 6-8 characters"}
        
        # Validate lock PIN if provided
        if has_separate_lock_pin and lock_pin and (len(lock_pin) < 6 or len(lock_pin) > 8):
            return {"success": False, "message": "Lock PIN must be 6-8 characters"}
        
        # Add user
        user_id = await self.hass.async_add_executor_job(
            self.database.add_user,
            name,
            pin,
            is_admin,
            is_duress,
            phone,
            email,
            has_separate_lock_pin,
            lock_pin
        )
        
        if user_id:
            return {"success": True, "message": f"User {name} added", "user_id": user_id}
        else:
            return {"success": False, "message": "Failed to add user"}
    
    async def remove_user(self, user_id: int, admin_pin: str) -> Dict[str, Any]:
        """Remove a user."""
        # Verify admin PIN using service authentication
        admin_user = await self._authenticate_service(admin_pin)
        
        if not admin_user or not admin_user.get('is_admin'):
            return {"success": False, "message": "Admin authentication required"}
        
        # Check if trying to delete the last admin
        users = await self.hass.async_add_executor_job(
            self.database.get_users
        )
        
        # Count enabled admins excluding the user being deleted
        enabled_admins = [u for u in users if u['is_admin'] and u['enabled'] and u['id'] != user_id]
        user_to_delete = next((u for u in users if u['id'] == user_id), None)
        
        if user_to_delete and user_to_delete['is_admin'] and len(enabled_admins) == 0:
            return {"success": False, "message": "Cannot delete the last admin user. Create another admin first."}
        
        success = await self.hass.async_add_executor_job(
            self.database.remove_user,
            user_id
        )
        
        if success:
            return {"success": True, "message": "User deleted"}
        else:
            return {"success": False, "message": "Failed to delete user"}
    
    async def bypass_zone(self, zone_entity_id: str, pin: str,
                         bypass: bool = True) -> Dict[str, Any]:
        """Bypass or unbypass a zone."""
        user = await self._authenticate(pin)
        
        if not user:
            return {"success": False, "message": "Invalid PIN"}
        
        if bypass:
            self._bypassed_zones.add(zone_entity_id)
        else:
            self._bypassed_zones.discard(zone_entity_id)
        
        success = await self.hass.async_add_executor_job(
            self.database.set_zone_bypass,
            zone_entity_id,
            bypass
        )
        
        if success:
            return {"success": True, "message": f"Zone {'bypassed' if bypass else 'unbypassed'}"}
        else:
            return {"success": False, "message": "Failed to update zone"}
    
    async def update_config(self, admin_pin: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update alarm configuration."""
        # Verify admin PIN using service authentication
        admin_user = await self._authenticate_service(admin_pin)
        
        if not admin_user or not admin_user.get('is_admin'):
            return {"success": False, "message": "Admin authentication required"}
        
        success = await self.hass.async_add_executor_job(
            self.database.update_config,
            updates
        )
        
        if success:
            return {"success": True, "message": "Configuration updated"}
        else:
            return {"success": False, "message": "Failed to update configuration"}
        
    async def update_user(self, user_id: int, name: Optional[str], pin: Optional[str],
                     phone: Optional[str], email: Optional[str], is_admin: bool,
                     has_separate_lock_pin: bool, lock_pin: Optional[str],
                     admin_pin: str) -> Dict[str, Any]:
        """Update a user."""
        # Verify admin PIN using service authentication
        admin_user = await self._authenticate_service(admin_pin)
        
        if not admin_user or not admin_user.get('is_admin'):
            return {"success": False, "message": "Admin authentication required"}
        
        # Validate PIN if provided
        if pin and (len(pin) < 6 or len(pin) > 8):
            return {"success": False, "message": "PIN must be 6-8 characters"}
        
        # Validate lock PIN if provided
        if lock_pin and (len(lock_pin) < 6 or len(lock_pin) > 8):
            return {"success": False, "message": "Lock PIN must be 6-8 characters"}
        
        # Update user
        success = await self.hass.async_add_executor_job(
            self.database.update_user,
            user_id,
            name,
            pin,
            is_admin,
            phone,
            email,
            has_separate_lock_pin,
            lock_pin
        )
        
        if success:
            return {"success": True, "message": f"User updated"}
        else:
            return {"success": False, "message": "Failed to update user"}