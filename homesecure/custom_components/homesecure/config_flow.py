"""
HomeSecure HA Integration — config_flow
Collects container URL, API token, and creates the first admin user
during setup so no separate bootstrap step is needed.
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

DEFAULT_URL = "http://c2e9a60a-homesecure:8099"


class HomeSecureConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow — connect to container and create first admin user."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors = {}

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            url        = user_input["container_url"].rstrip("/")
            token      = user_input.get("api_token") or None
            admin_name = user_input.get("admin_name", "").strip()
            admin_pin  = user_input.get("admin_pin", "")
            confirm    = user_input.get("pin_confirm", "")

            # Validate PIN format
            if not admin_pin.isdigit():
                errors["admin_pin"] = "pin_digits_only"
            elif not (6 <= len(admin_pin) <= 8):
                errors["admin_pin"] = "pin_length"
            elif admin_pin != confirm:
                errors["pin_confirm"] = "pin_mismatch"

            if not errors:
                # Verify we can reach the container
                ok, err = await self._test_connection(url, token)
                if not ok:
                    errors["container_url"] = "cannot_connect"
                    _LOGGER.warning("Container connection test failed: %s", err)

            if not errors:
                # If name and PIN provided, try to create the first admin user
                if admin_name and admin_pin:
                    created, msg = await self._create_first_user(
                        url, token, admin_name, admin_pin
                    )
                    if not created:
                        # Not a hard failure — user may already exist
                        _LOGGER.info("First user creation skipped: %s", msg)

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
                vol.Required("container_url", default=DEFAULT_URL):  cv.string,
                vol.Optional("api_token",     default=""):           cv.string,
                vol.Optional("admin_name",    default="Admin"):      cv.string,
                vol.Required("admin_pin",    default=""):          cv.string,
                vol.Required("pin_confirm", default=""):            cv.string,
            }),
            errors=errors,
            description_placeholders={
                "default_url": DEFAULT_URL,
            },
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
        except Exception as exc:
            return False, str(exc)

    async def _create_first_user(
        self, url: str, token: str | None, name: str, pin: str
    ) -> tuple[bool, str]:
        """Attempt to create the first admin user via the bootstrap path."""
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with aiohttp.ClientSession() as session:
                # Check if any users already exist
                async with session.get(
                    f"{url}/api/users", headers=headers,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("users"):
                            return False, "Users already exist — skipping first-user creation"

                # No users — use bootstrap path (admin_pin ignored server-side)
                import json
                payload = json.dumps({
                    "name":      name,
                    "pin":       pin,
                    "admin_pin": pin,   # server accepts any value when no users exist
                    "is_admin":  True,
                })
                async with session.post(
                    f"{url}/api/users", headers=headers, data=payload,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    result = await resp.json()
                    if result.get("success"):
                        _LOGGER.info("First admin user '%s' created successfully", name)
                        return True, "Created"
                    return False, result.get("message", "Unknown error")
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return HomeSecureOptionsFlow()


class HomeSecureOptionsFlow(config_entries.OptionsFlow):
    """Allow changing the container URL and token post-setup."""

    def __init__(self) -> None:
        """Initialise with no arguments — HA sets self.config_entry automatically."""
        super().__init__()

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        entry = self.config_entry
        current_url = entry.options.get(
            "container_url", entry.data.get("container_url", DEFAULT_URL)
        )
        current_token = entry.options.get(
            "api_token", entry.data.get("api_token", "")
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("container_url", default=current_url):   cv.string,
                vol.Optional("api_token",     default=current_token): cv.string,
            }),
        )
