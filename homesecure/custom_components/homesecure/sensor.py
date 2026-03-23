"""Sensor platform for HomeSecure (thin — reads from container API client)."""
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
    api_client = hass.data[DOMAIN][entry.entry_id]["api_client"]

    async_add_entities([
        AlarmStateSensor(api_client),
        LastChangedBySensor(api_client),
        FailedAttemptsSensor(api_client),
    ], True)


class _BaseContainerSensor(SensorEntity):
    """Base class — subscribes to the API client state updates."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, api_client):
        self._api = api_client

    async def async_added_to_hass(self) -> None:
        self._api.add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        self._api.remove_listener(self._handle_update)

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class AlarmStateSensor(_BaseContainerSensor):
    """Human-readable alarm state."""

    _attr_name = "Alarm Status"
    _attr_icon = "mdi:information"

    def __init__(self, api_client):
        super().__init__(api_client)
        self._attr_unique_id = f"{DOMAIN}_status"

    @property
    def native_value(self) -> str:
        return self._api.state.replace("_", " ").title()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "state_raw":    self._api.state,
            "changed_by":   self._api.changed_by,
            "triggered_by": self._api.triggered_by,
        }


class LastChangedBySensor(_BaseContainerSensor):
    """Who last changed the alarm state."""

    _attr_name = "Last Changed By"
    _attr_icon = "mdi:account"

    def __init__(self, api_client):
        super().__init__(api_client)
        self._attr_unique_id = f"{DOMAIN}_last_changed_by"

    @property
    def native_value(self) -> str:
        return self._api.changed_by or "Unknown"


class FailedAttemptsSensor(_BaseContainerSensor):
    """
    Recent failed PIN attempts.
    Polled from the container on every state update since the API client
    doesn't push this separately.  Cached to avoid hammering the API.
    """

    _attr_name = "Failed Login Attempts"
    _attr_icon = "mdi:lock-alert"
    _attr_native_unit_of_measurement = "attempts"
    _attr_should_poll = True   # poll this one independently

    def __init__(self, api_client):
        super().__init__(api_client)
        self._attr_unique_id = f"{DOMAIN}_failed_attempts"
        self._count = 0

    async def async_update(self) -> None:
        try:
            logs = await self._api.get_logs(limit=50)
            # Count failed_auth events in the last 5 minutes
            from datetime import datetime, timedelta, timezone
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            self._count = sum(
                1 for e in logs
                if e.get("event_type") == "failed_auth"
                and (e.get("timestamp") or "") >= cutoff
            )
        except Exception:
            pass  # keep last known value

    @property
    def native_value(self) -> int:
        return self._count
