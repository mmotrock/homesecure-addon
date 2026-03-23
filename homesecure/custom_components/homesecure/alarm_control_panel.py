"""
HomeSecure HA Integration — alarm_control_panel (thin proxy)
All business logic lives in the container.  This entity just:
  1. Forwards arm/disarm calls to the container REST API
  2. Reflects state updates that arrive via WebSocket
"""
import logging
from typing import Any, Optional

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Map container state strings to HA alarm state strings (they match, but
# keep explicit for clarity and easier future mapping).
STATE_MAP = {
    "disarmed":    "disarmed",
    "arming":      "arming",
    "armed_home":  "armed_home",
    "armed_away":  "armed_away",
    "pending":     "pending",
    "triggered":   "triggered",
    "unknown":     "unknown",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    api_client = hass.data[DOMAIN][entry.entry_id]["api_client"]
    async_add_entities([HomeSecureAlarmPanel(api_client, entry)], True)


class HomeSecureAlarmPanel(AlarmControlPanelEntity):
    """Thin alarm panel that proxies to the HomeSecure container API."""

    _attr_has_entity_name    = True
    _attr_name               = "HomeSecure"
    _attr_should_poll        = False
    _attr_code_arm_required  = False   # container validates the PIN itself
    _attr_code_format        = "number"

    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.TRIGGER
    )

    def __init__(self, api_client, entry: ConfigEntry):
        self._api    = api_client
        self._entry  = entry
        self._attr_unique_id = f"{DOMAIN}_main_panel"

    # ------------------------------------------------------------------ #
    #  HA lifecycle                                                        #
    # ------------------------------------------------------------------ #

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._api.add_listener(self._on_state_update)

    async def async_will_remove_from_hass(self) -> None:
        self._api.remove_listener(self._on_state_update)

    # ------------------------------------------------------------------ #
    #  State                                                               #
    # ------------------------------------------------------------------ #

    @callback
    def _on_state_update(self) -> None:
        """Called by the API client whenever the container pushes a new state."""
        self.async_write_ha_state()

    @property
    def state(self) -> str:
        return STATE_MAP.get(self._api.state, "unknown")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "changed_by":   self._api.changed_by,
            "triggered_by": self._api.triggered_by,
        }

    # ------------------------------------------------------------------ #
    #  Commands → forwarded to container                                  #
    # ------------------------------------------------------------------ #

    async def async_alarm_disarm(self, code: Optional[str] = None) -> None:
        if not code:
            _LOGGER.warning("Disarm called without PIN")
            return
        result = await self._api.disarm(code)
        if not result.get("success"):
            _LOGGER.warning("Disarm failed: %s", result.get("message"))

    async def async_alarm_arm_home(self, code: Optional[str] = None) -> None:
        # When called from the HA UI without a code we use the service PIN
        # stored in the config entry (generated at setup time).
        pin = code or self._entry.data.get("service_pin", "")
        result = await self._api.arm_home(pin)
        if not result.get("success"):
            _LOGGER.warning("Arm home failed: %s", result.get("message"))

    async def async_alarm_arm_away(self, code: Optional[str] = None) -> None:
        pin = code or self._entry.data.get("service_pin", "")
        result = await self._api.arm_away(pin)
        if not result.get("success"):
            _LOGGER.warning("Arm away failed: %s", result.get("message"))

    async def async_alarm_trigger(self, code: Optional[str] = None) -> None:
        # Manual trigger — uses the service PIN so the container accepts it
        pin = self._entry.data.get("service_pin", "")
        result = await self._api.arm_away(pin)   # trigger via arm+force
        _LOGGER.info("Manual trigger requested: %s", result)

    # ------------------------------------------------------------------ #
    #  Icon                                                                #
    # ------------------------------------------------------------------ #

    @property
    def icon(self) -> str:
        icons = {
            "disarmed":   "mdi:shield-off",
            "arming":     "mdi:shield-sync",
            "armed_home": "mdi:shield-home",
            "armed_away": "mdi:shield-lock",
            "pending":    "mdi:shield-alert",
            "triggered":  "mdi:bell-ring",
        }
        return icons.get(self._api.state, "mdi:shield")
