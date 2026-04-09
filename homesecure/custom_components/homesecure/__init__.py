"""
HomeSecure HA Integration — __init__.py (Phase 2 thin version)
Sets up the API client that talks to the HomeSecure container.
All business logic has moved to the container.
"""
import logging
import secrets

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api_client import HomeSecureAPIClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["alarm_control_panel", "sensor"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HomeSecure from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    container_url = entry.data.get("container_url", "http://localhost:8099")
    api_token     = entry.data.get("api_token")   # optional

    # Ensure a service_pin exists in the entry data (used to arm via HA UI)
    if "service_pin" not in entry.data:
        await _migrate_add_service_pin(hass, entry)

    api_client = HomeSecureAPIClient(hass, container_url, api_token)

    # Fetch initial state synchronously to validate connectivity
    # but start the WS listener as a background task so it does not
    # block HA's startup phase (which has a strict timeout).
    try:
        await api_client.async_connect()
    except Exception as exc:
        _LOGGER.error("Cannot connect to HomeSecure container at %s: %s",
                      container_url, exc)
        return False

    hass.data[DOMAIN][entry.entry_id] = {
        "api_client": api_client,
        "entry": entry,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start WS listener after platforms are set up, outside the startup phase
    entry.async_on_unload(
        hass.bus.async_listen_once(
            "homeassistant_started",
            lambda _: api_client.async_start_ws(),
        )
    )

    _LOGGER.info(
        "HomeSecure integration connected to container at %s", container_url
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        client = hass.data[DOMAIN].pop(entry.entry_id, {}).get("api_client")
        if client:
            await client.async_stop()
    return unload_ok


async def _migrate_add_service_pin(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Add a service_pin to legacy config entries that don't have one."""
    pin = "".join(str(secrets.randbelow(10)) for _ in range(8))
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "service_pin": pin}
    )
    _LOGGER.info("Migrated config entry: service_pin added")
