"""Coordinator for Daikin integration."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from pydaikin.daikin_base import Appliance

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TIMEOUT, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import ATTR_COOL_ENERGY, ATTR_ENERGY_TODAY, ATTR_HEAT_ENERGY, DOMAIN, TIMEOUT_SEC
from .utils import calculate_energy_sum, parse_daikin_list

try:
    from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
    from homeassistant.components.recorder.statistics import async_import_statistics
    from homeassistant.components.recorder.const import StatisticMeanType
except ImportError:
    # Fallback for environments without recorder
    StatisticData = None
    StatisticMetaData = None
    async_import_statistics = None
    StatisticMeanType = None

_LOGGER = logging.getLogger(__name__)

type DaikinConfigEntry = ConfigEntry[DaikinCoordinator]


@dataclass
class DaikinData:
    """Class to hold Daikin data."""

    appliance: Appliance
    calculated_total_energy_today: float
    today_cool_energy: float
    today_heat_energy: float


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
        self._last_total_energy_today = 0
        self._integrated_total_energy = 0
        self._last_update_time = None
        self._last_power = 0
        self._last_history_sync = None

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

        # Energy smoothing logic for TOTAL system energy
        now = dt_util.utcnow()
        current_power = getattr(self.device, "current_total_power_consumption", 0) or 0
        real_total_energy_today = (
            getattr(self.device, "today_total_energy_consumption", 0) or 0
        )

        if self._last_update_time is not None:
            delta_h = (now - self._last_update_time).total_seconds() / 3600
            avg_power = (self._last_power + current_power) / 2
            energy_delta = avg_power * delta_h
            self._integrated_total_energy += energy_delta

        # Detect reset (midnight) or new data block arrival for total energy
        if real_total_energy_today != self._last_total_energy_today:
            self._integrated_total_energy = 0
            self._last_total_energy_today = real_total_energy_today

        self._last_update_time = now
        self._last_power = current_power

        # Periodic history sync (every hour)
        if (
            self._last_history_sync is None
            or now - self._last_history_sync > timedelta(hours=1)
        ):
            self.hass.async_create_task(self.async_sync_history())
            self._last_history_sync = now

        # Calculate current cumulative cool/heat totals from arrays
        today_cool = self._get_sum_from_daikin_key("curr_day_cool")
        today_heat = self._get_sum_from_daikin_key("curr_day_heat")

        return DaikinData(
            appliance=self.device,
            calculated_total_energy_today=real_total_energy_today
            + self._integrated_total_energy,
            today_cool_energy=today_cool,
            today_heat_energy=today_heat,
        )

    def _get_sum_from_daikin_key(self, daikin_key: str) -> float:
        """Calculate sum from a Daikin historical data key."""
        raw_data = self.device.values.get(daikin_key, [])
        data = parse_daikin_list(raw_data)
        return calculate_energy_sum(data)

    async def async_sync_history(self, days_ago: int = 0) -> None:
        """Sync energy history with Daikin historical data."""
        if async_import_statistics is None:
            return

        _LOGGER.debug("Syncing energy history for %s (days_ago=%s)", self.name, days_ago)

        # Get historical data arrays
        if days_ago == 0:
            normal_data = self.device.values.get("curr_day_energy", [])
            cool_data = self.device.values.get("curr_day_cool", [])
            heat_data = self.device.values.get("curr_day_heat", [])
            base_date = dt_util.start_of_local_day()
        else:
            normal_data = self.device.values.get("prev_1day_energy", [])
            cool_data = self.device.values.get("prev_1day_cool", [])
            heat_data = self.device.values.get("prev_1day_heat", [])
            base_date = dt_util.start_of_local_day() - timedelta(days=1)

        # Map to actual entity IDs
        ent_reg = er.async_get(self.hass)
        
        for key, raw_data in {
            ATTR_ENERGY_TODAY: normal_data,
            ATTR_COOL_ENERGY: cool_data,
            ATTR_HEAT_ENERGY: heat_data,
        }.items():
            data = parse_daikin_list(raw_data)
            if not data:
                continue

            unique_id = f"{self.device.mac}-{key}"
            entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
            if not entity_id:
                continue

            await self._async_import_data_to_stats(entity_id, data, base_date)

    async def _async_import_data_to_stats(
        self, entity_id: str, data: list[int], base_date: datetime
    ) -> None:
        """Import a list of hourly deltas into HA statistics."""
        metadata = StatisticMetaData(
            has_mean=False,
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=None,  # Will be taken from entity
            source="recorder",
            statistic_id=entity_id,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            unit_class="energy",
        )

        statistics = []
        cumulative_sum = 0.0
        
        # Values are typically in 0.1 kWh
        for hour, delta_int in enumerate(data):
            if hour >= 24:
                break
            
            delta = delta_int / 10.0  # Convert to kWh
            cumulative_sum += delta
            
            start_time = base_date + timedelta(hours=hour)
            start_time_utc = dt_util.as_utc(start_time)
            
            if start_time_utc > dt_util.utcnow():
                break

            statistics.append(
                StatisticData(
                    start=start_time_utc,
                    state=delta,
                    sum=cumulative_sum,
                )
            )

        if statistics:
            _LOGGER.debug(
                "Importing %s hourly data points for %s on %s",
                len(statistics),
                entity_id,
                base_date.date(),
            )
            async_import_statistics(self.hass, metadata, statistics)
