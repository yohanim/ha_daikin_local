"""Services for Daikin integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_TOTAL_ENERGY_TODAY,
    CONF_ENERGY_GROUP_ID,
    CONF_ENERGY_GROUP_TOTAL_HISTORY_MASTER,
    CONF_HISTORY_HOURS_TO_CORRECT,
    CONF_HISTORY_SKIP_EXTRA_HOURS,
    CONF_INSERT_MISSING,
    DOMAIN,
)
from .pure import (
    ATTR_DAYS_AGO,
    ATTR_ENTITY_ID,
    build_service_schema,
)
from .pure import (
    group_has_master as _group_has_master,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_SYNC_HISTORY = "sync_history"
SERVICE_SYNC_TOTAL_HISTORY = "sync_total_history"
SERVICE_SCHEMA = build_service_schema(cv.boolean)

SERVICE_SET_DEMAND_CONTROL = "set_demand_control"
ATTR_EN_DEMAND = "en_demand"
ATTR_MAX_POW = "max_pow"
ATTR_MODE = "mode"
SET_DEMAND_CONTROL_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): vol.Coerce(str),
        vol.Optional(ATTR_EN_DEMAND): cv.boolean,
        vol.Optional(ATTR_MAX_POW): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional(ATTR_MODE): vol.All(vol.Coerce(int), vol.Range(min=0, max=2)),
    }
)

SERVICE_SET_BRP084_OPTIONS = "set_brp084_options"
ATTR_VERTICAL_VANE = "vertical_vane"
ATTR_DRY_COMFORT_OFFSET = "dry_comfort_offset"
SET_BRP084_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTITY_ID): vol.Coerce(str),
        vol.Optional(ATTR_VERTICAL_VANE): vol.In(["off", "down", "swing"]),
        vol.Optional(ATTR_DRY_COMFORT_OFFSET): vol.Coerce(float),
    }
)


def _loaded_config_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Config entries for this integration that have a running coordinator."""
    return [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if getattr(e, "runtime_data", None)
    ]


def _entries_for_entity_target(
    hass: HomeAssistant, target_entity_id: str | None
) -> list[ConfigEntry]:
    """Entries to run a service on.

    Without ``entity_id``: all loaded entries. With ``entity_id``: only the
    config entry that owns that entity. The same ``target_entity_id`` is still
    passed into ``async_sync_history`` / ``async_sync_total_history`` so the
    coordinator can limit which sensor entity IDs are corrected inside that entry.
    """
    loaded = _loaded_config_entries(hass)
    if not target_entity_id:
        return loaded
    ent_reg = er.async_get(hass)
    reg = ent_reg.async_get(target_entity_id)
    if reg is None:
        _LOGGER.warning(
            "[service] Unknown %s %s; skipping",
            ATTR_ENTITY_ID,
            target_entity_id,
        )
        return []
    if not reg.config_entry_id:
        _LOGGER.warning(
            "[service] %s %s is not tied to a config entry; skipping",
            ATTR_ENTITY_ID,
            target_entity_id,
        )
        return []
    entry = hass.config_entries.async_get_entry(reg.config_entry_id)
    if entry is None or entry.domain != DOMAIN:
        _LOGGER.warning(
            "[service] %s %s is not owned by %s; skipping",
            ATTR_ENTITY_ID,
            target_entity_id,
            DOMAIN,
        )
        return []
    if not getattr(entry, "runtime_data", None):
        _LOGGER.warning(
            "[service] Config entry for %s is not loaded; skipping",
            target_entity_id,
        )
        return []
    return [entry]


