"""Load ``const`` + ``pure`` without executing ``daikin_local/__init__.py`` (no HA / aiohttp)."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_PKG = "custom_components.daikin_local"


def ensure_daikin_pure_and_const_loaded() -> None:
    """Register stub package and ``const`` / ``pure`` submodules (idempotent)."""
    if f"{_PKG}.pure" in sys.modules:
        return

    if "custom_components" not in sys.modules:
        cc = types.ModuleType("custom_components")
        cc.__path__ = [str(_REPO / "custom_components")]
        sys.modules["custom_components"] = cc

    parent = types.ModuleType(_PKG)
    parent.__path__ = [str(_REPO / "custom_components" / "daikin_local")]
    sys.modules[_PKG] = parent

    c_path = _REPO / "custom_components/daikin_local/const.py"
    spec_c = importlib.util.spec_from_file_location(f"{_PKG}.const", c_path)
    if not spec_c or not spec_c.loader:
        msg = f"Cannot load {c_path}"
        raise RuntimeError(msg)
    mod_c = importlib.util.module_from_spec(spec_c)
    sys.modules[f"{_PKG}.const"] = mod_c
    spec_c.loader.exec_module(mod_c)

    p_path = _REPO / "custom_components/daikin_local/pure.py"
    spec_p = importlib.util.spec_from_file_location(f"{_PKG}.pure", p_path)
    if not spec_p or not spec_p.loader:
        msg = f"Cannot load {p_path}"
        raise RuntimeError(msg)
    mod_p = importlib.util.module_from_spec(spec_p)
    sys.modules[f"{_PKG}.pure"] = mod_p
    spec_p.loader.exec_module(mod_p)


def load_utils_standalone():
    """Load ``utils.py`` (no relative imports; no package ``__init__``)."""
    path = _REPO / "custom_components/daikin_local/utils.py"
    spec = importlib.util.spec_from_file_location("daikin_utils_standalone", path)
    if not spec or not spec.loader:
        msg = f"Cannot load {path}"
        raise RuntimeError(msg)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
