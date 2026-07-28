"""IAM Air integration setup."""

from __future__ import annotations

from dataclasses import dataclass

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
from .const import CONF_APP_KEY, CONF_APP_SECRET, PLATFORMS
from .coordinator import IamAirCoordinator


@dataclass(slots=True)
class IamAirRuntimeData:
    """Runtime objects associated with one config entry."""

    client: IamCloudClient
    coordinator: IamAirCoordinator


type IamAirConfigEntry = ConfigEntry[IamAirRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: IamAirConfigEntry) -> bool:
    """Set up IAM Air from a config entry."""
    client = IamCloudClient(
        async_get_clientsession(hass),
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        app_key=entry.data[CONF_APP_KEY],
        app_secret=entry.data[CONF_APP_SECRET],
    )
    try:
        await client.async_login()
        devices = await client.async_discover_air_devices()
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
