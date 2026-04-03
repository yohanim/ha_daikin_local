"""Utility functions for Daikin."""
from __future__ import annotations

import logging

from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)


def device_object_id_prefix(device_name: str | None) -> str:
    """Stable slug prefix for entity object_ids from the appliance display name."""
    slug = slugify(device_name or "daikin")
    return slug if slug else "daikin"


def parse_daikin_list(raw_data: str | list[int]) -> list[int]:
    """Parse Daikin historical data (can be slash-separated string or list)."""
    if isinstance(raw_data, str):
        try:
            # Daikin uses "0/0/1/..." strings. We MUST keep zeros, otherwise
            # the hourly indexes shift and Home Assistant energy charts become
            # aggregated at the start of the day.
            return [int(v) for v in raw_data.split("/") if v != ""]
        except ValueError:
            _LOGGER.debug("Failed to parse Daikin historical data: %s", raw_data)
            return []
    if isinstance(raw_data, list):
        return raw_data
    return []


def calculate_energy_sum(data: list[int]) -> float:
    """Calculate energy sum in kWh from Daikin historical data (0.1 kWh units)."""
    if not data:
        return 0.0
    return sum(data) / 10.0
