"""
HomeSecure HA Integration — config_flow
Collects the container URL and optional API token.
Auto-detects the supervisor internal addon URL when possible.
"""
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Internal supervisor URL — works from within the HA network without needing
# the addon slug. Falls back to this if supervisor token is unavailable.
DEFAULT_URL = "http://c2e9a60a-homesecure:8099"


async def _detect_container_url(hass) -> str:
    """Try to auto-detect the container URL via the supervisor API."""
    try:
        supervisor_token = hass.auth._store._data.get("supervisor_token") or ""
        # Try the well-known internal hostname first
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{DEFAULT_URL}/health",
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                if resp.status == 200:
                    return DEFAULT_URL
    except Exception:
        pass
    return DEFAULT_URL


class HomeSecureConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow — point HA at the HomeSecure container."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors = {}

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            url   = user_input["container_url"].rstrip("/")
            token = user_input.get("api_token") or None

            ok, err = await self._test_connection(url, token)
            if not ok:
                errors["container_url"] = "cannot_connect"
                _LOGGER.warning("Container connection test failed: %s", err)
            else:
                return self.async_create_entry(
                    title="HomeSecure",
                    data={
                        "container_url": url,
                        "api_token":     token,
                    },
                )

        # Auto-detect the URL for the default value
        detected_url = await _detect_container_url(self.hass)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("container_url", default=detected_url): cv.string,
                vol.Optional("api_token"): cv.string,
            }),
            errors=errors,
        )

    async def _test_connection(self, url: str, token: str | None) -> tuple[bool, str]:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{url}/health", headers=headers,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        return True, ""
                    return False, f"HTTP {resp.status}"
        except aiohttp.ClientConnectorError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return HomeSecureOptionsFlow(config_entry)


class HomeSecureOptionsFlow(config_entries.OptionsFlow):
    """Allow changing the container URL and token post-setup."""

    def __init__(self, config_entry):
        """Store config entry — required for HA versions before 2024.x."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_url   = self.config_entry.options.get(
            "container_url",
            self.config_entry.data.get("container_url", DEFAULT_URL),
        )
        current_token = self.config_entry.options.get(
            "api_token",
            self.config_entry.data.get("api_token", ""),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("container_url", default=current_url): cv.string,
                vol.Optional("api_token", default=current_token): cv.string,
            }),
        )
