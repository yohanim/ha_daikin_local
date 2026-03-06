"""Cloud API for Daikin Onecta."""

import logging
from typing import Any

from aiohttp import ClientSession

from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import get_url
from homeassistant.helpers import config_entry_oauth2_helper

from .const import DAIKIN_ONECTA_API_URL

_LOGGER = logging.getLogger(__name__)

class DaikinCloudAPI:
    """Handle communication with Daikin Onecta Cloud API."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: config_entry_oauth2_helper.OAuth2Session,
        device_id: str,
    ) -> None:
        """Initialize the Cloud API."""
        self.hass = hass
        self.session = session
        self.device_id = device_id

    async def async_set_wind_nice(self, value: bool) -> bool:
        """Set windNice (Comfort Airflow) characteristic."""
        url = f"{DAIKIN_ONECTA_API_URL}/devices/{self.device_id}/management-points/climateControl/characteristics/windNice"
        payload = {"value": "on" if value else "off"}

        try:
            resp = await self.session.async_request("PATCH", url, json=payload)
            if resp.status == 204:
                _LOGGER.debug("Successfully set windNice to %s", value)
                return True
            
            body = await resp.text()
            _LOGGER.error("Failed to set windNice: %s - %s", resp.status, body)
        except Exception as err:
            _LOGGER.exception("Error while calling Cloud API: %s", err)
        
        return False

    async def async_get_device_status(self) -> dict[str, Any] | None:
        """Get current status of the device from Cloud."""
        url = f"{DAIKIN_ONECTA_API_URL}/devices/{self.device_id}"
        try:
            resp = await self.session.async_request("GET", url)
            if resp.status == 200:
                return await resp.json()
            
            body = await resp.text()
            _LOGGER.error("Failed to get device status: %s - %s", resp.status, body)
        except Exception as err:
            _LOGGER.exception("Error while calling Cloud API: %s", err)
        
        return None
