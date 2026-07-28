"""Config flow for IAM Air."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .cloud import (
    IamAirAuthError,
    IamAirConnectionError,
    IamAirError,
    IamCloudClient,
)
from .const import CONF_APP_KEY, CONF_APP_SECRET, DOMAIN

_LOGGER = logging.getLogger(__name__)


def user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the account form without defining any credential defaults."""
    defaults = defaults or {}
    username_marker = (
        vol.Required(CONF_USERNAME, default=defaults[CONF_USERNAME])
        if CONF_USERNAME in defaults
        else vol.Required(CONF_USERNAME)
    )
    app_key_marker = (
        vol.Required(CONF_APP_KEY, default=defaults[CONF_APP_KEY])
        if CONF_APP_KEY in defaults
        else vol.Required(CONF_APP_KEY)
    )
    return vol.Schema(
        {
            username_marker: TextSelector(),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            app_key_marker: TextSelector(),
            vol.Required(CONF_APP_SECRET): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        }
    )


class IamAirConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure IAM Air through the UI."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle initial account configuration."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = IamCloudClient(
                async_get_clientsession(self.hass),
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                app_key=user_input[CONF_APP_KEY],
                app_secret=user_input[CONF_APP_SECRET],
            )
            try:
                await client.async_login()
                devices = await client.async_discover_air_devices()
            except IamAirAuthError:
                errors["base"] = "invalid_auth"
            except IamAirConnectionError:
                errors["base"] = "cannot_connect"
            except IamAirError:
                _LOGGER.exception("IAM Air configuration failed")
                errors["base"] = "unknown"
            else:
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    digest = hashlib.sha256(
                        (
                            user_input[CONF_USERNAME].strip().lower()
                            + "\0"
                            + user_input[CONF_APP_KEY].strip()
                        ).encode()
                    ).hexdigest()[:24]
                    await self.async_set_unique_id(f"account-{digest}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="IAM Air",
                        data=user_input,
                    )

        visible_defaults = {
            key: value
            for key, value in (user_input or {}).items()
            if key not in {CONF_PASSWORD, CONF_APP_SECRET}
        }
        return self.async_show_form(
            step_id="user",
            data_schema=user_schema(visible_defaults),
            errors=errors,
        )

    async def async_step_reauth(
        self, _entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after a credential failure."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate replacement credentials and reload the entry."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            client = IamCloudClient(
                async_get_clientsession(self.hass),
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                app_key=user_input[CONF_APP_KEY],
                app_secret=user_input[CONF_APP_SECRET],
            )
            try:
                await client.async_login()
                devices = await client.async_discover_air_devices()
            except IamAirAuthError:
                errors["base"] = "invalid_auth"
            except IamAirConnectionError:
                errors["base"] = "cannot_connect"
            except IamAirError:
                _LOGGER.exception("IAM Air reauthentication failed")
                errors["base"] = "unknown"
            else:
                if devices:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates=user_input,
                    )
                errors["base"] = "no_devices"

        defaults = {
            CONF_USERNAME: entry.data[CONF_USERNAME],
            CONF_APP_KEY: entry.data[CONF_APP_KEY],
        }
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=user_schema(defaults),
            errors=errors,
        )
