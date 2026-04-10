"""Integration diagnostics entry point — **must stay tiny**.

Home Assistant loads this module with ``import_module`` on the **event loop**
(see ``loader._import_platform``). Any top-level import of Home Assistant or
integration submodules can trigger "blocking call" warnings. Real logic lives in
``diagnostics_data`` and is imported only when diagnostics are requested.
"""

from __future__ import annotations

from typing import Any


async def async_get_config_entry_diagnostics(hass: Any, entry: Any) -> dict[str, Any]:
    """Delegate to implementation (lazy import)."""
    from . import diagnostics_data

    return await diagnostics_data.async_get_config_entry_diagnostics(hass, entry)


async def async_get_device_diagnostics(
    hass: Any, entry: Any, device: Any
) -> dict[str, Any]:
    """Delegate to implementation (lazy import)."""
    from . import diagnostics_data

    return await diagnostics_data.async_get_device_diagnostics(hass, entry, device)
