"""
Binary sensor platform for HomeSecure.
Creates one BinarySensorEntity per zone registered in the container.
Zone list is fetched once on setup; the container's WebSocket stream
triggers a state refresh whenever the alarm state changes (which affects
which zones are active/bypassed).
"""
import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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

    try:
        zones = await api_client.get_zones()
    except Exception as exc:
        _LOGGER.warning("Could not fetch zones from container: %s", exc)
        zones = []

    entities = [HomeSecureZone(api_client, zone) for zone in zones]
    if entities:
        async_add_entities(entities, True)
        _LOGGER.info("Created %d zone sensor(s)", len(entities))
    else:
        _LOGGER.info("No zones registered in container yet")


class HomeSecureZone(BinarySensorEntity):
    """
    Binary sensor representing a single HomeSecure zone.

    is_on  = True  → zone is open / active
    is_on  = False → zone is closed / secure

    The actual open/closed state comes from HA's own entity registry for
    the underlying sensor (door/window/motion).  This entity adds the
    HomeSecure context: zone type, bypass status, and which arm modes it
    is active in.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.DOOR  # sensible default

    def __init__(self, api_client, zone: dict):
        self._api       = api_client
        self._zone      = zone
        self._entity_id_ref = zone.get("entity_id", "")   # HA entity this zone tracks
        self._bypassed  = bool(zone.get("bypassed", False))

        zone_name = zone.get("zone_name", self._entity_id_ref)
        self._attr_name        = zone_name
        self._attr_unique_id   = f"{DOMAIN}_zone_{self._entity_id_ref.replace('.', '_')}"

        # Map zone_type to a device class where possible
        zone_type = zone.get("zone_type", "")
        self._attr_device_class = {
            "perimeter": BinarySensorDeviceClass.DOOR,
            "entry":     BinarySensorDeviceClass.DOOR,
            "interior":  BinarySensorDeviceClass.MOTION,
        }.get(zone_type, BinarySensorDeviceClass.DOOR)

    # ------------------------------------------------------------------ #
    #  HA lifecycle                                                        #
    # ------------------------------------------------------------------ #

    async def async_added_to_hass(self) -> None:
        # Re-fetch zone state when alarm state changes (bypasses may change)
        self._api.add_listener(self._on_alarm_state_update)

    async def async_will_remove_from_hass(self) -> None:
        self._api.remove_listener(self._on_alarm_state_update)

    @callback
    def _on_alarm_state_update(self) -> None:
        """Alarm state changed — refresh bypass status from container."""
        self.hass.async_create_task(self._refresh_zone())

    async def _refresh_zone(self) -> None:
        try:
            zones = await self._api.get_zones()
            match = next(
                (z for z in zones if z.get("entity_id") == self._entity_id_ref),
                None,
            )
            if match:
                self._zone     = match
                self._bypassed = bool(match.get("bypassed", False))
                self.async_write_ha_state()
        except Exception as exc:
            _LOGGER.debug("Zone refresh failed for %s: %s", self._entity_id_ref, exc)

    # ------------------------------------------------------------------ #
    #  State                                                               #
    # ------------------------------------------------------------------ #

    @property
    def is_on(self) -> bool:
        """
        Delegate to the underlying HA entity state.
        Returns True (open/active) if the tracked entity is 'on' or 'open'.
        Falls back to False if the entity isn't found.
        """
        if not self._entity_id_ref or not self.hass:
            return False
        state = self.hass.states.get(self._entity_id_ref)
        if state is None:
            return False
        return state.state in ("on", "open", "detected", "unlocked")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "zone_type":     self._zone.get("zone_type"),
            "entity_id_ref": self._entity_id_ref,
            "bypassed":      self._bypassed,
            "enabled_away":  bool(self._zone.get("enabled_away", True)),
            "enabled_home":  bool(self._zone.get("enabled_home", True)),
        }

    @property
    def icon(self) -> str:
        if self._bypassed:
            return "mdi:shield-off"
        return "mdi:shield-check" if not self.is_on else "mdi:shield-alert"
