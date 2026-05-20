"""Load ``coordinator`` for unit tests without a full Home Assistant install."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timezone
from typing import Any

from tests.daikin_pure_loader import _PKG, _REPO, ensure_daikin_pure_and_const_loaded

_COORDINATOR_KEY = f"{_PKG}.coordinator"


def install_pydaikin_stubs() -> tuple[type[Exception], type, type]:
    """Minimal ``pydaikin`` modules so ``coordinator`` can load without native deps."""
    if "pydaikin.exceptions" in sys.modules:
        exc_mod = sys.modules["pydaikin.exceptions"]
        base_mod = sys.modules["pydaikin.daikin_base"]
        brp_mod = sys.modules["pydaikin.daikin_brp069"]
        return exc_mod.DaikinException, base_mod.Appliance, brp_mod.DaikinBRP069

    pydaikin = types.ModuleType("pydaikin")
    pydaikin.__path__ = []
    sys.modules["pydaikin"] = pydaikin

    exc_mod = types.ModuleType("pydaikin.exceptions")

    class DaikinException(Exception):
        """Stub matching pydaikin API surface used by the coordinator."""

    exc_mod.DaikinException = DaikinException
    sys.modules["pydaikin.exceptions"] = exc_mod

    base_mod = types.ModuleType("pydaikin.daikin_base")

    class Appliance:
        """Stub appliance base."""

    base_mod.Appliance = Appliance
    sys.modules["pydaikin.daikin_base"] = base_mod

    brp_mod = types.ModuleType("pydaikin.daikin_brp069")

    class DaikinBRP069(Appliance):
        """Stub BRP069 appliance type."""

    brp_mod.DaikinBRP069 = DaikinBRP069
    sys.modules["pydaikin.daikin_brp069"] = brp_mod

    return DaikinException, Appliance, DaikinBRP069


def pydaikin_types() -> tuple[type[Exception], type, type]:
    """Return ``(DaikinException, Appliance, DaikinBRP069)`` (real or stub)."""
    try:
        from pydaikin.daikin_base import Appliance
        from pydaikin.daikin_brp069 import DaikinBRP069
        from pydaikin.exceptions import DaikinException
    except ImportError:
        return install_pydaikin_stubs()
    return DaikinException, Appliance, DaikinBRP069


def install_ha_stubs_for_coordinator() -> None:
    """Register minimal ``homeassistant`` modules required by ``coordinator.py``."""
    if "homeassistant.helpers.update_coordinator" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    sys.modules["homeassistant"] = ha

    nested_paths = (
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.core",
        "homeassistant.components",
        "homeassistant.components.recorder",
        "homeassistant.helpers",
        "homeassistant.helpers.entity_registry",
        "homeassistant.helpers.storage",
        "homeassistant.helpers.update_coordinator",
        "homeassistant.util",
        "homeassistant.util.dt",
    )
    for name in nested_paths:
        mod = types.ModuleType(name)
        if name.endswith(("components", "helpers", "util")):
            mod.__path__ = []
        sys.modules[name] = mod

    sys.modules["homeassistant.components"].recorder = sys.modules[
        "homeassistant.components.recorder"
    ]

    class UpdateFailed(Exception):
        def __init__(
            self,
            *,
            translation_domain: str | None = None,
            translation_key: str | None = None,
            translation_placeholders: dict[str, str] | None = None,
        ) -> None:
            super().__init__(translation_key or translation_domain or "UpdateFailed")
            self.translation_domain = translation_domain
            self.translation_key = translation_key
            self.translation_placeholders = translation_placeholders or {}

    class _GenericStub:
        def __class_getitem__(cls, _item: Any) -> type:
            return cls

    class DataUpdateCoordinator(_GenericStub):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.data = kwargs.get("data")
            self.name = kwargs.get("name", "daikin")

    uc = sys.modules["homeassistant.helpers.update_coordinator"]
    uc.UpdateFailed = UpdateFailed
    uc.DataUpdateCoordinator = DataUpdateCoordinator

    class ConfigEntry(_GenericStub):
        pass

    sys.modules["homeassistant.config_entries"].ConfigEntry = ConfigEntry
    sys.modules["homeassistant.core"].HomeAssistant = type("HomeAssistant", (), {})

    const_mod = sys.modules["homeassistant.const"]
    const_mod.UnitOfEnergy = type("UnitOfEnergy", (), {"KILO_WATT_HOUR": "kWh"})

    dt_mod = sys.modules["homeassistant.util.dt"]
    dt_mod.utcnow = lambda: datetime.now(timezone.utc)
    dt_mod.as_local = lambda value: value

    storage_mod = sys.modules["homeassistant.helpers.storage"]

    class Store:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    storage_mod.Store = Store

    er_mod = sys.modules["homeassistant.helpers.entity_registry"]
    er_mod.async_get = lambda _hass: None


def load_coordinator_module():
    """Import ``custom_components.daikin_local.coordinator`` with HA stubs (idempotent)."""
    cached = sys.modules.get(_COORDINATOR_KEY)
    if cached is not None and hasattr(cached, "DaikinCoordinator"):
        return cached
    if _COORDINATOR_KEY in sys.modules:
        del sys.modules[_COORDINATOR_KEY]

    ensure_daikin_pure_and_const_loaded()
    try:
        import pydaikin  # noqa: F401
    except ImportError:
        install_pydaikin_stubs()
    install_ha_stubs_for_coordinator()

    utils_path = _REPO / "custom_components/daikin_local/utils.py"
    spec_u = importlib.util.spec_from_file_location(f"{_PKG}.utils", utils_path)
    if not spec_u or not spec_u.loader:
        msg = f"Cannot load {utils_path}"
        raise RuntimeError(msg)
    mod_u = importlib.util.module_from_spec(spec_u)
    sys.modules[f"{_PKG}.utils"] = mod_u
    spec_u.loader.exec_module(mod_u)

    coord_path = _REPO / "custom_components/daikin_local/coordinator.py"
    spec_c = importlib.util.spec_from_file_location(_COORDINATOR_KEY, coord_path)
    if not spec_c or not spec_c.loader:
        msg = f"Cannot load {coord_path}"
        raise RuntimeError(msg)
    mod_c = importlib.util.module_from_spec(spec_c)
    sys.modules[_COORDINATOR_KEY] = mod_c
    spec_c.loader.exec_module(mod_c)
    return mod_c
