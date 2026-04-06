"""Platform for the Daikin AC."""

from __future__ import annotations

import asyncio
import logging

from aiohttp import ClientConnectionError
from pydaikin.daikin_base import Appliance
from pydaikin.factory import DaikinFactory

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_TIMEOUT, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from .const import KEY_MAC, TIMEOUT_SEC, DOMAIN, CONF_HISTORY_SKIP_EXTRA_HOURS
from .coordinator import DaikinConfigEntry, DaikinCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

# v1.1.0 diagnostics used these keys; v1.1.1+ uses pydaikin_daily_poll_errors.
_LEGACY_DIAGNOSTIC_SENSOR_KEYS: tuple[tuple[str, str], ...] = (
    ("daily_pooling_error", "pydaikin_daily_poll_errors"),
)

# Removed sensor: pydaikin_daily_history_errors (and legacy daily_history_error key).
_OBSOLETE_HISTORY_ERROR_UNIQUE_ID_SUFFIXES: tuple[str, ...] = (
    "-pydaikin_daily_history_errors",
    "-daily_history_error",
)

PLATFORMS = [Platform.CLIMATE, Platform.SENSOR, Platform.SWITCH]

_OBSOLETE_CONFIG_KEYS = frozenset({"api_key", "password", "uuid"})
_LEGACY_OPTION_SKIP_HOURS = "history_skip_hours"


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entries (matches config_flow FlowHandler.VERSION)."""
    # v1 -> v2: drop legacy credential keys from entry.data
    if entry.version == 1:
        new_data = {
            k: v for k, v in entry.data.items() if k not in _OBSOLETE_CONFIG_KEYS
        }
        hass.config_entries.async_update_entry(entry, data=new_data, version=2)
        return True

    # v2 -> v3: rename history window option to "extra hours" semantics
    if entry.version == 2:
        options = dict(entry.options)
        if (
            _LEGACY_OPTION_SKIP_HOURS in options
            and CONF_HISTORY_SKIP_EXTRA_HOURS not in options
        ):
            try:
                legacy_total = int(options.get(_LEGACY_OPTION_SKIP_HOURS) or 2)
            except (TypeError, ValueError):
                legacy_total = 2
            # legacy_total included the current hour; new option counts only extra.
            extra = max(0, legacy_total - 1)
            options.pop(_LEGACY_OPTION_SKIP_HOURS, None)
            options[CONF_HISTORY_SKIP_EXTRA_HOURS] = extra

        hass.config_entries.async_update_entry(entry, options=options, version=3)
        return True

    # v3 -> v4: remove obsolete history_sync_minutes_after_hour (auto history uses polling only)
    if entry.version == 3:
        options = dict(entry.options)
        options.pop("history_sync_minutes_after_hour", None)
        hass.config_entries.async_update_entry(entry, options=options, version=4)
        return True

    return True


async def async_setup_entry(hass: HomeAssistant, entry: DaikinConfigEntry) -> bool:
    """Establish connection with Daikin."""
    conf = entry.data
    # For backwards compat, set unique ID
    if entry.unique_id is None or ".local" in entry.unique_id:
        hass.config_entries.async_update_entry(entry, unique_id=conf[KEY_MAC])

    session = async_get_clientsession(hass)
    host = conf[CONF_HOST]
    # Polling / connection timeout: options override data (same as coordinator).
    timeout = entry.options.get(CONF_TIMEOUT) or conf.get(CONF_TIMEOUT) or TIMEOUT_SEC
    try:
        async with asyncio.timeout(timeout):
            device: Appliance = await DaikinFactory(host, session)
        _LOGGER.debug("Connection to %s successful", host)
    except TimeoutError as err:
        _LOGGER.debug("Connection to %s timed out in %s seconds", host, timeout)
        raise ConfigEntryNotReady from err
    except ClientConnectionError as err:
        _LOGGER.debug("ClientConnectionError to %s", host)
        raise ConfigEntryNotReady from err

    coordinator = DaikinCoordinator(hass, entry, device)

    await coordinator.async_load_error_stats()
    await coordinator.async_config_entry_first_refresh()

    await async_migrate_unique_id(hass, entry, device)
    _migrate_legacy_diagnostic_sensor_unique_ids(hass, device)
    _remove_obsolete_history_error_sensor_entities(hass, entry.entry_id)

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services once
    if not hass.data.get(f"{DOMAIN}_services_registered"):
        await async_setup_services(hass)
        hass.data[f"{DOMAIN}_services_registered"] = True

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def update_listener(hass: HomeAssistant, entry: DaikinConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: DaikinConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


@callback
def _migrate_legacy_diagnostic_sensor_unique_ids(
    hass: HomeAssistant, device: Appliance
) -> None:
    """Merge duplicate diagnostic sensors after renaming sensor keys (1.1.0 -> 1.1.1+).

    Old unique_id: <mac>-daily_pooling_error
    New unique_id: <mac>-pydaikin_daily_poll_errors
    """
    ent_reg = er.async_get(hass)
    mac = device.mac
    for old_suffix, new_suffix in _LEGACY_DIAGNOSTIC_SENSOR_KEYS:
        old_uid = f"{mac}-{old_suffix}"
        new_uid = f"{mac}-{new_suffix}"
        old_entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, old_uid)
        new_entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, new_uid)
        if old_entity_id and new_entity_id:
            _LOGGER.info(
                "Removing legacy duplicate diagnostic entity %s (%s); keeping %s",
                old_entity_id,
                old_uid,
                new_entity_id,
            )
            ent_reg.async_remove(old_entity_id)
        elif old_entity_id and not new_entity_id:
            _LOGGER.info(
                "Migrating diagnostic entity %s unique_id %s -> %s",
                old_entity_id,
                old_uid,
                new_uid,
            )
            ent_reg.async_update_entity(old_entity_id, new_unique_id=new_uid)


@callback
def _remove_obsolete_history_error_sensor_entities(
    hass: HomeAssistant, config_entry_id: str
) -> None:
    """Drop removed diagnostic sensors from the entity registry (idempotent).

    The pydaikin_daily_history_errors entity was removed from the integration; old
    registry rows would otherwise linger. Recorder LTS rows for the old statistic_id
    may remain until HA purge — same as any deleted entity.
    """
    ent_reg = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(ent_reg, config_entry_id):
        if entity.domain != "sensor" or entity.platform != DOMAIN:
            continue
        uid = entity.unique_id or ""
        if not any(uid.endswith(sfx) for sfx in _OBSOLETE_HISTORY_ERROR_UNIQUE_ID_SUFFIXES):
            continue
        _LOGGER.info(
            "Removing obsolete diagnostic entity %s (unique_id=%s)",
            entity.entity_id,
            uid,
        )
        ent_reg.async_remove(entity.entity_id)


async def async_migrate_unique_id(
    hass: HomeAssistant, config_entry: DaikinConfigEntry, device: Appliance
) -> None:
    """Migrate old entry."""
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    old_unique_id = config_entry.unique_id
    new_unique_id = device.mac
    new_mac = dr.format_mac(new_unique_id)
    new_name = device.values.get("name", "Daikin AC")

    @callback
    def _update_unique_id(entity_entry: er.RegistryEntry) -> dict[str, str] | None:
        """Update unique ID of entity entry."""
        return update_unique_id(entity_entry, new_unique_id)

    if new_unique_id == old_unique_id:
        return

    duplicate = dev_reg.async_get_device(
        connections={(CONNECTION_NETWORK_MAC, new_mac)}, identifiers=None
    )

    # Remove duplicated device
    if duplicate is not None:
        if config_entry.entry_id in duplicate.config_entries:
            _LOGGER.debug(
                "Removing duplicated device %s",
                duplicate.name,
            )

            # The automatic cleanup in entity registry is scheduled as a task, remove
            # the entities manually to avoid unique_id collision when the entities
            # are migrated.
            duplicate_entities = er.async_entries_for_device(
                ent_reg, duplicate.id, True
            )
            for entity in duplicate_entities:
                if entity.config_entry_id == config_entry.entry_id:
                    ent_reg.async_remove(entity.entity_id)

            dev_reg.async_update_device(
                duplicate.id, remove_config_entry_id=config_entry.entry_id
            )

    # Migrate devices
    for device_entry in dr.async_entries_for_config_entry(
        dev_reg, config_entry.entry_id
    ):
        for connection in device_entry.connections:
            if connection[1] == old_unique_id:
                new_connections = {(CONNECTION_NETWORK_MAC, new_mac)}

                _LOGGER.debug(
                    "Migrating device %s connections to %s",
                    device_entry.name,
                    new_connections,
                )
                dev_reg.async_update_device(
                    device_entry.id,
                    merge_connections=new_connections,
                )

        if device_entry.name is None:
            _LOGGER.debug(
                "Migrating device name to %s",
                new_name,
            )
            dev_reg.async_update_device(
                device_entry.id,
                name=new_name,
            )

        # Migrate entities
        await er.async_migrate_entries(hass, config_entry.entry_id, _update_unique_id)

        new_data = {**config_entry.data, KEY_MAC: dr.format_mac(new_unique_id)}

        hass.config_entries.async_update_entry(
            config_entry, unique_id=new_unique_id, data=new_data
        )


@callback
def update_unique_id(
    entity_entry: er.RegistryEntry, unique_id: str
) -> dict[str, str] | None:
    """Update unique ID of entity entry."""
    if entity_entry.unique_id.startswith(unique_id):
        # Already correct, nothing to do
        return None

    unique_id_parts = entity_entry.unique_id.split("-")
    unique_id_parts[0] = unique_id
    entity_new_unique_id = "-".join(unique_id_parts)

    _LOGGER.debug(
        "Migrating entity %s from %s to new id %s",
        entity_entry.entity_id,
        entity_entry.unique_id,
        entity_new_unique_id,
    )
    return {"new_unique_id": entity_new_unique_id}
