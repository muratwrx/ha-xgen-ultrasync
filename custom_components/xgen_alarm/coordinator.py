"""Keeps the panel state up to date."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PanelState, XGenAuthError, XGenClient, XGenError
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type XGenConfigEntry = ConfigEntry[XGenCoordinator]


class XGenCoordinator(DataUpdateCoordinator[PanelState]):
    """Polls the panel's change counters and fetches what changed."""

    config_entry: XGenConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: XGenConfigEntry, client: XGenClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self._ready = False

    async def _async_update_data(self) -> PanelState:
        try:
            if not self._ready:
                state = await self.client.async_setup()
                self._ready = True
                return state
            return await self.client.async_update()
        except XGenAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except XGenError as err:
            raise UpdateFailed(str(err)) from err

    def push(self) -> None:
        """Publish state the client already has (e.g. from a command reply)."""
        self.async_set_updated_data(self.client.state)
