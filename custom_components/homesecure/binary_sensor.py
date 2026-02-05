"""Binary sensor platform for HomeSecure."""
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STATE_ALARM_DISARMED, STATE_ALARM_TRIGGERED

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    database = hass.data[DOMAIN][entry.entry_id]["database"]
    
    sensors = [
        AlarmArmedBinarySensor(coordinator, database),
        AlarmTriggeredBinarySensor(coordinator, database),
        SystemLockedOutBinarySensor(coordinator, database),
    ]
    
    async_add_entities(sensors, True)

class AlarmArmedBinarySensor(BinarySensorEntity):
    """Binary sensor indicating if alarm is armed."""
    
    _attr_has_entity_name = True
    _attr_name = "Alarm Armed"
    _attr_device_class = BinarySensorDeviceClass.SAFETY
    
    def __init__(self, coordinator, database):
        """Initialize the binary sensor."""
        self._coordinator = coordinator
        self._database = database
        self._attr_unique_id = f"{DOMAIN}_armed"
    
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        self._coordinator.add_listener(self._handle_coordinator_update)
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
    
    @property
    def is_on(self) -> bool:
        """Return true if alarm is armed."""
        return self._coordinator.state != STATE_ALARM_DISARMED
    
    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:shield-check" if self.is_on else "mdi:shield-off"

class AlarmTriggeredBinarySensor(BinarySensorEntity):
    """Binary sensor indicating if alarm is triggered."""
    
    _attr_has_entity_name = True
    _attr_name = "Alarm Triggered"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    
    def __init__(self, coordinator, database):
        """Initialize the binary sensor."""
        self._coordinator = coordinator
        self._database = database
        self._attr_unique_id = f"{DOMAIN}_triggered"
    
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        self._coordinator.add_listener(self._handle_coordinator_update)
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
    
    @property
    def is_on(self) -> bool:
        """Return true if alarm is triggered."""
        return self._coordinator.state == STATE_ALARM_TRIGGERED
    
    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:bell-ring" if self.is_on else "mdi:bell-off"

class SystemLockedOutBinarySensor(BinarySensorEntity):
    """Binary sensor indicating if system is locked out."""
    
    _attr_has_entity_name = True
    _attr_name = "System Locked Out"
    _attr_device_class = BinarySensorDeviceClass.LOCK
    
    def __init__(self, coordinator, database):
        """Initialize the binary sensor."""
        self._coordinator = coordinator
        self._database = database
        self._attr_unique_id = f"{DOMAIN}_locked_out"
    
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        self._coordinator.add_listener(self._handle_coordinator_update)
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
    
    @property
    def is_on(self) -> bool:
        """Return true if system is locked out."""
        try:
            return self._database.is_locked_out()
        except Exception as e:
            _LOGGER.error(f"Error checking lockout status: {e}")
            return False
    
    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:lock-alert" if self.is_on else "mdi:lock-open"