def _total_energy_sensor_enabled(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """True if the compressor total-energy-today sensor exists and is enabled."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None or not hasattr(runtime, "device"):
        return False
    mac = runtime.device.mac
    unique_id = f"{mac}-{ATTR_TOTAL_ENERGY_TODAY}"
    ent_reg = er.async_get(hass)
    eid = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
    if not eid:
        return False
    reg = ent_reg.async_get(eid)
    if reg is None:
        return False
    return reg.disabled_by is None


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for the Daikin integration."""

    async def async_sync_history(call: ServiceCall) -> None:
        """Sync history for all or specific Daikin devices."""
        days_ago = call.data.get(ATTR_DAYS_AGO, 0)
        target_entity_id = call.data.get(ATTR_ENTITY_ID)
        insert_missing = call.data.get(CONF_INSERT_MISSING, None)
        history_skip_extra_hours = call.data.get(CONF_HISTORY_SKIP_EXTRA_HOURS, None)
        history_hours_to_correct = call.data.get(CONF_HISTORY_HOURS_TO_CORRECT, None)

        for entry in _entries_for_entity_target(hass, target_entity_id):
            coordinator = entry.runtime_data
            await coordinator.async_sync_history(
                days_ago=days_ago,
                target_entity_id=target_entity_id,
                insert_missing=insert_missing,
                history_skip_extra_hours=history_skip_extra_hours,
                history_hours_to_correct=history_hours_to_correct,
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_HISTORY,
        async_sync_history,
        schema=SERVICE_SCHEMA,
    )

    async def async_sync_total_history(call: ServiceCall) -> None:
        """Sync only the Daikin total/compressor energy history."""
        days_ago = call.data.get(ATTR_DAYS_AGO, 0)
        target_entity_id = call.data.get(ATTR_ENTITY_ID)
        insert_missing = call.data.get(CONF_INSERT_MISSING, None)
        history_skip_extra_hours = call.data.get(CONF_HISTORY_SKIP_EXTRA_HOURS, None)
        history_hours_to_correct = call.data.get(CONF_HISTORY_HOURS_TO_CORRECT, None)

        if target_entity_id:
            entries = _entries_for_entity_target(hass, target_entity_id)
        else:
            entries = _loaded_config_entries(hass)

        if target_entity_id:
            for entry in entries:
                coordinator = entry.runtime_data
                await coordinator.async_sync_total_history(
                    days_ago=days_ago,
                    target_entity_id=target_entity_id,
                    insert_missing=insert_missing,
                    history_skip_extra_hours=history_skip_extra_hours,
                    history_hours_to_correct=history_hours_to_correct,
                )
            return

        for entry in entries:
            group = (entry.options.get(CONF_ENERGY_GROUP_ID) or "").strip()
            is_master = bool(
                entry.options.get(CONF_ENERGY_GROUP_TOTAL_HISTORY_MASTER, False)
            )

            if group:
                if _group_has_master(entries, group):
                    if not is_master:
                        continue
                elif not _total_energy_sensor_enabled(hass, entry):
                    continue
            elif not _total_energy_sensor_enabled(hass, entry):
                continue

            coordinator = entry.runtime_data
            await coordinator.async_sync_total_history(
                days_ago=days_ago,
                target_entity_id=target_entity_id,
                insert_missing=insert_missing,
                history_skip_extra_hours=history_skip_extra_hours,
                history_hours_to_correct=history_hours_to_correct,
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_TOTAL_HISTORY,
        async_sync_total_history,
        schema=SERVICE_SCHEMA,
    )

    async def async_set_demand_control(call: ServiceCall) -> None:
        """Set demand control (max power limit) on one or all Daikin devices."""
        target_entity_id = call.data.get(ATTR_ENTITY_ID)
        en_demand = call.data.get(ATTR_EN_DEMAND)
        max_pow = call.data.get(ATTR_MAX_POW)
        mode = call.data.get(ATTR_MODE)

        for entry in _entries_for_entity_target(hass, target_entity_id):
            coordinator = entry.runtime_data
            if not coordinator.device.support_demand_control:
                _LOGGER.warning(
                    "[service] %s does not support demand control; skipping",
                    entry.title,
                )
                continue
            async with coordinator.pydaikin_communication_lock:
                await coordinator.device.set_demand_control(
                    en_demand=None
                    if en_demand is None
                    else ("on" if en_demand else "off"),
                    max_pow=max_pow,
                    mode=mode,
                )
            await coordinator.async_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DEMAND_CONTROL,
        async_set_demand_control,
        schema=SET_DEMAND_CONTROL_SCHEMA,
    )

    async def async_set_brp084_options(call: ServiceCall) -> None:
        """Set BRP084-only vertical vane position and/or dry-mode comfort offset."""
        target_entity_id = call.data.get(ATTR_ENTITY_ID)
        vertical_vane = call.data.get(ATTR_VERTICAL_VANE)
        dry_comfort_offset = call.data.get(ATTR_DRY_COMFORT_OFFSET)

        for entry in _entries_for_entity_target(hass, target_entity_id):
            coordinator = entry.runtime_data
            device = coordinator.device
            async with coordinator.pydaikin_communication_lock:
                if vertical_vane is not None:
                    if hasattr(device, "set_vertical_vane"):
                        await device.set_vertical_vane(vertical_vane)
                    else:
                        _LOGGER.warning(
                            "[service] %s does not support vertical vane control; skipping",
                            entry.title,
                        )
                if dry_comfort_offset is not None:
                    if getattr(device, "support_dry_comfort_offset", False):
                        await device.set_dry_comfort_offset(dry_comfort_offset)
                    else:
                        _LOGGER.warning(
                            "[service] %s does not support dry comfort offset; skipping",
                            entry.title,
                        )
            await coordinator.async_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_BRP084_OPTIONS,
        async_set_brp084_options,
        schema=SET_BRP084_OPTIONS_SCHEMA,
    )
