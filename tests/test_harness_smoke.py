"""Home Assistant pytest harness — skipped if optional test deps are not installed."""

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

pytestmark = pytest.mark.requires_ha


@pytest.mark.asyncio
async def test_hass_fixture_boots(hass, enable_custom_integrations) -> None:
    """Confirms pytest-homeassistant-custom-component fixtures work."""
    assert hass is not None
