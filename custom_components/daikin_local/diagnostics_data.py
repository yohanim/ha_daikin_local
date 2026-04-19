"""Implementation for integration diagnostics (loaded lazily — see ``diagnostics.py`` shim)."""

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
    KEY_IS_BRP069,
    KEY_MAC,
    KEY_SUPPORTS_ENERGY,
)

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


def _is_coordinator_runtime(obj: object) -> bool:
    """True if ``obj`` is our Daikin DataUpdateCoordinator (duck typing, no coordinator import)."""
    if obj is None:
        return False
    return all(
        hasattr(obj, attr)
        for attr in (
            "device",
            "update_interval",
            "last_update_success",
            "daily_polling_error_count",
        )
    )


def _coordinator_snapshot(runtime: object) -> dict[str, Any] | None:
    """Non-sensitive runtime state; ``runtime`` is DaikinCoordinator (duck typed)."""
    if not _is_coordinator_runtime(runtime):
        return None
    device = getattr(runtime, "device", None)
    if device is None:
        return None
    vals = getattr(device, "values", None) or {}
    ui = getattr(runtime, "update_interval", None)
    return {
        "update_interval_seconds": ui.total_seconds() if ui is not None else None,
        "last_update_success": getattr(runtime, "last_update_success", None),
        "consecutive_communication_failures": getattr(
            runtime, "consecutive_communication_failures", None
        ),
        "poll_cooldown_until_utc": getattr(runtime, "poll_cooldown_until_iso", None),
        "state_domain_interval_seconds": getattr(
            runtime, "state_domain_interval_seconds", None
        ),
        "energy_domain_interval_seconds": getattr(
            runtime, "energy_domain_interval_seconds", None
        ),
        "daily_polling_error_count": getattr(runtime, "daily_polling_error_count", None),
        "daily_state_polling_error_count": getattr(
            runtime, "daily_state_polling_error_count", None
        ),
        "daily_energy_polling_error_count": getattr(
            runtime, "daily_energy_polling_error_count", None
        ),
        "last_state_domain_response_sec": getattr(
            runtime, "last_state_domain_response_sec", None
        ),
        "last_energy_domain_response_sec": getattr(
            runtime, "last_energy_domain_response_sec", None
        ),
        "device_api": {
            "model": vals.get("model") if isinstance(vals, dict) else None,
            "firmware_ver": vals.get("ver") if isinstance(vals, dict) else None,
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
    snap = _coordinator_snapshot(runtime) if runtime is not None else None
    data["coordinator"] = snap

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
    if _is_coordinator_runtime(runtime):
        device_obj = getattr(runtime, "device", None)
        mac = getattr(device_obj, "mac", None) if device_obj is not None else None
        if isinstance(mac, str) and mac:
            expected = dr.format_mac(mac)
            base["device_registry"]["matches_runtime_mac"] = any(
                ctype == CONNECTION_NETWORK_MAC and cval == expected
                for ctype, cval in device.connections
            )

    return base
