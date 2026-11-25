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


# --- scripts/test_requirements.py (CI "minimum" / "latest" runs) ---


def _test_requirements_module():
    path = REPO_ROOT / "scripts" / "test_requirements.py"
    spec = importlib.util.spec_from_file_location("test_requirements_script", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        ("pydaikin>=2.24.1", "pydaikin==2.24.1"),
        (" pkg >= 1.0 ", "pkg==1.0"),
        ("pkg[extra]>=2.0", "pkg[extra]==2.0"),
        ("babel", "babel"),  # no floor: kept as declared
        ("pkg>=1.0,<2", "pkg>=1.0,<2"),  # bounded range: kept as declared
        ("pkg==3.1", "pkg==3.1"),
    ],
)
def test_pin_to_minimum(requirement: str, expected: str) -> None:
    assert _test_requirements_module().pin_to_minimum(requirement) == expected


def test_minimum_run_follows_hacs_and_manifest_floors() -> None:
    mod = _test_requirements_module()
    floor = json.loads(HACS.read_text(encoding="utf-8"))["homeassistant"]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert mod.requirements("minimum") == [
        f"pytest-homeassistant=={floor}",
        *(mod.pin_to_minimum(r) for r in manifest["requirements"]),
    ]
    assert any(r.startswith("pydaikin==") for r in mod.requirements("minimum"))


def test_latest_run_is_unpinned() -> None:
    mod = _test_requirements_module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert mod.requirements("latest") == ["pytest-homeassistant", *manifest["requirements"]]


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        _test_requirements_module().requirements("pinned")
