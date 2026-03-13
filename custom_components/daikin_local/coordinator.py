"""Coordinator for Daikin integration."""

import asyncio
from datetime import timedelta
import logging

from pydaikin.daikin_base import Appliance

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, TIMEOUT_SEC

_LOGGER = logging.getLogger(__name__)

type DaikinConfigEntry = ConfigEntry[DaikinCoordinator]


class DaikinCoordinator(DataUpdateCoordinator[Appliance]):
    """Class to manage fetching Daikin data."""

    def __init__(
        self, hass: HomeAssistant, entry: DaikinConfigEntry, device: Appliance
    ) -> None:
        """Initialize global Daikin data updater."""
        timeout = entry.options.get(
            CONF_TIMEOUT, entry.data.get(CONF_TIMEOUT, TIMEOUT_SEC)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=device.values.get("name", DOMAIN),
            update_interval=timedelta(seconds=timeout),
        )
        self.device = device

    async def _async_update_data(self) -> Appliance:
        """Update data."""
        timeout = self.config_entry.options.get(
            CONF_TIMEOUT, self.config_entry.data.get(CONF_TIMEOUT, TIMEOUT_SEC)
        )
        try:
            async with asyncio.timeout(timeout):
                await self.device.update_status()
        except TimeoutError as err:
            raise UpdateFailed(
                f"Timeout communicating with Daikin {self.name}: {err}"
            ) from err
        except Exception as err:
            raise UpdateFailed(
                f"Error communicating with Daikin {self.name}: {err}"
            ) from err
        return self.device
