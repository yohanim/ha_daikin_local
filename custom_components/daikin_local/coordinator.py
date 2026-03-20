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
    from homeassistant.components.recorder.statistics import (
        async_import_statistics,
    )
    from homeassistant.components.recorder.const import StatisticMeanType
except ImportError:
    # Fallback for environments without recorder
    StatisticData = None
    StatisticMetaData = None
    async_import_statistics = None
    async_get_statistics = None
    StatisticMeanType = None

_LOGGER = logging.getLogger(__name__)

type DaikinConfigEntry = ConfigEntry[DaikinCoordinator]


@dataclass
class DaikinData:
    """Class to hold Daikin data."""

    appliance: Appliance
    calculated_total_energy_today: float
    today_energy: float
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
        # Prevent concurrent history imports into recorder statistics.
        self._history_sync_lock = asyncio.Lock()

    async def _async_update_data(self) -> DaikinData:
        """Update data."""
        timeout = self.config_entry.options.get(
            CONF_TIMEOUT, self.config_entry.data.get(CONF_TIMEOUT, TIMEOUT_SEC)
        )
        try:
            async with asyncio.timeout(timeout):
                await self.device.update_status()
                # Fetch extended energy if possible during regular update
                if hasattr(self.device, "get_day_power_ex"):
                    await self.device.get_day_power_ex()
        except Exception as err:
            raise UpdateFailed(
                f"Error communicating with Daikin {self.name}: {err}"
            ) from err

        # Energy smoothing logic
        now = dt_util.utcnow()
        current_power = getattr(self.device, "current_total_power_consumption", 0) or 0
        
        # Use property for smoothing if available, fallback to history sum
        real_total_energy_today = (
            getattr(self.device, "today_total_energy_consumption", 0) or 0
        )
        # Calculate base energy from history arrays for cool/heat
        today_cool = self._get_sum_from_daikin_key("curr_day_cool")
        today_heat = self._get_sum_from_daikin_key("curr_day_heat")

        local_midnight = dt_util.start_of_local_day()

        if self._last_update_time is not None:
            # Smooth the "total compressor energy" counter between API updates.
            delta_h = (now - self._last_update_time).total_seconds() / 3600
            avg_power = (self._last_power + current_power) / 2
            energy_delta = avg_power * delta_h
            self._integrated_total_energy += energy_delta

            # Daikin can "correct" its reported totals during the day.
            # Keep the displayed counter continuous unless we are close to
            # local midnight (where a real reset should happen).
            if self._last_total_energy_today != real_total_energy_today:
                old_calc = self._last_total_energy_today + self._integrated_total_energy
                if (
                    real_total_energy_today < self._last_total_energy_today
                    and now >= local_midnight + timedelta(hours=6)
                ):
                    # Decrease far from midnight: treat it as a correction,
                    # not a reset.
                    self._integrated_total_energy = old_calc - real_total_energy_today
                elif (
                    real_total_energy_today < self._last_total_energy_today
                    and now < local_midnight + timedelta(hours=6)
                ):
                    # Likely a real cycle reset at midnight.
                    self._integrated_total_energy = 0.0
                else:
                    # Normal correction: shift the integration baseline.
                    self._integrated_total_energy = old_calc - real_total_energy_today

                self._last_total_energy_today = real_total_energy_today
        else:
            # First run: establish baseline.
            self._last_total_energy_today = real_total_energy_today
            self._integrated_total_energy = 0.0

        self._last_update_time = now
        self._last_power = current_power

        # Periodic history sync (every hour)
        if (
            self._last_history_sync is None
            or now - self._last_history_sync > timedelta(hours=1)
        ):
            # Daikin can report consumption with a delay.
            # Sync both today and (recently) yesterday to catch late data
            # that crosses the midnight boundary.
            self.hass.async_create_task(self.async_sync_history(days_ago=0))

            local_midnight = dt_util.start_of_local_day()
            if now < local_midnight + timedelta(hours=3):
                self.hass.async_create_task(self.async_sync_history(days_ago=1))
            self._last_history_sync = now

        return DaikinData(
            appliance=self.device,
            calculated_total_energy_today=real_total_energy_today + self._integrated_total_energy,
            today_energy=real_total_energy_today,
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

        async with self._history_sync_lock:
            # Attempt to fetch historical data explicitly if pydaikin supports it
            if hasattr(self.device, "get_day_power_ex"):
                _LOGGER.debug("Fetching extended day power data for %s", self.name)
                try:
                    await self.device.get_day_power_ex()
                except Exception as err:
                    _LOGGER.warning(
                        "Failed to fetch extended power data for %s: %s",
                        self.name,
                        err,
                    )

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

            def _normalize_24(values: list[int]) -> list[int]:
                values = values[:24]
                if len(values) < 24:
                    values += [0] * (24 - len(values))
                return values

            normal_list = parse_daikin_list(normal_data)
            cool_list = parse_daikin_list(cool_data)
            heat_list = parse_daikin_list(heat_data)

            normal_available = bool(normal_list)
            cool_available = bool(cool_list)
            heat_available = bool(heat_list)

            # Fallback: if normal_data is empty but we have cool/heat, sum them up
            if not normal_available and (cool_list or heat_list):
                _LOGGER.debug(
                    "Energy missing for %s, calculating from cool/heat", self.name
                )
                cool_list = _normalize_24(cool_list)
                heat_list = _normalize_24(heat_list)
                normal_list = [c + h for c, h in zip(cool_list, heat_list)]
                normal_available = True

            # Normalize to 24 hourly deltas so all days compile consistently.
            normal_list = _normalize_24(normal_list) if normal_available else []
            cool_list = _normalize_24(cool_list) if cool_available else []
            heat_list = _normalize_24(heat_list) if heat_available else []

            _LOGGER.debug(
                "Data for %s: normal=%s, cool=%s, heat=%s",
                self.name,
                normal_list,
                cool_list,
                heat_list,
            )

            # Map to actual entity IDs
            ent_reg = er.async_get(self.hass)

            for key, data in {
                ATTR_ENERGY_TODAY: normal_list,
                ATTR_COOL_ENERGY: cool_list,
                ATTR_HEAT_ENERGY: heat_list,
            }.items():
                if not data:
                    continue

                unique_id = f"{self.device.mac}-{key}"
                entity_id = ent_reg.async_get_entity_id(
                    "sensor", DOMAIN, unique_id
                )
                if not entity_id:
                    _LOGGER.warning(
                        "Entity not found for %s (unique_id: %s). Is the sensor enabled?",
                        self.name,
                        unique_id,
                    )
                    continue

                _LOGGER.debug("Found entity_id %s for %s", entity_id, key)
                self.hass.async_create_task(
                    self._import_data_to_stats(entity_id, data, base_date)
                )

    async def _import_data_to_stats(
        self, entity_id: str, data: list[int], base_date: datetime
    ) -> None:
        """Import a list of hourly energy values into HA statistics.

        For HA energy/consumption aggregation (`state_class=total_increasing`),
        each statistic entry must represent the counter value at the end of
        the hour and include `last_reset` (we assume the counter resets at
        local midnight for the "today" entities).
        """
        # The "today" energy sensors reset at local midnight, so we start the
        # cumulative counter at 0 for this day.
        cumulative_sum = 0.0

        metadata: StatisticMetaData = {
            "mean_type": StatisticMeanType.NONE,
            "has_sum": True,
            "name": None,
            "source": "recorder",
            "statistic_id": entity_id,
            "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
            # For kWh, HA uses EnergyConverter -> UNIT_CLASS="energy".
            "unit_class": "energy",
        }

        statistics = []
        
        # Values are typically in 0.1 kWh
        padded = data[:24] + [0] * max(0, 24 - len(data))
        for hour, delta_int in enumerate(padded):
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
                    # `state` and `sum` represent the counter value at the end
                    # of the hour (HA takes the "last" value during the period
                    # when compiling hourly/daily rollups).
                    state=cumulative_sum,
                    sum=cumulative_sum,
                    last_reset=base_date,
                )
            )

        if statistics:
            _LOGGER.debug(
                "Importing %s hourly data points for %s on %s (starting sum: %s)",
                len(statistics),
                entity_id,
                base_date.date(),
                0.0,
            )
            async_import_statistics(self.hass, metadata, statistics)
