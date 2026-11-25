"""Repair issues raised by Daikin Local (Settings > Repairs)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

ISSUE_DEVICE_UNREACHABLE = "device_unreachable"


def unreachable_issue_id(entry_id: str) -> str:
    """Issue id of the "device unreachable" repair for one config entry."""
    return f"{ISSUE_DEVICE_UNREACHABLE}_{entry_id}"


def async_create_unreachable_issue(
    hass: HomeAssistant, entry_id: str, *, name: str, host: str
) -> None:
    """Show a repair telling the user the unit stopped answering.

    The issue is tied to the config entry, so Home Assistant deletes it with the
    entry and hides it while the entry is disabled.
    """
    ir.async_create_issue(
        hass,
        DOMAIN,
        unreachable_issue_id(entry_id),
        config_entry_id=entry_id,
        is_fixable=False,
        # Not persistent: after a restart the entry setup reports the outage itself.
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_DEVICE_UNREACHABLE,
        translation_placeholders={"name": name, "host": host},
    )


def async_delete_unreachable_issue(hass: HomeAssistant, entry_id: str) -> None:
    """Remove the "device unreachable" repair (no-op when absent)."""
    ir.async_delete_issue(hass, DOMAIN, unreachable_issue_id(entry_id))
