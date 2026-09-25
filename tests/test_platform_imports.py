"""Import every integration module against a real Home Assistant install.

The rest of the suite runs against lightweight stubs (fast, no HA install needed
on Windows) so a name that doesn't actually exist in ``homeassistant.const`` (or
any other real-package-only symbol) can slip through unnoticed — that's exactly
what happened with ``UnitOfSignalStrength``, which isn't a real HA constant, and
broke ``sensor.py`` (and therefore the whole integration) for every user on
startup. A plain import of each module is enough to catch that class of bug.
"""

from __future__ import annotations

import importlib

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

pytestmark = pytest.mark.requires_ha

PLATFORM_MODULES = (
    "custom_components.daikin_local",
    "custom_components.daikin_local.const",
    "custom_components.daikin_local.pure",
    "custom_components.daikin_local.utils",
    "custom_components.daikin_local.entity",
    "custom_components.daikin_local.coordinator",
    "custom_components.daikin_local.config_flow",
    "custom_components.daikin_local.services",
    "custom_components.daikin_local.climate",
    "custom_components.daikin_local.number",
    "custom_components.daikin_local.sensor",
    "custom_components.daikin_local.switch",
)


@pytest.mark.parametrize("module_name", PLATFORM_MODULES)
def test_module_imports_cleanly(module_name: str) -> None:
    """Every integration module must import without error under real HA/pydaikin."""
    importlib.import_module(module_name)
