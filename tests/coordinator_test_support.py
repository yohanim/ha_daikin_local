"""Load ``coordinator`` for unit tests without a full Home Assistant install."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import UTC, datetime
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
    dt_mod.utcnow = lambda: datetime.now(UTC)
    dt_mod.as_local = lambda value: value

    storage_mod = sys.modules["homeassistant.helpers.storage"]

    class Store:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    storage_mod.Store = Store

    er_mod = sys.modules["homeassistant.helpers.entity_registry"]
    er_mod.async_get = lambda _hass: None


def install_extra_stubs_for_init() -> None:
    """Extend coordinator stubs with everything __init__.py additionally needs.

    Must be called *after* install_ha_stubs_for_coordinator().
    """
    # ---- aiohttp ----
    if "aiohttp" not in sys.modules:
        aio = types.ModuleType("aiohttp")

        class ClientConnectionError(OSError):
            pass

        aio.ClientConnectionError = ClientConnectionError
        sys.modules["aiohttp"] = aio

    # ---- pydaikin.factory ----
    if "pydaikin.factory" not in sys.modules:
        factory_mod = types.ModuleType("pydaikin.factory")

        async def DaikinFactory(host: str, session: Any) -> Any:
            return None

        factory_mod.DaikinFactory = DaikinFactory
        sys.modules["pydaikin.factory"] = factory_mod

    # ---- homeassistant.const extras ----
    const_mod = sys.modules.get("homeassistant.const")
    if const_mod is not None:
        if not hasattr(const_mod, "CONF_HOST"):
            const_mod.CONF_HOST = "host"
        if not hasattr(const_mod, "Platform"):

            class _Platform:
                CLIMATE = "climate"
                NUMBER = "number"
                SENSOR = "sensor"
                SWITCH = "switch"

            const_mod.Platform = _Platform

    # ---- homeassistant.core extras ----
    core_mod = sys.modules.get("homeassistant.core")
    if core_mod is not None and not hasattr(core_mod, "callback"):
        core_mod.callback = lambda f: f

    # ---- homeassistant.helpers.typing ----
    if "homeassistant.helpers.typing" not in sys.modules:
        typing_mod = types.ModuleType("homeassistant.helpers.typing")
        typing_mod.ConfigType = dict
        sys.modules["homeassistant.helpers.typing"] = typing_mod

    # ---- homeassistant.helpers.config_validation ----
    cv_key = "homeassistant.helpers.config_validation"
    if cv_key not in sys.modules:
        cv_mod = types.ModuleType(cv_key)
        cv_mod.empty_config_schema = lambda _domain: lambda _config: {}
        sys.modules[cv_key] = cv_mod

    # ---- homeassistant.exceptions ----
    if "homeassistant.exceptions" not in sys.modules:
        exc_mod = types.ModuleType("homeassistant.exceptions")

        class ConfigEntryNotReady(Exception):
            pass

        class HomeAssistantError(Exception):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args)
                self.translation_domain = kwargs.get("translation_domain")
                self.translation_key = kwargs.get("translation_key")
                self.translation_placeholders = kwargs.get("translation_placeholders", {})

        class ServiceValidationError(HomeAssistantError):
            pass

        exc_mod.ConfigEntryNotReady = ConfigEntryNotReady
        exc_mod.HomeAssistantError = HomeAssistantError
        exc_mod.ServiceValidationError = ServiceValidationError
        sys.modules["homeassistant.exceptions"] = exc_mod

    # ---- homeassistant.helpers.aiohttp_client ----
    if "homeassistant.helpers.aiohttp_client" not in sys.modules:
        client_mod = types.ModuleType("homeassistant.helpers.aiohttp_client")
        client_mod.async_get_clientsession = lambda _hass: None
        sys.modules["homeassistant.helpers.aiohttp_client"] = client_mod

    # ---- homeassistant.helpers.device_registry ----
    dr_key = "homeassistant.helpers.device_registry"
    if dr_key not in sys.modules:
        dr_mod = types.ModuleType(dr_key)
        sys.modules[dr_key] = dr_mod
    dr_mod = sys.modules[dr_key]
    for _attr, _val in (
        ("async_get", lambda _hass: None),
        ("format_mac", lambda mac: mac.lower()),
        ("CONNECTION_NETWORK_MAC", "mac"),
        ("async_entries_for_config_entry", lambda _reg, _eid: []),
    ):
        if not hasattr(dr_mod, _attr):
            setattr(dr_mod, _attr, _val)

    # ---- homeassistant.helpers.entity_registry extras ----
    er_mod = sys.modules.get("homeassistant.helpers.entity_registry")
    if er_mod is not None:
        if not hasattr(er_mod, "async_entries_for_config_entry"):
            er_mod.async_entries_for_config_entry = lambda _reg, _eid: []
        if not hasattr(er_mod, "async_migrate_entries"):

            async def _noop_migrate(*_args: Any, **_kwargs: Any) -> None:
                pass

            er_mod.async_migrate_entries = _noop_migrate
        if not hasattr(er_mod, "async_entries_for_device"):
            er_mod.async_entries_for_device = (
                lambda _reg, _did, _include_disabled=False: []
            )
        if not hasattr(er_mod, "RegistryEntry"):

            class RegistryEntry:
                unique_id: str = ""
                entity_id: str = ""
                domain: str = ""
                platform: str = ""
                config_entry_id: str | None = None
                disabled_by: Any = None

            er_mod.RegistryEntry = RegistryEntry

    # ---- homeassistant.config_entries extras ----
    ce_mod = sys.modules.get("homeassistant.config_entries")
    if ce_mod is not None:
        for _name in ("ConfigFlow", "OptionsFlow", "ConfigFlowResult"):
            if not hasattr(ce_mod, _name):
                setattr(ce_mod, _name, type(_name, (), {}))
        if not hasattr(ce_mod, "callback"):
            ce_mod.callback = lambda f: f

    # ---- .services stub ----
    services_key = f"{_PKG}.services"
    if services_key not in sys.modules:
        services_mod = types.ModuleType(services_key)

        async def async_setup_services(_hass: Any) -> None:
            pass

        services_mod.async_setup_services = async_setup_services
        sys.modules[services_key] = services_mod


def load_init_module() -> types.ModuleType:
    """Import ``custom_components.daikin_local.__init__`` with HA stubs (idempotent)."""
    cached = sys.modules.get(_PKG)
    if cached is not None and hasattr(cached, "async_migrate_entry"):
        return cached
    if _PKG in sys.modules:
        del sys.modules[_PKG]

    ensure_daikin_pure_and_const_loaded()
    install_pydaikin_stubs()
    install_ha_stubs_for_coordinator()
    install_extra_stubs_for_init()
    load_coordinator_module()  # __init__ imports DaikinCoordinator from coordinator

    init_path = _REPO / "custom_components/daikin_local/__init__.py"
    spec = importlib.util.spec_from_file_location(_PKG, init_path)
    if not spec or not spec.loader:
        msg = f"Cannot load {init_path}"
        raise RuntimeError(msg)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_PKG] = mod
    spec.loader.exec_module(mod)
    return mod


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
