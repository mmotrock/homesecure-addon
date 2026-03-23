"""
HomeSecure HA Integration — config_flow (Phase 2)
Now only collects the container URL and optional API token.
No PIN setup here — that's handled in the container's first-run setup.
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

DEFAULT_URL = "http://localhost:8099"


class HomeSecureConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow — just point HA at the container."""

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

            # Verify we can reach the container
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

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("container_url", default=DEFAULT_URL): cv.string,
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
                    f"{url}/health", headers=headers, timeout=aiohttp.ClientTimeout(total=5)
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
    """Allow changing the container URL post-setup."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    "container_url",
                    default=self.config_entry.data.get("container_url", DEFAULT_URL),
                ): cv.string,
                vol.Optional(
                    "api_token",
                    default=self.config_entry.data.get("api_token", ""),
                ): cv.string,
            }),
        )
