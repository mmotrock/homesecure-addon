"""Alarm control panel platform for HomeSecure."""
import logging
from typing import Any, Optional

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    STATE_ALARM_DISARMED,
    STATE_ALARM_ARMED_HOME,
    STATE_ALARM_ARMED_AWAY,
    STATE_ALARM_PENDING,
    STATE_ALARM_TRIGGERED,
    STATE_ALARM_ARMING,
    ATTR_CHANGED_BY,
    ATTR_CODE_FORMAT,
    ATTR_ZONES_BYPASSED,
    ATTR_ACTIVE_ZONES,
    ATTR_FAILED_ATTEMPTS,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the alarm control panel from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    database = hass.data[DOMAIN][entry.entry_id]["database"]
    
    async_add_entities([SecureAlarmPanel(coordinator, database, entry)], True)

class SecureAlarmPanel(AlarmControlPanelEntity):
    """Representation of a HomeSecure Panel."""
    
    _attr_has_entity_name = True
    _attr_name = "HomeSecure"
    _attr_should_poll = False
    _attr_code_arm_required = False  # We handle this in coordinator
    _attr_code_format = "number"
    
    def __init__(self, coordinator, database, entry: ConfigEntry):
        """Initialize the alarm panel."""
        self._coordinator = coordinator
        self._database = database
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_main_panel"
        
        # Set supported features
        self._attr_supported_features = (
            AlarmControlPanelEntityFeature.ARM_HOME
            | AlarmControlPanelEntityFeature.ARM_AWAY
            | AlarmControlPanelEntityFeature.TRIGGER
        )
        
        # Register listener
        self._coordinator.add_listener(self._handle_coordinator_update)
    
    @property
    def config_entry(self) -> ConfigEntry:
        """Return the config entry."""
        return self._entry
    
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()
        
        # Subscribe to zone state changes
        await self._subscribe_to_zones()
    
    async def _subscribe_to_zones(self) -> None:
        """Subscribe to all zone entity state changes."""
        zones = await self.hass.async_add_executor_job(
            self._database.get_zones
        )
        
        for zone in zones:
            entity_id = zone['entity_id']
            
            @callback
            def zone_state_changed(event, zone_entity_id=entity_id, zone_name=zone['zone_name']):
                """Handle zone state change."""
                new_state = event.data.get('new_state')
                old_state = event.data.get('old_state')
                
                if new_state is None:
                    return
                
                # Check if zone went from off to on (closed to open)
                if (old_state and old_state.state == 'off' and 
                    new_state.state == 'on'):
                    self.hass.async_create_task(
                        self._coordinator.zone_triggered(zone_entity_id, zone_name)
                    )
            
            # Track state changes
            self.hass.bus.async_listen(
                'state_changed',
                zone_state_changed,
                lambda event: event.data.get('entity_id') == entity_id
            )
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
    
    @property
    def state(self) -> str:
        """Return the state of the alarm."""
        coordinator_state = self._coordinator.state
        
        # Map our custom ARMING state to HA's standard states
        if coordinator_state == STATE_ALARM_ARMING:
            return STATE_ALARM_ARMING
        
        return coordinator_state
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attrs = {
            ATTR_CODE_FORMAT: "number",
            ATTR_CHANGED_BY: self._coordinator.changed_by,
        }
        
        # Add triggered by if alarm is triggered or pending
        if self._coordinator.state in [STATE_ALARM_TRIGGERED, STATE_ALARM_PENDING]:
            attrs["triggered_by"] = self._coordinator.triggered_by
        
        # Add failed attempts count
        try:
            failed_attempts = self._database.get_failed_attempts_count()
            attrs[ATTR_FAILED_ATTEMPTS] = failed_attempts
        except Exception as e:
            _LOGGER.error(f"Error getting failed attempts: {e}")
        
        # Add bypassed zones
        try:
            zones = self._database.get_zones()
            bypassed = [z['zone_name'] for z in zones if z['bypassed']]
            if bypassed:
                attrs[ATTR_ZONES_BYPASSED] = bypassed
        except Exception as e:
            _LOGGER.error(f"Error getting bypassed zones: {e}")
        
        return attrs
    
    async def async_alarm_disarm(self, code: Optional[str] = None) -> None:
        """Send disarm command."""
        if not code:
            _LOGGER.warning("Disarm called without code")
            return
        
        result = await self._coordinator.disarm(code)
        
        if not result["success"]:
            _LOGGER.warning(f"Disarm failed: {result['message']}")
    
    async def async_alarm_arm_home(self, code: Optional[str] = None) -> None:
        """Send arm home command."""
        # Use service PIN from config entry for internal authentication
        from . import get_service_pin
        service_pin = get_service_pin(self.hass, self._entry.entry_id)
        
        result = await self._coordinator.arm_home(service_pin)
        
        if not result["success"]:
            _LOGGER.warning(f"Arm home failed: {result['message']}")

    async def async_alarm_arm_away(self, code: Optional[str] = None) -> None:
        """Send arm away command."""
        # Use service PIN from config entry for internal authentication
        from . import get_service_pin
        service_pin = get_service_pin(self.hass, self._entry.entry_id)
        
        result = await self._coordinator.arm_away(service_pin)
        
        if not result["success"]:
            _LOGGER.warning(f"Arm away failed: {result['message']}")                                        
    
    async def async_alarm_trigger(self, code: Optional[str] = None) -> None:
        """Send alarm trigger command."""
        await self._coordinator._trigger_alarm("manual", "Manual Trigger")
    
    @property
    def icon(self) -> str:
        """Return the icon."""
        if self.state == STATE_ALARM_DISARMED:
            return "mdi:shield-off"
        elif self.state == STATE_ALARM_ARMED_HOME:
            return "mdi:shield-home"
        elif self.state == STATE_ALARM_ARMED_AWAY:
            return "mdi:shield-lock"
        elif self.state == STATE_ALARM_PENDING:
            return "mdi:shield-alert"
        elif self.state == STATE_ALARM_TRIGGERED:
            return "mdi:bell-ring"
        elif self.state == STATE_ALARM_ARMING:
            return "mdi:shield-sync"
        return "mdi:shield"