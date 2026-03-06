"""Coordinator for Daikin integration."""

from datetime import timedelta
import logging

from pydaikin.daikin_base import Appliance

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN, 
    TIMEOUT_SEC, 
    SWING_WINDNICE,
    CONF_CLOUD_SCAN_INTERVAL_DAY,
    CONF_CLOUD_SCAN_INTERVAL_NIGHT,
    CONF_CLOUD_DAY_START,
    CONF_CLOUD_DAY_END,
    DEFAULT_CLOUD_SCAN_INTERVAL_DAY,
    DEFAULT_CLOUD_SCAN_INTERVAL_NIGHT,
    DEFAULT_CLOUD_DAY_START,
    DEFAULT_CLOUD_DAY_END
)
from .cloud_api import DaikinCloudAPI

_LOGGER = logging.getLogger(__name__)

type DaikinConfigEntry = ConfigEntry[DaikinCoordinator]


class DaikinCoordinator(DataUpdateCoordinator[None]):
    """Class to manage fetching Daikin data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: DaikinConfigEntry,
        device: Appliance,
        cloud_api: DaikinCloudAPI | None = None,
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
        self.cloud_api = cloud_api
        self.wind_nice_active = False
        self._last_cloud_update = 0

    def _get_cloud_interval(self) -> int:
        """Calculate current cloud interval in seconds."""
        import datetime
        now = datetime.datetime.now().time()
        
        day_start = self.config_entry.options.get(CONF_CLOUD_DAY_START, DEFAULT_CLOUD_DAY_START)
        day_end = self.config_entry.options.get(CONF_CLOUD_DAY_END, DEFAULT_CLOUD_DAY_END)
        
        try:
            start_t = datetime.datetime.strptime(day_start, "%H:%M").time()
            end_t = datetime.datetime.strptime(day_end, "%H:%M").time()
            
            # Normal case: 07:00 -> 23:00
            if start_t < end_t:
                is_day = start_t <= now <= end_t
            else: # Night case: 22:00 -> 06:00
                is_day = now >= start_t or now <= end_t
                
            interval_min = self.config_entry.options.get(
                CONF_CLOUD_SCAN_INTERVAL_DAY if is_day else CONF_CLOUD_SCAN_INTERVAL_NIGHT,
                DEFAULT_CLOUD_SCAN_INTERVAL_DAY if is_day else DEFAULT_CLOUD_SCAN_INTERVAL_NIGHT
            )
            return interval_min * 60
        except Exception:
            return DEFAULT_CLOUD_SCAN_INTERVAL_DAY * 60

    async def _async_update_data(self) -> None:
        """Update data via local API and optionally cloud API."""
        await self.device.update_status()

        # Update cloud data only if cloud_api is configured
        # Dynamic interval based on time of day
        import time
        now = time.time()
        interval = self._get_cloud_interval()
        
        if self.cloud_api and (now - self._last_cloud_update >= interval or self._last_cloud_update == 0):
            _LOGGER.debug("Polling Daikin Cloud (interval: %ds) for device %s", interval, self.cloud_api.device_id)
            status = await self.cloud_api.async_get_device_status()
            if status:
                self._last_cloud_update = now
                try:
                    # Parse the windNice value from the complex JSON structure
                    for mp in status.get("managementPoints", []):
                        if mp.get("embeddedId") == "climateControl":
                            for char in mp.get("characteristics", []):
                                if char.get("name") == "windNice":
                                    self.wind_nice_active = char.get("value") == "on"
                except Exception as err:
                    _LOGGER.error("Error parsing cloud status: %s", err)
