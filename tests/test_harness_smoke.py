"""Home Assistant pytest harness — skipped if optional test deps are not installed."""

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant")

pytestmark = pytest.mark.requires_ha


@pytest.mark.asyncio
async def test_hass_fixture_boots(hass) -> None:
    """Confirms pytest-homeassistant fixtures work (custom integrations enabled)."""
    assert hass is not None
