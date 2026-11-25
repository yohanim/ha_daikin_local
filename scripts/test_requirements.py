"""Print the pip requirements of a test run, derived from the repository metadata.

Usage: python scripts/test_requirements.py {minimum,latest}

- minimum: Home Assistant at the ``hacs.json`` floor (``pytest-homeassistant``
  pins the matching ``homeassistant``), and every ``manifest.json`` requirement
  at its declared minimum (``pkg>=X`` becomes ``pkg==X``).
- latest: the newest ``pytest-homeassistant`` (hence the newest Core) and the
  ``manifest.json`` requirements as declared, resolved to their newest version.

So the CI follows ``hacs.json`` and ``manifest.json`` without the versions
being repeated anywhere else. Test-only tools live in requirements_test.txt.
Standard library only: it runs before anything is installed.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = "pytest-homeassistant"
MODES = ("minimum", "latest")

# "name>=1.2.3" (optionally with extras). Anything else (no floor, upper bounds,
# markers) is passed through unchanged.
_FLOOR = re.compile(r"\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]*\])?)\s*>=\s*(?P<version>[^\s,;]+)\s*")


def pin_to_minimum(requirement: str) -> str:
    """``pkg>=X`` becomes ``pkg==X``; other requirements are kept as declared."""
    match = _FLOOR.fullmatch(requirement)
    if match is None:
        return requirement.strip()
    return f"{match['name']}=={match['version']}"


def _manifest(root: Path) -> dict:
    manifests = sorted(root.glob("custom_components/*/manifest.json"))
    if len(manifests) != 1:
        msg = f"expected one custom_components/*/manifest.json, found {len(manifests)}"
        raise SystemExit(msg)
    return json.loads(manifests[0].read_text(encoding="utf-8"))


def requirements(mode: str, root: Path = ROOT) -> list[str]:
    """Requirements of the ``minimum`` or ``latest`` run."""
    if mode not in MODES:
        msg = f"unknown mode {mode!r}, expected one of {MODES}"
        raise ValueError(msg)
    manifest_requirements = _manifest(root).get("requirements", [])
    if mode == "latest":
        return [HARNESS, *manifest_requirements]
    floor = json.loads((root / "hacs.json").read_text(encoding="utf-8"))["homeassistant"]
    return [f"{HARNESS}=={floor}", *(pin_to_minimum(r) for r in manifest_requirements)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=MODES)
    args = parser.parse_args(argv)
    print("\n".join(requirements(args.mode)))


if __name__ == "__main__":
    main()
