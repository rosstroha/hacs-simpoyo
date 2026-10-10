"""Simpoyo cloud usage integration."""

from aiohttp import CookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store

from .api import SimpoyoClient
from .const import CONF_GMAIL_APP_PASSWORD, CONF_GMAIL_EMAIL, DOMAIN
from .coordinator import SimpoyoCoordinator

type SimpoyoConfigEntry = ConfigEntry[SimpoyoCoordinator]
PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: SimpoyoConfigEntry) -> bool:
    """Set up a configured account."""
    client = SimpoyoClient(
        entry.data[CONF_EMAIL],
        entry.data[CONF_GMAIL_EMAIL],
        entry.data[CONF_GMAIL_APP_PASSWORD],
        session=async_create_clientsession(hass, cookie_jar=CookieJar()),
        executor=hass.async_add_executor_job,
    )
    coordinator = SimpoyoCoordinator(hass, entry, client)
    flow_cookies = hass.data.get(f"{DOMAIN}_flow_cookies", {}).pop(
        entry.data[CONF_EMAIL], None
    )
    try:
        if flow_cookies is not None:
            await coordinator.store.async_save({"cookies": flow_cookies})
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await client.async_close()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SimpoyoConfigEntry) -> bool:
    """Unload entities and release the account session."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.client.async_close()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete saved authentication when you remove an account."""
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}", private=True).async_remove()
