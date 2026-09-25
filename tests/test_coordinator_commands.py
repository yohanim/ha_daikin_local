"""Unit tests for coordinator command execution and history-window computation.

Covers behavior introduced/centralized by the code-review pass:
- ``async_execute_command``: commands run under the shared lock, bounded by a
  timeout, and the lock is always released (even when the command hangs).
- ``connection_timeout_sec``: reads the same config as polling.
- ``_history_sync_window``: the windowing logic shared by ``async_sync_history``
  and ``async_sync_total_history`` (previously duplicated, untested).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.coordinator_test_support import load_coordinator_module, pydaikin_types
from tests.daikin_pure_loader import ensure_daikin_pure_and_const_loaded

pydaikin_types()
ensure_daikin_pure_and_const_loaded()

from custom_components.daikin_local.const import CONF_CONNECTION_TIMEOUT, TIMEOUT_SEC

pytestmark = pytest.mark.local


def _coordinator_module():
    return load_coordinator_module()


def _make_command_coordinator(mod, *, options: dict | None = None):
    coordinator = object.__new__(mod.DaikinCoordinator)
    coordinator._pydaikin_communication_lock = asyncio.Lock()
    coordinator.config_entry = SimpleNamespace(data={}, options=options or {})
    return coordinator


def _make_history_coordinator(mod, *, options: dict | None = None):
    coordinator = object.__new__(mod.DaikinCoordinator)
    coordinator.config_entry = SimpleNamespace(data={}, options=options or {})
    coordinator._history_backfill_extra_hour = False
    return coordinator


# ---------------------------------------------------------------------------
# connection_timeout_sec
# ---------------------------------------------------------------------------


def test_connection_timeout_sec_options_override_data() -> None:
    mod = _coordinator_module()
    coordinator = object.__new__(mod.DaikinCoordinator)
    coordinator.config_entry = SimpleNamespace(
        data={CONF_CONNECTION_TIMEOUT: 10}, options={CONF_CONNECTION_TIMEOUT: 42}
    )
    assert coordinator.connection_timeout_sec == 42


def test_connection_timeout_sec_falls_back_to_default() -> None:
    mod = _coordinator_module()
    coordinator = object.__new__(mod.DaikinCoordinator)
    coordinator.config_entry = SimpleNamespace(data={}, options={})
    assert coordinator.connection_timeout_sec == TIMEOUT_SEC


# ---------------------------------------------------------------------------
# async_execute_command: lock + timeout
# ---------------------------------------------------------------------------


async def test_async_execute_command_runs_command_under_lock() -> None:
    mod = _coordinator_module()
    coordinator = _make_command_coordinator(mod)

    ran_while_locked = False

    async def _command() -> None:
        nonlocal ran_while_locked
        ran_while_locked = coordinator.pydaikin_communication_lock.locked()

    await coordinator.async_execute_command(_command)

    assert ran_while_locked is True
    assert not coordinator.pydaikin_communication_lock.locked()


async def test_async_execute_command_propagates_command_error_and_releases_lock() -> None:
    mod = _coordinator_module()
    coordinator = _make_command_coordinator(mod)

    async def _failing_command() -> None:
        raise mod.DaikinException("device rejected the command")

    with pytest.raises(mod.DaikinException):
        await coordinator.async_execute_command(_failing_command)

    assert not coordinator.pydaikin_communication_lock.locked()


async def test_async_execute_command_timeout_releases_lock_for_next_command() -> None:
    """A stuck command must not hold the lock forever (the deadlock this fixes)."""
    mod = _coordinator_module()
    coordinator = _make_command_coordinator(
        mod, options={CONF_CONNECTION_TIMEOUT: 0.05}
    )

    async def _stuck_command() -> None:
        await asyncio.sleep(10)

    with pytest.raises(TimeoutError):
        await coordinator.async_execute_command(_stuck_command)

    assert not coordinator.pydaikin_communication_lock.locked()

    # The lock must be immediately available to a subsequent command/poll.
    ran = False

    async def _quick_command() -> None:
        nonlocal ran
        ran = True

    await asyncio.wait_for(coordinator.async_execute_command(_quick_command), timeout=1)
    assert ran is True


# ---------------------------------------------------------------------------
# _history_sync_window (shared by async_sync_history / async_sync_total_history)
# ---------------------------------------------------------------------------


def _patched_now(mod, *, utcnow: datetime, today_start: datetime):
    return (
        patch.object(mod.dt_util, "utcnow", return_value=utcnow),
        patch.object(mod.dt_util, "start_of_local_day", return_value=today_start),
    )


def test_history_sync_window_empty_when_nothing_to_correct() -> None:
    mod = _coordinator_module()
    coordinator = _make_history_coordinator(mod)

    recent_hours_by_date, days_to_sync, hours_to_correct = (
        coordinator._history_sync_window(
            days_ago=0,
            history_skip_extra_hours=0,
            history_hours_to_correct=0,
        )
    )

    assert recent_hours_by_date == {}
    assert days_to_sync == []
    assert hours_to_correct == 0


def test_history_sync_window_today_only() -> None:
    mod = _coordinator_module()
    coordinator = _make_history_coordinator(mod)

    p_now, p_today = _patched_now(
        mod,
        utcnow=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
        today_start=datetime(2026, 5, 20, 0, 0, tzinfo=UTC),
    )
    with p_now, p_today:
        recent_hours_by_date, days_to_sync, hours_to_correct = (
            coordinator._history_sync_window(
                days_ago=0,
                history_skip_extra_hours=None,
                history_hours_to_correct=None,
            )
        )

    assert recent_hours_by_date == {date(2026, 5, 20): {6, 7, 8}}
    assert days_to_sync == [0]
    assert hours_to_correct == 3


def test_history_sync_window_yesterday_only_crosses_midnight() -> None:
    mod = _coordinator_module()
    coordinator = _make_history_coordinator(mod)

    p_now, p_today = _patched_now(
        mod,
        utcnow=datetime(2026, 5, 20, 1, 30, tzinfo=UTC),
        today_start=datetime(2026, 5, 20, 0, 0, tzinfo=UTC),
    )
    with p_now, p_today:
        recent_hours_by_date, days_to_sync, hours_to_correct = (
            coordinator._history_sync_window(
                days_ago=0,
                history_skip_extra_hours=None,
                history_hours_to_correct=None,
            )
        )

    assert recent_hours_by_date == {date(2026, 5, 19): {21, 22, 23}}
    assert days_to_sync == [1]
    assert hours_to_correct == 3


def test_history_sync_window_spans_today_and_yesterday() -> None:
    mod = _coordinator_module()
    coordinator = _make_history_coordinator(mod)

    p_now, p_today = _patched_now(
        mod,
        utcnow=datetime(2026, 5, 20, 1, 0, tzinfo=UTC),
        today_start=datetime(2026, 5, 20, 0, 0, tzinfo=UTC),
    )
    with p_now, p_today:
        recent_hours_by_date, days_to_sync, hours_to_correct = (
            coordinator._history_sync_window(
                days_ago=0,
                history_skip_extra_hours=0,
                history_hours_to_correct=2,
            )
        )

    assert recent_hours_by_date == {
        date(2026, 5, 20): {0},
        date(2026, 5, 19): {23},
    }
    assert days_to_sync == [0, 1]
    assert hours_to_correct == 2


@pytest.mark.parametrize(("days_ago", "expected"), [(0, [0]), (1, [0, 1])])
def test_history_sync_window_falls_back_when_dates_are_unmatched(
    days_ago: int, expected: list[int]
) -> None:
    """Defensive fallback: if the computed window doesn't land on today/yesterday
    relative to ``start_of_local_day`` (e.g. an inconsistent clock read), fall back
    to the pre-existing ``days_ago``-based day selection instead of syncing nothing.
    """
    mod = _coordinator_module()
    coordinator = _make_history_coordinator(mod)

    p_now, p_today = _patched_now(
        mod,
        utcnow=datetime(2026, 5, 10, 10, 0, tzinfo=UTC),
        today_start=datetime(2026, 5, 20, 0, 0, tzinfo=UTC),
    )
    with p_now, p_today:
        recent_hours_by_date, days_to_sync, _hours_to_correct = (
            coordinator._history_sync_window(
                days_ago=days_ago,
                history_skip_extra_hours=None,
                history_hours_to_correct=None,
            )
        )

    assert recent_hours_by_date  # non-empty, but not on today/yesterday
    assert days_to_sync == expected


# ---------------------------------------------------------------------------
# _normalize_24_hours (previously duplicated in both history sync methods)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([], [0] * 24),
        ([1, 2, 3], [1, 2, 3] + [0] * 21),
        (list(range(24)), list(range(24))),
        (list(range(30)), list(range(24))),
    ],
)
def test_normalize_24_hours(values: list[int], expected: list[int]) -> None:
    mod = _coordinator_module()
    assert mod._normalize_24_hours(values) == expected
