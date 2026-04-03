"""Coordinator for Daikin integration."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import re

from pydaikin.daikin_base import Appliance
from pydaikin.daikin_brp069 import DaikinBRP069

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TIMEOUT, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.components import recorder
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_COOL_ENERGY,
    ATTR_ENERGY_TODAY,
    ATTR_HEAT_ENERGY,
    ATTR_TOTAL_ENERGY_TODAY,
    CONF_AUTO_HISTORY_SYNC,
    CONF_HISTORY_HOURS_TO_CORRECT,
    CONF_HISTORY_SKIP_EXTRA_HOURS,
    CONF_INSERT_MISSING,
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


def _recent_completed_hours_by_local_date(
    *,
    include_extra_hour: bool = False,
    skip_hours: int = 2,
    hours_to_correct: int = 3,
) -> dict[datetime.date, set[int]]:
    """Hour indices for completed local hours to (re)inject.

    We intentionally exclude:
    - the current hour (hour in progress)
    - the previous hour

    ``skip_hours``: number of most recent hours to skip counting backwards from
    "now" and including the current hour. Default 2 = skip current+previous hour.

    ``hours_to_correct``: number of hourly slots to correct immediately before the
    skipped range. Default 3 with skip_hours=2 targets hours back {2,3,4}.

    When ``include_extra_hour`` is True, we correct one additional hour (i.e.
    ``hours_to_correct + 1``). This is used after a history-sync failure so we
    can "catch up" one missed slot later.
    """
    skip_hours = max(1, int(skip_hours))
    hours_to_correct = max(1, int(hours_to_correct))

    now_local = dt_util.as_local(dt_util.utcnow())
    mapping: dict[datetime.date, set[int]] = {}
    extra = 1 if include_extra_hour else 0
    for i in range(hours_to_correct + extra):
        t = now_local - timedelta(hours=skip_hours + i)
        mapping.setdefault(t.date(), set()).add(t.hour)
    return mapping


def _history_skip_hours_from_options(options: dict) -> int:
    """Compute total hours to skip (includes current hour).

    New option: history_skip_extra_hours (extra hours besides current hour).
    Legacy option (kept for backward compat): history_skip_hours (included current hour).
    """
    if CONF_HISTORY_SKIP_EXTRA_HOURS in options:
        extra = int(options.get(CONF_HISTORY_SKIP_EXTRA_HOURS) or 0)
        return max(1, 1 + extra)

    # Backward compat: old meaning was total skip including current hour.
    legacy_total = int(options.get("history_skip_hours") or 2)
    return max(1, legacy_total)


def _lts_row_start_to_datetime(
    start: datetime | str | float | int | None,
) -> datetime | None:
    """Convert recorder LTS row ``start`` to a datetime.

    Newer Home Assistant returns Unix timestamps (float/int) for ``start``;
    older code paths used ISO strings or datetime objects.
    """
    if start is None:
        return None
    if isinstance(start, datetime):
        return start
    if isinstance(start, str):
        return dt_util.parse_datetime(start)
    if isinstance(start, (int, float)):
        return dt_util.utc_from_timestamp(float(start))
    return None


def _poll_timeout_sec(entry: ConfigEntry) -> int:
    """Polling interval (seconds): options override data when set."""
    return (
        entry.options.get(CONF_TIMEOUT)
        or entry.data.get(CONF_TIMEOUT)
        or TIMEOUT_SEC
    )


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
        timeout = _poll_timeout_sec(entry)
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
        # Local calendar hour for auto history: (year, month, day, hour).
        self._auto_history_local_slot: tuple[int, int, int, int] | None = None
        # True once LTS auto-sync succeeded for the current slot (new hour resets).
        self._auto_history_synced_ok: bool = False
        # Daily pydaikin error counters (per local day).
        self._error_stats_date: datetime.date | None = None
        self._daily_polling_error_count: int = 0
        self._daily_history_poll_error_count: int = 0
        self._consecutive_poll_failures = 0
        self._poll_cooldown_until: datetime | None = None
        # When Daikin communication fails at an hourly boundary, we may miss
        # one "recent completed hour" worth of statistics injection.
        # Keep one extra hour in the next history sync attempt.
        self._history_backfill_extra_hour = False
        # Prevent concurrent history imports into recorder statistics.
        self._history_sync_lock = asyncio.Lock()

    @property
    def daily_polling_error_count(self) -> int:
        """Errors during normal polling update_status() calls (force_refresh=False)."""
        return self._daily_polling_error_count

    @property
    def daily_history_poll_error_count(self) -> int:
        """Errors during polling when force_refresh=True for history corrections."""
        return self._daily_history_poll_error_count

    def _ensure_error_stats_date(self) -> None:
        """Reset per-day error counters when the local date changes."""
        today = dt_util.as_local(dt_util.utcnow()).date()
        if self._error_stats_date != today:
            self._error_stats_date = today
            self._daily_polling_error_count = 0
            self._daily_history_poll_error_count = 0

    async def _async_maybe_auto_history_sync(self) -> None:
        """After a successful poll, optionally correct LTS (same schedule as polling).

        At most one successful sync per local clock hour; retries on later polls if needed.
        Failures here do not fail the coordinator update (sensor data already refreshed).
        """
        if not self.config_entry.options.get(CONF_AUTO_HISTORY_SYNC, False):
            # When auto history is disabled, forget any previous slot state.
            self._auto_history_local_slot = None
            self._auto_history_synced_ok = False
            return

        # If we've already synced successfully for this local hour, do nothing.
        if self._auto_history_synced_ok:
            return

        try:
            await self.async_sync_history(
                days_ago=0,
                insert_missing=None,
            )
        except Exception as err:
            # Widen next run's window to backfill one extra hour.
            self._history_backfill_extra_hour = True
            _LOGGER.warning(
                "[history] Auto history sync failed for %s: %s "
                "(will retry on next poll)",
                self.name,
                err,
            )
            return

        # Mark this local hour as successfully synced.
        self._auto_history_synced_ok = True

    async def _async_update_data(self) -> DaikinData:
        """Update data."""
        timeout = _poll_timeout_sec(self.config_entry)
        now = dt_util.utcnow()

        # Decide whether this poll should force-refresh dynamic resources (including
        # extended energy data) to feed the upcoming auto history correction run.
        auto_enabled = self.config_entry.options.get(CONF_AUTO_HISTORY_SYNC, False)
        force_refresh = False
        if auto_enabled:
            # Also ensure per-day error counters are aligned with current local date.
            self._ensure_error_stats_date()
            now_local = dt_util.as_local(now)
            slot = (now_local.year, now_local.month, now_local.day, now_local.hour)
            if self._auto_history_local_slot != slot:
                # New local hour: reset sync state so the next successful history run
                # will mark this slot as complete.
                self._auto_history_local_slot = slot
                self._auto_history_synced_ok = False
            # While we have not yet synced LTS for this slot, ask pydaikin (when
            # supported) to bypass its TTL cache for dynamic resources so we see the
            # latest extended arrays.
            force_refresh = not self._auto_history_synced_ok

        # If we've recently hit a transient communication error, avoid hammering
        # the device (and spamming logs). Return cached data during cooldown.
        if self._poll_cooldown_until is not None and now < self._poll_cooldown_until:
            if self.data is not None:
                _LOGGER.debug(
                    "[poll] Skipping update for %s during cooldown until %s",
                    self.name,
                    self._poll_cooldown_until,
                )
                return self.data

        try:
            async with asyncio.timeout(timeout):
                if force_refresh and isinstance(self.device, DaikinBRP069):
                    _LOGGER.debug(
                        "[poll] Updating %s via pydaikin update_status(force_refresh=True)",
                        self.name,
                    )
                    await self.device.update_status(force_refresh=True)
                else:
                    _LOGGER.debug(
                        "[poll] Updating %s via pydaikin update_status()", self.name
                    )
                    await self.device.update_status()
        except Exception as err:
            # Track per-day error counters by poll type.
            self._ensure_error_stats_date()
            if force_refresh:
                self._daily_history_poll_error_count += 1
            else:
                self._daily_polling_error_count += 1
            self._consecutive_poll_failures += 1
            # No explicit retry is scheduled here: polling already runs frequently.

            # For frequent polling, treat transient failures as "best effort":
            # - during the first few consecutive failures, return cached data
            #   and log at debug/info instead of raising UpdateFailed (which
            #   triggers the noisy "Error fetching X data" log).
            # - if failures persist, raise UpdateFailed to surface the issue.
            cooldown_s = min(300, 30 * self._consecutive_poll_failures)
            self._poll_cooldown_until = now + timedelta(seconds=cooldown_s)

            if self.data is not None and self._consecutive_poll_failures <= 3:
                _LOGGER.warning(
                    "[poll] Transient communication error for %s (%s); "
                    "serving cached data, cooldown=%ss (failure #%s, force_refresh=%s)",
                    self.name,
                    err,
                    cooldown_s,
                    self._consecutive_poll_failures,
                    force_refresh,
                )
                return self.data

            # Escalate: persistent comm failures.
            raise UpdateFailed(
                f"[poll] Error communicating with Daikin {self.name}: {err}"
            ) from err

        # Energy smoothing logic
        self._consecutive_poll_failures = 0
        self._poll_cooldown_until = None
        current_power = getattr(self.device, "current_total_power_consumption", 0) or 0
        
        # Use property for smoothing if available, fallback to history sum
        real_total_energy_today = (
            getattr(self.device, "today_total_energy_consumption", 0) or 0
        )
        # Calculate base energy from history arrays for cool/heat
        today_cool = self._get_sum_from_daikin_key("curr_day_cool")
        today_heat = self._get_sum_from_daikin_key("curr_day_heat")

        # Option: exactness over smoothing.
        # `total_energy_today` is derived from Daikin's own counter, so to
        # keep consistent distribution vs. cool/heat sensors we don't
        # integrate power between polls here.
        self._integrated_total_energy = 0.0
        self._last_total_energy_today = real_total_energy_today

        self._last_update_time = now
        self._last_power = current_power

        data = DaikinData(
            appliance=self.device,
            calculated_total_energy_today=real_total_energy_today,
            today_energy=real_total_energy_today,
            today_cool_energy=today_cool,
            today_heat_energy=today_heat,
        )
        await self._async_maybe_auto_history_sync()
        return data

    def _get_sum_from_daikin_key(self, daikin_key: str) -> float:
        """Calculate sum from a Daikin historical data key."""
        raw_data = self.device.values.get(daikin_key, [])
        data = parse_daikin_list(raw_data)
        return calculate_energy_sum(data)

    async def async_sync_history(
        self,
        days_ago: int = 0,
        target_entity_id: str | None = None,
        *,
        insert_missing: bool | None = None,
    ) -> None:
        """Sync energy history with Daikin historical data.

        Only sensors owned by this config entry are ever passed to the recorder.
        Optional ``target_entity_id`` limits the run to a single sensor entity
        (must still belong to this device entry).

        ``insert_missing``: None = use integration option ``insert_missing``;
        False = only update hours that already have LTS rows; True = may insert
        missing hours (risk of recorder UNIQUE conflicts).

        """
        if insert_missing is None:
            insert_missing = self.config_entry.options.get(CONF_INSERT_MISSING, False)
        if not _ensure_recorder_statistics_api():
            key = f"{DOMAIN}_recorder_stats_unavailable_logged"
            if not self.hass.data.get(key):
                _LOGGER.warning(
                    "Recorder statistics injection unavailable; energy history sync is disabled"
                )
                self.hass.data[key] = True
            return

        _LOGGER.info(
            "[history] Syncing energy history for %s (days_ago=%s)",
            self.name,
            days_ago,
        )

        async with self._history_sync_lock:
            skip_hours = _history_skip_hours_from_options(self.config_entry.options)
            hours_to_correct = int(
                self.config_entry.options.get(CONF_HISTORY_HOURS_TO_CORRECT, 3)
            )
            # Inject only the last 3 completed local hours (skip current + previous).
            # This avoids trying to correct hours/whole days that the recorder has
            # not compiled yet (common right after local midnight).
            recent_hours_by_date = _recent_completed_hours_by_local_date(
                include_extra_hour=self._history_backfill_extra_hour,
                skip_hours=skip_hours,
                hours_to_correct=hours_to_correct,
            )
            today_start = dt_util.start_of_local_day()
            today_date = today_start.date()
            yesterday_date = (today_start - timedelta(days=1)).date()

            days_to_sync: list[int] = []
            did_import_any = False
            if today_date in recent_hours_by_date:
                days_to_sync.append(0)
            if yesterday_date in recent_hours_by_date:
                days_to_sync.append(1)
            if not days_to_sync:
                # Fallback to the previous behavior if, for some reason,
                # we couldn't compute the target day offsets.
                days_to_sync = [0] if days_ago == 0 else [0, 1]

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

                target_hours = recent_hours_by_date.get(base_date.date())
                if not target_hours:
                    continue

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

                    if target_entity_id and entity_id != target_entity_id:
                        continue

                    _LOGGER.debug("Found entity_id %s for %s", entity_id, key)
                    did_import_any = (
                        await self._import_data_to_stats(
                            entity_id,
                            data,
                            base_date,
                            insert_missing=insert_missing,
                            target_hours=target_hours,
                        )
                        or did_import_any
                    )

            if did_import_any:
                self._history_backfill_extra_hour = False

    async def async_sync_total_history(
        self,
        days_ago: int = 0,
        target_entity_id: str | None = None,
        *,
        insert_missing: bool | None = None,
    ) -> None:
        """Sync *only* the smoothed total/compressor energy history.

        This is meant as a targeted correction service for the total sensor.
        It should be used rarely because it can influence Energy dashboard
        calculations depending on which entities are configured.

        ``insert_missing``: None = use integration option (same as sync_history).
        """
        if insert_missing is None:
            insert_missing = self.config_entry.options.get(CONF_INSERT_MISSING, False)
        if not _ensure_recorder_statistics_api():
            key = f"{DOMAIN}_recorder_stats_unavailable_logged"
            if not self.hass.data.get(key):
                _LOGGER.warning(
                    "Recorder statistics injection unavailable; total energy history sync is disabled"
                )
                self.hass.data[key] = True
            return

        _LOGGER.info(
            "Syncing total energy history for %s (days_ago=%s) - use with care",
            self.name,
            days_ago,
        )

        async with self._history_sync_lock:
            skip_hours = _history_skip_hours_from_options(self.config_entry.options)
            hours_to_correct = int(
                self.config_entry.options.get(CONF_HISTORY_HOURS_TO_CORRECT, 3)
            )
            # Inject only the last 3 completed local hours (skip current + previous).
            recent_hours_by_date = _recent_completed_hours_by_local_date(
                include_extra_hour=self._history_backfill_extra_hour,
                skip_hours=skip_hours,
                hours_to_correct=hours_to_correct,
            )
            today_start = dt_util.start_of_local_day()
            today_date = today_start.date()
            yesterday_date = (today_start - timedelta(days=1)).date()

            days_to_sync: list[int] = []
            did_import_any = False
            if today_date in recent_hours_by_date:
                days_to_sync.append(0)
            if yesterday_date in recent_hours_by_date:
                days_to_sync.append(1)
            if not days_to_sync:
                days_to_sync = [0] if days_ago == 0 else [0, 1]

            def _normalize_24(values: list[int]) -> list[int]:
                values = values[:24]
                if len(values) < 24:
                    values += [0] * (24 - len(values))
                return values

            def _aggregate_all_devices_cool_heat(
                target_days_ago: int,
            ) -> list[int] | None:
                """Build a global total series by summing all devices cool+heat."""
                aggregate = [0] * 24
                found = False

                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    runtime = getattr(entry, "runtime_data", None)
                    if runtime is None or not hasattr(runtime, "device"):
                        continue
                    values = runtime.device.values
                    if target_days_ago == 0:
                        cool_raw = values.get("curr_day_cool", [])
                        heat_raw = values.get("curr_day_heat", [])
                    elif target_days_ago == 1:
                        cool_raw = values.get("prev_1day_cool", [])
                        heat_raw = values.get("prev_1day_heat", [])
                    else:
                        cool_raw = values.get(f"prev_{target_days_ago}day_cool", [])
                        heat_raw = values.get(f"prev_{target_days_ago}day_heat", [])

                    cool_list = parse_daikin_list(cool_raw)
                    heat_list = parse_daikin_list(heat_raw)
                    if not cool_list and not heat_list:
                        continue

                    cool_list = _normalize_24(cool_list)
                    heat_list = _normalize_24(heat_list)
                    aggregate = [
                        agg + c + h for agg, c, h in zip(aggregate, cool_list, heat_list)
                    ]
                    found = True

                return aggregate if found else None

            def _candidate_keys_for_day(target_days_ago: int) -> list[str]:
                values = self.device.values
                if target_days_ago == 0:
                    day_markers = ("curr_day", "today", "current_day", "day0")
                else:
                    day_markers = (
                        f"prev_{target_days_ago}day",
                        f"prev{target_days_ago}day",
                        f"previous_{target_days_ago}day",
                        f"day-{target_days_ago}",
                        "prev_day",
                        "yesterday",
                    )

                preferred: list[str] = []
                fallback: list[str] = []
                relaxed: list[str] = []
                for key in values:
                    key_l = key.lower()
                    # Total correction must not use segmented cool/heat streams.
                    if "cool" in key_l or "heat" in key_l:
                        continue

                    # Keep only active keys which currently expose usable
                    # history data.
                    parsed = parse_daikin_list(values.get(key, []))
                    if not parsed:
                        continue

                    # Prefer explicit "total/global" style keys.
                    is_totalish = (
                        "total_global" in key_l
                        or "global_total" in key_l
                        or "tot_global" in key_l
                        or re.search(r"\btotal\b", key_l)
                    )

                    if not is_totalish:
                        # Still accept active day energy keys if they are
                        # neither cool nor heat (some firmwares only expose
                        # aggregate data under generic energy keys).
                        if "energy" in key_l and any(
                            marker in key_l for marker in day_markers
                        ):
                            fallback.append(key)
                        continue

                    has_day_marker = any(marker in key_l for marker in day_markers)
                    if has_day_marker:
                        preferred.append(key)
                    # Relaxed fallback: keep total-ish active keys even without
                    # recognized day markers (some pydaikin firmwares use
                    # inconsistent naming).
                    elif "energy" in key_l or "global" in key_l or "total" in key_l:
                        relaxed.append(key)

                if not preferred and relaxed:
                    fallback.extend(relaxed)

                # Keep deterministic order for debugging/reproducibility.
                preferred.sort()
                fallback.sort()
                return preferred + fallback

            for target_days_ago in reversed(days_to_sync):
                total_keys = _candidate_keys_for_day(target_days_ago)

                selected_key: str | None = None
                total_data = []
                for key in total_keys:
                    raw_value = self.device.values.get(key, [])
                    parsed = parse_daikin_list(raw_value)
                    if parsed:
                        selected_key = key
                        total_data = parsed
                        break

                base_date = dt_util.start_of_local_day() - timedelta(
                    days=target_days_ago
                )

                target_hours = recent_hours_by_date.get(base_date.date())
                if not target_hours:
                    continue

                total_list = parse_daikin_list(total_data)
                if not total_list:
                    # Fallback requested: if pydaikin does not expose an
                    # aggregate total series for this day, rebuild it from
                    # ALL devices cool+heat hourly series.
                    all_devices_total = _aggregate_all_devices_cool_heat(target_days_ago)
                    if all_devices_total is not None:
                        total_list = all_devices_total
                        selected_key = "fallback:all_devices_cool+heat"

                if not total_list:
                    active_totalish_keys = sorted(
                        key
                        for key, raw in self.device.values.items()
                        if ("total" in key.lower() or "global" in key.lower())
                        and parse_daikin_list(raw)
                    )
                    diagnostic_keys = []
                    for key, raw in self.device.values.items():
                        key_l = key.lower()
                        if not (
                            "total" in key_l
                            or "global" in key_l
                            or "energy" in key_l
                            or "curr_day" in key_l
                            or "prev_" in key_l
                        ):
                            continue
                        parsed = parse_daikin_list(raw)
                        diagnostic_keys.append(
                            f"{key}<{type(raw).__name__}> parsed_len={len(parsed)}"
                        )

                    _LOGGER.debug(
                        "No total history key available for %s (days_ago=%s); "
                        "skipping total history correction for this day. "
                        "Candidates=%s active_totalish=%s diagnostic=%s",
                        self.name,
                        target_days_ago,
                        total_keys,
                        active_totalish_keys,
                        diagnostic_keys,
                    )
                    continue

                _LOGGER.debug(
                    "Using %s for total history sync on %s (days_ago=%s)",
                    selected_key,
                    self.name,
                    target_days_ago,
                )
                total_list = _normalize_24(total_list)

                ent_reg = er.async_get(self.hass)
                unique_id = f"{self.device.mac}-{ATTR_TOTAL_ENERGY_TODAY}"
                entity_id = ent_reg.async_get_entity_id(
                    "sensor", DOMAIN, unique_id
                )
                if not entity_id:
                    _LOGGER.warning(
                        "Total sensor entity not found for %s (unique_id: %s).",
                        self.name,
                        unique_id,
                    )
                    continue

                if target_entity_id and entity_id != target_entity_id:
                    continue

                did_import_any = (
                    await self._import_data_to_stats(
                        entity_id,
                        total_list,
                        base_date,
                        insert_missing=insert_missing,
                        target_hours=target_hours,
                    )
                    or did_import_any
                )

            if did_import_any:
                self._history_backfill_extra_hour = False

    async def _import_data_to_stats(
        self,
        entity_id: str,
        data: list[int],
        base_date: datetime,
        *,
        insert_missing: bool = False,
        target_hours: set[int] | None = None,
    ) -> bool:
        """Import a list of hourly energy values into HA statistics.

        For HA energy/consumption aggregation (`state_class=total_increasing`),
        each statistic entry must represent the counter value at the end of
        the hour and include `last_reset` (we assume the counter resets at
        local midnight for the "today" entities).

        Imports are refused unless the entity is registered and tied to *this*
        config entry — so a bug or wrong ID cannot target another integration.

        When ``insert_missing`` is False (default), hours without an existing
        long-term statistics row are skipped so the recorder's hourly compiler
        does not hit UNIQUE (metadata_id, start_ts) conflicts with our INSERTs.
        """
        ent_reg = er.async_get(self.hass)
        reg_entry = ent_reg.async_get(entity_id)
        if reg_entry is None:
            _LOGGER.warning(
                "Statistics import skipped: %s is not in the entity registry",
                entity_id,
            )
            return False
        if reg_entry.config_entry_id != self.config_entry.entry_id:
            _LOGGER.error(
                "Refusing statistics import for %s: not owned by this device entry "
                "(expected config_entry_id=%s, got %s)",
                entity_id,
                self.config_entry.entry_id,
                reg_entry.config_entry_id,
            )
            return False
        if reg_entry.platform != DOMAIN:
            _LOGGER.error(
                "Refusing statistics import for %s: wrong platform (%s)",
                entity_id,
                reg_entry.platform,
            )
            return False

        def _hour_index_local_day(row_start: datetime, day_start: datetime) -> int | None:
            """Hour index 0..23 for row within the local calendar day of day_start."""
            row_local = dt_util.as_local(row_start)
            base_local = dt_util.as_local(day_start)
            if row_local.date() != base_local.date():
                return None
            delta = row_local - base_local
            h = int(delta.total_seconds() // 3600)
            if 0 <= h < 24:
                return h
            return None

        # Hours that already have an LTS row (avoid competing INSERTs with recorder).
        existing_hours: set[int] = set()
        if statistics_during_period is not None and not insert_missing:
            day_end = base_date + timedelta(days=1)
            day_rows = await recorder.get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                dt_util.as_utc(base_date),
                dt_util.as_utc(day_end),
                {entity_id},
                "hour",
                {"energy": UnitOfEnergy.KILO_WATT_HOUR},
                {"sum"},
            )
            if entity_id in day_rows:
                for row in day_rows[entity_id]:
                    start = _lts_row_start_to_datetime(row.get("start"))
                    if start is None:
                        continue
                    hi = _hour_index_local_day(start, base_date)
                    if hi is not None:
                        existing_hours.add(hi)

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
            # Use an end timestamp strictly before `base_date` to avoid
            # reusing a 00:00 sample from the same day on repeated syncs.
            end_before_base = base_date - timedelta(microseconds=1)
            last_stats = await recorder.get_instance(
                self.hass
            ).async_add_executor_job(
                statistics_during_period,
                self.hass,
                base_date - timedelta(hours=48),
                end_before_base,
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
        skipped_no_row = 0

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

            if target_hours is not None and hour not in target_hours:
                continue

            if not insert_missing and hour not in existing_hours:
                skipped_no_row += 1
                continue

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

        did_import = False

        if statistics:
            _LOGGER.debug(
                "Importing %s hourly data points for %s on %s (starting sum: %s, "
                "insert_missing=%s, skipped_hours_without_row=%s)",
                len(statistics),
                entity_id,
                base_date.date(),
                last_sum,
                insert_missing,
                skipped_no_row,
            )
            async_import_statistics(self.hass, metadata, statistics)
            did_import = True
        elif not insert_missing and not statistics and skipped_no_row:
            _LOGGER.warning(
                "Statistics import for %s on %s produced no updates (no existing "
                "hourly LTS rows for this day). Wait for the recorder to compile the "
                "day, then retry; or use service parameter insert_missing=true to "
                "insert missing hours (may rarely log duplicate-statistics warnings).",
                entity_id,
                base_date.date(),
            )

        return did_import
