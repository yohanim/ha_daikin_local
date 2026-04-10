"""Tests that need only the standard library — run anywhere (Windows, CI, venv)."""

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.local

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "custom_components" / "daikin_local" / "manifest.json"
HACS = REPO_ROOT / "hacs.json"
CONST_PY = REPO_ROOT / "custom_components" / "daikin_local" / "const.py"


def _load_const_domain() -> str:
    """Load ``DOMAIN`` from ``const.py`` without importing the integration package."""
    spec = importlib.util.spec_from_file_location("daikin_const_standalone", CONST_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return str(mod.DOMAIN)


def test_manifest_json_valid() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["domain"] == "daikin_local"
    assert data["name"]
    assert isinstance(data.get("requirements"), list)
    assert data["version"]


def test_hacs_json_valid() -> None:
    data = json.loads(HACS.read_text(encoding="utf-8"))
    assert data["name"]
    assert data["homeassistant"]


def test_const_domain_matches_manifest() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert _load_const_domain() == data["domain"]
