"""Config flow for HomeSecure."""
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN
from .database import AlarmDatabase

_LOGGER = logging.getLogger(__name__)

class SecureAlarmConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HomeSecure."""
    
    VERSION = 1
    
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}
        
        if user_input is not None:
            # Check if already configured
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            
            # Validate admin setup
            admin_name = user_input.get("admin_name")
            admin_pin = user_input.get("admin_pin")
            admin_pin_confirm = user_input.get("admin_pin_confirm")
            zwave_server_url = user_input.get("zwave_server_url", "ws://a0d7b954-zwavejs2mqtt.local.hass.io:3000")
            
            # Validate PIN
            if len(admin_pin) < 6 or len(admin_pin) > 8:
                errors["admin_pin"] = "pin_length"
            elif admin_pin != admin_pin_confirm:
                errors["admin_pin_confirm"] = "pin_mismatch"
            elif not admin_pin.isdigit():
                errors["admin_pin"] = "pin_numeric"
            
            if not errors:
                # Create entry - INCLUDE zwave_server_url!
                return self.async_create_entry(
                    title="HomeSecure",
                    data={
                        "admin_name": admin_name,
                        "admin_pin": admin_pin,
                        "zwave_server_url": zwave_server_url,
                    },
                )
        
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("admin_name", default="Admin"): cv.string,
                vol.Required("admin_pin"): cv.string,
                vol.Required("admin_pin_confirm"): cv.string,
                vol.Optional("zwave_server_url", default="ws://a0d7b954-zwavejs2mqtt.local.hass.io:3000"): cv.string, 
            }),
            errors=errors,
        )
    
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return SecureAlarmOptionsFlow(config_entry)

class SecureAlarmOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for HomeSecure."""
    
    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry
    
    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    "entry_delay",
                    default=self.config_entry.options.get("entry_delay", 30)
                ): cv.positive_int,
                vol.Optional(
                    "exit_delay",
                    default=self.config_entry.options.get("exit_delay", 60)
                ): cv.positive_int,
                vol.Optional(
                    "alarm_duration",
                    default=self.config_entry.options.get("alarm_duration", 300)
                ): cv.positive_int,
            })
        )