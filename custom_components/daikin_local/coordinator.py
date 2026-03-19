"""Coordinator for Daikin integration."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging

from pydaikin.daikin_base import Appliance

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, TIMEOUT_SEC

_LOGGER = logging.getLogger(__name__)

type DaikinConfigEntry = ConfigEntry[DaikinCoordinator]


@dataclass
class DaikinData:
    """Class to hold Daikin data."""

    appliance: Appliance
    calculated_energy_today: float
    calculated_total_energy_today: float
    calculated_cool_energy: float
    calculated_heat_energy: float


class DaikinCoordinator(DataUpdateCoordinator[DaikinData]):
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
        self._last_energy_today = 0
        self._last_total_energy_today = 0
        self._last_cool_energy = 0
        self._last_heat_energy = 0

        self._integrated_energy = 0
        self._integrated_total_energy = 0
        self._integrated_cool_energy = 0
        self._integrated_heat_energy = 0

        self._last_update_time = None
        self._last_power = 0

    async def _async_update_data(self) -> DaikinData:
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

        # Energy smoothing logic
        now = dt_util.utcnow()
        current_power = getattr(self.device, "current_total_power_consumption", 0) or 0
        real_energy_today = getattr(self.device, "today_energy_consumption", 0) or 0
        real_total_energy_today = (
            getattr(self.device, "today_total_energy_consumption", 0) or 0
        )
        real_cool_energy = (
            getattr(self.device, "last_hour_cool_energy_consumption", 0) or 0
        )
        real_heat_energy = (
            getattr(self.device, "last_hour_heat_energy_consumption", 0) or 0
        )

        daikin_mode = self.device.represent("mode")[1]

        if self._last_update_time is not None:
            delta_h = (now - self._last_update_time).total_seconds() / 3600
            avg_power = (self._last_power + current_power) / 2
            energy_delta = avg_power * delta_h
            self._integrated_energy += energy_delta
            self._integrated_total_energy += energy_delta
            
            if daikin_mode == "cool":
                self._integrated_cool_energy += energy_delta
            elif daikin_mode in ("hot", "heat"):
                self._integrated_heat_energy += energy_delta

        # Detect reset (midnight) or new data block arrival
        if real_energy_today != self._last_energy_today:
            self._integrated_energy = 0
            self._last_energy_today = real_energy_today

        if real_total_energy_today != self._last_total_energy_today:
            self._integrated_total_energy = 0
            self._last_total_energy_today = real_total_energy_today
            
        if real_cool_energy != self._last_cool_energy:
            self._integrated_cool_energy = 0
            self._last_cool_energy = real_cool_energy
            
        if real_heat_energy != self._last_heat_energy:
            self._integrated_heat_energy = 0
            self._last_heat_energy = real_heat_energy

        self._last_update_time = now
        self._last_power = current_power

        return DaikinData(
            appliance=self.device,
            calculated_energy_today=real_energy_today + self._integrated_energy,
            calculated_total_energy_today=real_total_energy_today
            + self._integrated_total_energy,
            calculated_cool_energy=real_cool_energy + self._integrated_cool_energy,
            calculated_heat_energy=real_heat_energy + self._integrated_heat_energy,
        )
