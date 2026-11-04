"""Repair issues raised by Daikin Local (Settings > Repairs)."""

from __future__ import annotations

from typing import Any

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

    Home Assistant 2026.11+ ties the issue to the config entry (deleted with the
    entry, hidden while it is disabled). Older cores do not accept
    ``config_entry_id``; the issue is then deleted on unload instead.
    """
    kwargs: dict[str, Any] = {
        "is_fixable": False,
        # Not persistent: after a restart the entry setup reports the outage itself.
        "is_persistent": False,
        "severity": ir.IssueSeverity.WARNING,
        "translation_key": ISSUE_DEVICE_UNREACHABLE,
        "translation_placeholders": {"name": name, "host": host},
    }
    issue_id = unreachable_issue_id(entry_id)
    try:
        ir.async_create_issue(
            hass, DOMAIN, issue_id, config_entry_id=entry_id, **kwargs
        )
    except TypeError:
        ir.async_create_issue(hass, DOMAIN, issue_id, **kwargs)


def async_delete_unreachable_issue(hass: HomeAssistant, entry_id: str) -> None:
    """Remove the "device unreachable" repair (no-op when absent)."""
    ir.async_delete_issue(hass, DOMAIN, unreachable_issue_id(entry_id))
