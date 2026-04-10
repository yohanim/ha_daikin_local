"""Diagnostics downloads for config entries and devices (Home Assistant UI)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceEntry,
)

from .const import (
    CONF_ENERGY_GROUP_ID,
    CONF_HOST,
    DOMAIN,
    KEY_IS_BRP069,
    KEY_MAC,
    KEY_SUPPORTS_ENERGY,
)
from .coordinator import DaikinCoordinator

# https://developers.home-assistant.io/docs/core/integration_diagnostics/
REDACT_KEYS = frozenset({CONF_HOST, KEY_MAC, CONF_ENERGY_GROUP_ID})


def _integration_version() -> str:
    try:
        manifest = Path(__file__).resolve().parent / "manifest.json"
        with manifest.open(encoding="utf-8") as f:
            data = json.load(f)
        return str(data.get("version", "unknown"))
    except (OSError, json.JSONDecodeError, TypeError):
        return "unknown"


def _coordinator_dict(coordinator: DaikinCoordinator) -> dict[str, Any]:
    """Non-sensitive runtime state for support tickets."""
    vals = coordinator.device.values
    return {
        "update_interval_seconds": coordinator.update_interval.total_seconds()
        if coordinator.update_interval
        else None,
        "last_update_success": coordinator.last_update_success,
        "consecutive_communication_failures": coordinator.consecutive_communication_failures,
        "poll_cooldown_until_utc": coordinator.poll_cooldown_until_iso,
        "state_domain_interval_seconds": coordinator.state_domain_interval_seconds,
        "energy_domain_interval_seconds": coordinator.energy_domain_interval_seconds,
        "daily_polling_error_count": coordinator.daily_polling_error_count,
        "daily_state_polling_error_count": coordinator.daily_state_polling_error_count,
        "daily_energy_polling_error_count": coordinator.daily_energy_polling_error_count,
        "device_api": {
            "model": vals.get("model"),
            "firmware_ver": vals.get("ver"),
        },
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry (Settings → integration → Download diagnostics)."""
    data: dict[str, Any] = {
        "integration_version": _integration_version(),
        "config_entry": {
            "entry_id": entry.entry_id,
            "domain": entry.domain,
            "title": entry.title,
            "version": entry.version,
            "minor_version": getattr(entry, "minor_version", 1),
            "state": entry.state,
            "reason": getattr(entry, "reason", None),
        },
        "data": async_redact_data(dict(entry.data), REDACT_KEYS),
        "options": async_redact_data(dict(entry.options), REDACT_KEYS),
        "flags": {
            KEY_IS_BRP069: entry.data.get(KEY_IS_BRP069),
            KEY_SUPPORTS_ENERGY: entry.data.get(KEY_SUPPORTS_ENERGY),
        },
    }

    runtime = getattr(entry, "runtime_data", None)
    if isinstance(runtime, DaikinCoordinator):
        data["coordinator"] = _coordinator_dict(runtime)
    else:
        data["coordinator"] = None

    return data


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a single device (Device page → Download diagnostics)."""
    if entry.entry_id not in device.config_entries:
        return {
            "error": "This device is not linked to the selected config entry.",
        }

    base = await async_get_config_entry_diagnostics(hass, entry)
    base["device_registry"] = {
        "id": device.id,
        "name": device.name,
        "model": device.model,
        "hw_version": device.hw_version,
        "sw_version": device.sw_version,
        "manufacturer": device.manufacturer,
        "via_device_id": device.via_device_id,
        "connections": [list(c) for c in device.connections],
        "identifiers": [list(i) for i in device.identifiers],
    }

    runtime = getattr(entry, "runtime_data", None)
    if isinstance(runtime, DaikinCoordinator):
        expected = dr.format_mac(runtime.device.mac)
        base["device_registry"]["matches_runtime_mac"] = any(
            ctype == CONNECTION_NETWORK_MAC and cval == expected
            for ctype, cval in device.connections
        )

    return base
