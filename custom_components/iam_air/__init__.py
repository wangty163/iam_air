"""IAM Air integration setup."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .cloud import (
    IamAirAuthError,
    IamAirConnectionError,
    IamAirError,
    IamCloudClient,
)
from .const import (
    CONF_APP_KEY,
    CONF_APP_SECRET,
    CREDENTIALS_DIRECTORY,
    CREDENTIALS_FILENAME,
    PLATFORMS,
)
from .coordinator import IamAirCoordinator
from .credentials import (
    IamAirCredentialsError,
    IamAppCredentials,
    load_app_credentials,
)


@dataclass(slots=True)
class IamAirRuntimeData:
    """Runtime objects associated with one config entry."""

    client: IamCloudClient
    coordinator: IamAirCoordinator


type IamAirConfigEntry = ConfigEntry[IamAirRuntimeData]


def credentials_path(hass: HomeAssistant) -> str:
    """Return the fixed private application credentials path."""
    return hass.config.path(CREDENTIALS_DIRECTORY, CREDENTIALS_FILENAME)


async def async_load_app_credentials(
    hass: HomeAssistant,
    entry_data: Mapping[str, Any] | None = None,
) -> IamAppCredentials:
    """Load application credentials, preserving legacy version-one entries."""
    if (
        entry_data is not None
        and isinstance(entry_data.get(CONF_APP_KEY), str)
        and isinstance(entry_data.get(CONF_APP_SECRET), str)
    ):
        return IamAppCredentials(
            app_key=str(entry_data[CONF_APP_KEY]),
            app_secret=str(entry_data[CONF_APP_SECRET]),
        )
    return await hass.async_add_executor_job(
        load_app_credentials,
        credentials_path(hass),
    )


async def async_migrate_entry(
    hass: HomeAssistant,
    entry: IamAirConfigEntry,
) -> bool:
    """Migrate older config entries without exposing stored credentials."""
    if entry.version < 3:
        data = dict(entry.data)
        data.pop("apk_path", None)
        hass.config_entries.async_update_entry(entry, data=data, version=3)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IamAirConfigEntry) -> bool:
    """Set up IAM Air from a config entry."""
    try:
        credentials = await async_load_app_credentials(hass, entry.data)
        client = IamCloudClient(
            async_get_clientsession(hass),
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            app_key=credentials.app_key,
            app_secret=credentials.app_secret,
        )
        await client.async_login()
        devices = await client.async_discover_air_devices()
    except IamAirCredentialsError as err:
        raise ConfigEntryNotReady(
            "IAM application credentials are unavailable"
        ) from err
    except IamAirAuthError as err:
        raise ConfigEntryAuthFailed("IAM Air authentication failed") from err
    except IamAirConnectionError as err:
        raise ConfigEntryNotReady("IAM cloud is not reachable") from err
    except IamAirError as err:
        raise ConfigEntryNotReady("IAM cloud setup failed") from err

    if not devices:
        raise ConfigEntryNotReady("No bound device exposes an air-purifier TSL")

    coordinator = IamAirCoordinator(
        hass,
        config_entry=entry,
        client=client,
        devices=devices,
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = IamAirRuntimeData(
        client=client,
        coordinator=coordinator,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IamAirConfigEntry) -> bool:
    """Unload an IAM Air config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
