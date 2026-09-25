"""Unit tests for BRP069 domain-scheduling in ``DaikinCoordinator._async_update_data``.

This locks down the branch-dispatch logic (which of state/energy gets polled, and
which ``_brp069_last_*_poll_mono`` / ``_last_*_domain_response_sec`` trackers get
updated) across a refactor that replaced four near-identical inline blocks with a
single ``_poll_brp069_domain`` closure. Each test asserts both *what got polled*
(via the ``update_status`` call log) and *what got left untouched*.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

import pytest

from tests.coordinator_test_support import load_coordinator_module
from tests.daikin_pure_loader import ensure_daikin_pure_and_const_loaded

ensure_daikin_pure_and_const_loaded()

pytestmark = pytest.mark.local

_NOW_MONO = 1000.0
_STATE_INTERVAL = 60
_ENERGY_INTERVAL = 300
# 10s ago: below both intervals above, so "not due" for either domain.
_RECENTLY_POLLED_MONO = _NOW_MONO - 10


class _FakeBRP069:
    """Minimal stand-in for pydaikin's ``DaikinBRP069``.

    Deliberately does NOT subclass the real class: in real pydaikin,
    ``support_energy_consumption`` is a read-only ``@property`` computed from
    ``self.values``, so assigning it directly (as these tests need to, to force
    each scheduling branch) raises ``AttributeError``. ``mod.DaikinBRP069`` is
    monkeypatched to this class for the duration of the call under test, so
    ``isinstance(self.device, DaikinBRP069)`` in the coordinator still matches.
    """

    def __init__(self, *, support_energy_consumption: bool) -> None:
        self.support_energy_consumption = support_energy_consumption
        self.values: dict = {}
        self.update_status = AsyncMock()


def _coordinator_module():
    return load_coordinator_module()


def _make_brp069_coordinator(
    mod,
    *,
    last_state_poll_mono: float | None,
    last_energy_poll_mono: float | None,
    support_energy_consumption: bool = True,
):
    device = _FakeBRP069(support_energy_consumption=support_energy_consumption)

    coordinator = object.__new__(mod.DaikinCoordinator)
    coordinator.device = device
    coordinator.name = "test-ac"
    coordinator.data = None
    coordinator.hass = SimpleNamespace()
    coordinator.config_entry = SimpleNamespace(data={}, options={})
    coordinator._pydaikin_communication_lock = mod.asyncio.Lock()
    coordinator._brp069_state_interval_s = _STATE_INTERVAL
    coordinator._brp069_energy_interval_s = _ENERGY_INTERVAL
    coordinator._brp069_last_state_poll_mono = last_state_poll_mono
    coordinator._brp069_last_energy_poll_mono = last_energy_poll_mono
    coordinator._consecutive_poll_failures = 0
    coordinator._poll_cooldown_until = None
    coordinator._last_power = 0
    coordinator._total_power_enabled_cached = False
    coordinator._total_power_enabled_checked_mono = _NOW_MONO
    coordinator._last_state_domain_response_sec = None
    coordinator._last_energy_domain_response_sec = None
    coordinator._error_stats_date = mod.dt_util.as_local(mod.dt_util.utcnow()).date()
    return coordinator


async def _run_update(mod, coordinator):
    with (
        patch.object(mod, "DaikinBRP069", _FakeBRP069),
        patch.object(mod.time, "monotonic", return_value=_NOW_MONO),
    ):
        return await coordinator._async_update_data()


async def test_both_domains_due_polls_state_then_energy() -> None:
    mod = _coordinator_module()
    coordinator = _make_brp069_coordinator(
        mod, last_state_poll_mono=None, last_energy_poll_mono=None
    )

    data = await _run_update(mod, coordinator)

    assert data is not None
    assert coordinator.device.update_status.call_args_list == [
        call(list(mod.BRP069_STATE_RESOURCES)),
        call(list(mod.BRP069_ENERGY_RESOURCES)),
    ]
    assert coordinator._brp069_last_state_poll_mono == _NOW_MONO
    assert coordinator._brp069_last_energy_poll_mono == _NOW_MONO
    assert coordinator._last_state_domain_response_sec == 0.0
    assert coordinator._last_energy_domain_response_sec == 0.0


async def test_only_state_due_skips_energy_poll() -> None:
    mod = _coordinator_module()
    coordinator = _make_brp069_coordinator(
        mod,
        last_state_poll_mono=None,
        last_energy_poll_mono=_RECENTLY_POLLED_MONO,
    )

    await _run_update(mod, coordinator)

    coordinator.device.update_status.assert_awaited_once_with(
        list(mod.BRP069_STATE_RESOURCES)
    )
    assert coordinator._brp069_last_state_poll_mono == _NOW_MONO
    # Energy domain untouched: neither polled nor its tracker advanced.
    assert coordinator._brp069_last_energy_poll_mono == _RECENTLY_POLLED_MONO
    assert coordinator._last_energy_domain_response_sec is None


async def test_only_energy_due_skips_state_poll() -> None:
    mod = _coordinator_module()
    coordinator = _make_brp069_coordinator(
        mod,
        last_state_poll_mono=_RECENTLY_POLLED_MONO,
        last_energy_poll_mono=None,
    )

    await _run_update(mod, coordinator)

    coordinator.device.update_status.assert_awaited_once_with(
        list(mod.BRP069_ENERGY_RESOURCES)
    )
    assert coordinator._brp069_last_energy_poll_mono == _NOW_MONO
    # State domain untouched.
    assert coordinator._brp069_last_state_poll_mono == _RECENTLY_POLLED_MONO
    assert coordinator._last_state_domain_response_sec is None


async def test_neither_domain_due_still_does_minimal_state_poll() -> None:
    """Pre-existing quirk (kept intentionally): with nothing due, the coordinator
    still issues a minimal state poll rather than skipping the tick entirely."""
    mod = _coordinator_module()
    coordinator = _make_brp069_coordinator(
        mod,
        last_state_poll_mono=_RECENTLY_POLLED_MONO,
        last_energy_poll_mono=_RECENTLY_POLLED_MONO,
    )

    await _run_update(mod, coordinator)

    coordinator.device.update_status.assert_awaited_once_with(
        list(mod.BRP069_STATE_RESOURCES)
    )
    assert coordinator._brp069_last_state_poll_mono == _NOW_MONO
    assert coordinator._brp069_last_energy_poll_mono == _RECENTLY_POLLED_MONO


async def test_energy_never_due_when_device_does_not_support_it() -> None:
    """``support_energy_consumption=False`` must force the energy branch off,
    even though ``last_energy_poll_mono=None`` would otherwise mean "due"."""
    mod = _coordinator_module()
    coordinator = _make_brp069_coordinator(
        mod,
        last_state_poll_mono=None,
        last_energy_poll_mono=None,
        support_energy_consumption=False,
    )

    await _run_update(mod, coordinator)

    coordinator.device.update_status.assert_awaited_once_with(
        list(mod.BRP069_STATE_RESOURCES)
    )
    assert coordinator._brp069_last_energy_poll_mono is None
    assert coordinator._last_energy_domain_response_sec is None
