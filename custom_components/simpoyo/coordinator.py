"""Shared polling and private session storage."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import SimpoyoAuthError, SimpoyoClient, SimpoyoError
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class SimpoyoCoordinator(DataUpdateCoordinator[dict]):
    """Fetch once per account and share results among entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: SimpoyoClient):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}", private=True)
        self._saved_cookies = None

    async def _async_setup(self) -> None:
        if stored := await self.store.async_load():
            self._saved_cookies = stored.get("cookies", [])
            self.client.import_cookies(self._saved_cookies)

    async def _async_update_data(self) -> dict:
        try:
            plans = await self.client.async_fetch_usage()
        except SimpoyoAuthError as err:
            raise ConfigEntryAuthFailed("Simpoyo authentication failed") from err
        except SimpoyoError as err:
            raise UpdateFailed("Unable to fetch Simpoyo usage") from err
        cookies = self.client.export_cookies()
        if cookies != self._saved_cookies:
            await self.store.async_save({"cookies": cookies})
            self._saved_cookies = cookies
        return {"plans": plans, "checked_at": dt_util.utcnow().isoformat()}
