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

from .const import (
    ATTR_COOL_ENERGY,
    ATTR_ENERGY_TODAY,
    ATTR_HEAT_ENERGY,
    ATTR_TOTAL_ENERGY_TODAY,
    DOMAIN,
    TIMEOUT_SEC,
)
from .utils import calculate_energy_sum, parse_daikin_list

# Recorder statistics are only available when the recorder integration is loaded.
# We therefore import them lazily when we actually need to inject history.
StatisticData = None
StatisticMetaData = None
async_import_statistics = None
StatisticMeanType = None
statistics_during_period = None


def _ensure_recorder_statistics_api() -> bool:
    """Try to load HA recorder statistics import API at runtime."""
    global StatisticData, StatisticMetaData, async_import_statistics, StatisticMeanType, statistics_during_period

    if async_import_statistics is not None and StatisticData is not None:
        return True

    try:
        from homeassistant.components.recorder.models import (
            StatisticData as _StatisticData,
            StatisticMetaData as _StatisticMetaData,
        )
        from homeassistant.components.recorder.statistics import (
            async_import_statistics as _async_import_statistics,
            statistics_during_period as _statistics_during_period,
        )
        # In recent Home Assistant versions, StatisticMeanType is defined in
        # recorder models (not in recorder.const).
        from homeassistant.components.recorder.models import StatisticMeanType as _StatisticMeanType
    except ImportError as err:
        _LOGGER.debug("Recorder statistics API import failed: %s", err)
        return False

    StatisticData = _StatisticData
    StatisticMetaData = _StatisticMetaData
    async_import_statistics = _async_import_statistics
    statistics_during_period = _statistics_during_period
    StatisticMeanType = _StatisticMeanType
    return True

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
        if not _ensure_recorder_statistics_api():
            key = f"{DOMAIN}_recorder_stats_unavailable_logged"
            if not self.hass.data.get(key):
                _LOGGER.warning(
                    "Recorder statistics injection unavailable; energy history sync is disabled"
                )
                self.hass.data[key] = True
            return

        _LOGGER.info(
            "Syncing energy history for %s (days_ago=%s)",
            self.name,
            days_ago,
        )

        async with self._history_sync_lock:
            # Home Assistant uses "change" between day/hour boundaries.
            # For correct "today" values we also need yesterday's final sum
            # at the day boundary, so always import both when requested for
            # today.
            # General rule: to compute the first hour of day X, we also
            # need the final sum of the previous day (X+1, relative to the
            # Daikin "prev_1day_*" indexing).
            days_to_sync = [days_ago, days_ago + 1]
            days_to_sync = sorted(set(d for d in days_to_sync if d >= 0))

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

            def _normalize_24(values: list[int]) -> list[int]:
                values = values[:24]
                if len(values) < 24:
                    values += [0] * (24 - len(values))
                return values

            # Import from older to newer days so that rebasing using the
            # previously existing (or just-injected) `sum` boundary works.
            for target_days_ago in reversed(days_to_sync):
                # Get historical data arrays
                if target_days_ago == 0:
                    normal_data = self.device.values.get("curr_day_energy", [])
                    cool_data = self.device.values.get("curr_day_cool", [])
                    heat_data = self.device.values.get("curr_day_heat", [])
                elif target_days_ago == 1:
                    normal_data = self.device.values.get("prev_1day_energy", [])
                    cool_data = self.device.values.get("prev_1day_cool", [])
                    heat_data = self.device.values.get("prev_1day_heat", [])
                else:
                    # Some Daikin models (via get_day_power_ex) expose more
                    # previous-day keys.
                    normal_data = self.device.values.get(
                        f"prev_{target_days_ago}day_energy", []
                    )
                    cool_data = self.device.values.get(
                        f"prev_{target_days_ago}day_cool", []
                    )
                    heat_data = self.device.values.get(
                        f"prev_{target_days_ago}day_heat", []
                    )

                base_date = dt_util.start_of_local_day() - timedelta(
                    days=target_days_ago
                )

                normal_list = parse_daikin_list(normal_data)
                cool_list = parse_daikin_list(cool_data)
                heat_list = parse_daikin_list(heat_data)

                normal_available = bool(normal_list)
                cool_available = bool(cool_list)
                heat_available = bool(heat_list)

                # Fallback: if normal_data is empty but we have cool/heat, sum them up
                if not normal_available and (cool_list or heat_list):
                    _LOGGER.debug(
                        "Energy missing for %s, calculating from cool/heat",
                        self.name,
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
                    "Data for %s (days_ago=%s): normal=%s, cool=%s, heat=%s",
                    self.name,
                    target_days_ago,
                    normal_list,
                    cool_list,
                    heat_list,
                )

                # Map to actual entity IDs
                ent_reg = er.async_get(self.hass)

                for key, data in {
                    ATTR_ENERGY_TODAY: normal_list,
                    # When users configure the Energy dashboard with the smoothed
                    # "compressor energy" sensor, we still need to inject the
                    # historical counter values (based on Daikin totals) so the
                    # consolidated graphs can be corrected.
                    ATTR_TOTAL_ENERGY_TODAY: normal_list,
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
        # HA expects `sum` for total_increasing sensors to be monotone across
        # days (it represents an absolute counter), while `state` can reset.
        # To do that, we rebase our injected hourly `sum` on the last known
        # sum right before `base_date`.
        cumulative_delta = 0.0

        last_sum = 0.0
        if statistics_during_period is not None:
            # Query the last available absolute sum right before base_date.
            # This is needed so the injected `sum` stays monotone and
            # HA doesn't detect a "reset" on the day/hour boundary.
            last_stats = await self.hass.async_add_executor_job(
                statistics_during_period,
                self.hass,
                base_date - timedelta(hours=48),
                base_date,
                {entity_id},
                "hour",
                {"energy": UnitOfEnergy.KILO_WATT_HOUR},
                {"sum"},
            )
            if entity_id in last_stats and last_stats[entity_id]:
                last_sum = last_stats[entity_id][-1].get("sum") or 0.0

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
            cumulative_delta += delta
            cumulative_sum = last_sum + cumulative_delta
            
            start_time = base_date + timedelta(hours=hour)
            start_time_utc = dt_util.as_utc(start_time)
            
            if start_time_utc > dt_util.utcnow():
                break

            statistics.append(
                StatisticData(
                    start=start_time_utc,
                    # For total_increasing sensors:
                    # - `state` is the counter that may reset at midnight.
                    # - `sum` is the monotone absolute counter for deltas/change.
                    state=cumulative_delta,
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
                last_sum,
            )
            async_import_statistics(self.hass, metadata, statistics)
