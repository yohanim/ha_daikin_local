"""Repair issue helpers against the real Home Assistant issue registry."""

import importlib

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant")

from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant.common import MockConfigEntry

pytestmark = pytest.mark.requires_ha

DOMAIN = "daikin_local"


@pytest.mark.asyncio
async def test_unreachable_issue_roundtrip(hass) -> None:
    issues = importlib.import_module("custom_components.daikin_local.issues")
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "192.0.2.10"})
    entry.add_to_hass(hass)

    issues.async_create_unreachable_issue(
        hass, entry.entry_id, name="Salon", host="192.0.2.10"
    )
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, f"device_unreachable_{entry.entry_id}")
    assert issue is not None
    assert issue.translation_key == "device_unreachable"
    assert issue.translation_placeholders == {"name": "Salon", "host": "192.0.2.10"}
    assert issue.is_fixable is False
    assert issue.config_entry_id == entry.entry_id

    issues.async_delete_unreachable_issue(hass, entry.entry_id)
    assert registry.async_get_issue(DOMAIN, f"device_unreachable_{entry.entry_id}") is None
