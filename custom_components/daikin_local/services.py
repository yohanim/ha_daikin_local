"""Services for Daikin integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

SERVICE_SYNC_HISTORY = "sync_history"
SERVICE_SYNC_TOTAL_HISTORY = "sync_total_history"
ATTR_DAYS_AGO = "days_ago"
ATTR_INSERT_MISSING = "insert_missing"

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DAYS_AGO, default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=1)
        ),
        vol.Optional(ATTR_ENTITY_ID): vol.Coerce(str),
        vol.Optional(ATTR_INSERT_MISSING, default=False): cv.boolean,
    }
)

async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for the Daikin integration."""

    async def async_sync_history(call: ServiceCall) -> None:
        """Sync history for all or specific Daikin devices."""
        days_ago = call.data.get(ATTR_DAYS_AGO, 0)
        target_entity_id = call.data.get(ATTR_ENTITY_ID)
        insert_missing = call.data.get(ATTR_INSERT_MISSING, False)

        # In HA 2026.3, runtime_data is stored in entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN):
            if hasattr(entry, "runtime_data") and entry.runtime_data:
                coordinator = entry.runtime_data
                await coordinator.async_sync_history(
                    days_ago=days_ago,
                    target_entity_id=target_entity_id,
                    insert_missing=insert_missing,
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
        insert_missing = call.data.get(ATTR_INSERT_MISSING, False)

        for entry in hass.config_entries.async_entries(DOMAIN):
            if hasattr(entry, "runtime_data") and entry.runtime_data:
                coordinator = entry.runtime_data
                await coordinator.async_sync_total_history(
                    days_ago=days_ago,
                    target_entity_id=target_entity_id,
                    insert_missing=insert_missing,
                )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_TOTAL_HISTORY,
        async_sync_total_history,
        schema=SERVICE_SCHEMA,
    )
