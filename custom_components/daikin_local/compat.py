"""pydaikin features newer than the manifest floor (pydaikin>=2.22.1).

The floor follows the pydaikin version pinned by the oldest supported Home
Assistant (2026.11 ships 2.22.1): hassfest rejects a custom integration that
requires a newer version than Core pins. Features from later releases are used
when the installed pydaikin has them (Home Assistant 2026.12 ships 2.24.1):

- 2.23.0: adaptive setpoint step (``target_temperature_step``, 0.5 with a
  whole-degree fallback) and ``DaikinVerificationError``.
- 2.24.0: ``DaikinUnsupportedError`` and ``discovery.is_unsupported`` for
  adapters without a local API.

Drop each fallback once the manifest floor includes it.
"""

from __future__ import annotations

from typing import Any

from pydaikin.daikin_airbase import DaikinAirBase
from pydaikin.daikin_base import Appliance
from pydaikin.daikin_brp069 import DaikinBRP069
from pydaikin.exceptions import DaikinException

try:
    from pydaikin.exceptions import DaikinVerificationError
except ImportError:  # pydaikin < 2.23: never raised

    class DaikinVerificationError(DaikinException):  # type: ignore[no-redef]
        """Placeholder: a half-degree setpoint read back differently."""

        def __init__(self, requested: str, actual: str) -> None:
            super().__init__(f"Daikin accepted stemp={requested} but reports {actual}")
            self.requested = requested
            self.actual = actual


try:
    from pydaikin.exceptions import DaikinUnsupportedError
except ImportError:  # pydaikin < 2.24: never raised

    class DaikinUnsupportedError(DaikinException):  # type: ignore[no-redef]
        """Placeholder: the adapter has no local control API."""


try:
    from pydaikin.discovery import is_unsupported
except ImportError:  # pydaikin < 2.24

    def is_unsupported(device: dict[str, Any]) -> bool:
        """Without pydaikin's fingerprints, no discovered device is ruled out."""
        return False


def default_target_temperature_step(device: Appliance) -> float:
    """Setpoint step pydaikin >= 2.23 reports by default, for older versions.

    Same table (BRP069/BRP072C 0.5, AirBase 1, others 1), without the adaptive
    whole-degree fallback, which needs pydaikin 2.23.
    """
    if isinstance(device, DaikinAirBase):
        return 1.0
    if isinstance(device, DaikinBRP069):
        return 0.5
    return 1.0


def has_adaptive_step(device: Appliance) -> bool:
    """True if pydaikin learns the setpoint step at runtime (BRP069, >= 2.23)."""
    return hasattr(type(device), "target_temperature_step_status")


__all__ = [
    "DaikinUnsupportedError",
    "DaikinVerificationError",
    "default_target_temperature_step",
    "has_adaptive_step",
    "is_unsupported",
]
