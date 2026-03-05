"""Sensor platform for HomeSecure."""
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    database = hass.data[DOMAIN][entry.entry_id]["database"]
    
    sensors = [
        AlarmStatusSensor(coordinator, database),
        FailedAttemptsSensor(coordinator, database),
        LastChangedBySensor(coordinator, database),
        ActiveZonesSensor(coordinator, database),
    ]
    
    async_add_entities(sensors, True)

class AlarmStatusSensor(SensorEntity):
    """Sensor for alarm status information."""
    
    _attr_has_entity_name = True
    _attr_name = "Alarm Status"
    _attr_icon = "mdi:information"
    
    def __init__(self, coordinator, database):
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._database = database
        self._attr_unique_id = f"{DOMAIN}_status"
    
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        self._coordinator.add_listener(self._handle_coordinator_update)
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
    
    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        state = self._coordinator.state
        return state.replace('_', ' ').title()
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "state_raw": self._coordinator.state,
            "changed_by": self._coordinator.changed_by,
            "triggered_by": self._coordinator.triggered_by,
        }

class FailedAttemptsSensor(SensorEntity):
    """Sensor for failed authentication attempts."""
    
    _attr_has_entity_name = True
    _attr_name = "Failed Login Attempts"
    _attr_icon = "mdi:lock-alert"
    _attr_native_unit_of_measurement = "attempts"
    
    def __init__(self, coordinator, database):
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._database = database
        self._attr_unique_id = f"{DOMAIN}_failed_attempts"
    
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        self._coordinator.add_listener(self._handle_coordinator_update)
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
    
    @property
    def native_value(self) -> int:
        """Return the number of failed attempts."""
        try:
            return self._database.get_failed_attempts_count()
        except Exception as e:
            _LOGGER.error(f"Error getting failed attempts: {e}")
            return 0

class LastChangedBySensor(SensorEntity):
    """Sensor for who last changed the alarm state."""
    
    _attr_has_entity_name = True
    _attr_name = "Last Changed By"
    _attr_icon = "mdi:account"
    
    def __init__(self, coordinator, database):
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._database = database
        self._attr_unique_id = f"{DOMAIN}_last_changed_by"
    
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        self._coordinator.add_listener(self._handle_coordinator_update)
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
    
    @property
    def native_value(self) -> str:
        """Return who last changed the alarm."""
        return self._coordinator.changed_by or "Unknown"

class ActiveZonesSensor(SensorEntity):
    """Sensor for active/monitored zones count."""
    
    _attr_has_entity_name = True
    _attr_name = "Active Zones"
    _attr_icon = "mdi:shield-check"
    _attr_native_unit_of_measurement = "zones"
    
    def __init__(self, coordinator, database):
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._database = database
        self._attr_unique_id = f"{DOMAIN}_active_zones"
    
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        self._coordinator.add_listener(self._handle_coordinator_update)
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
    
    @property
    def native_value(self) -> int:
        """Return the number of active zones."""
        try:
            zones = self._database.get_zones(self._coordinator.state)
            active = [z for z in zones if not z['bypassed']]
            return len(active)
        except Exception as e:
            _LOGGER.error(f"Error getting active zones: {e}")
            return 0
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        try:
            zones = self._database.get_zones(self._coordinator.state)
            return {
                "total_zones": len(zones),
                "bypassed_zones": [z['zone_name'] for z in zones if z['bypassed']],
            }
        except Exception as e:
            _LOGGER.error(f"Error getting zones: {e}")
            return {}