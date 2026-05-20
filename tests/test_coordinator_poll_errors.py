"""Unit tests for coordinator poll error handling (no full Home Assistant)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from tests.coordinator_test_support import (  # noqa: E402
    load_coordinator_module,
    pydaikin_types,
)

DaikinException, Appliance, DaikinBRP069 = pydaikin_types()
from tests.daikin_pure_loader import ensure_daikin_pure_and_const_loaded  # noqa: E402

ensure_daikin_pure_and_const_loaded()

from custom_components.daikin_local.pure import (  # noqa: E402
    brp069_poll_failure_log_domain,
    format_communication_error,
    poll_error_translation_error,
    poll_failure_cooldown_seconds,
    should_serve_cached_poll_data,
)

pytestmark = pytest.mark.local

_NOW = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)


def _coordinator_module():
    return load_coordinator_module()


def _cached_data(mod, device: Appliance):
    return mod.DaikinData(
        appliance=device,
        calculated_total_energy_today=1.0,
        today_energy=1.0,
        today_cool_energy=0.5,
        today_heat_energy=0.5,
    )


def _make_coordinator(
    mod,
    *,
    device: Appliance,
    data=None,
    consecutive_failures: int = 0,
):
    coordinator = object.__new__(mod.DaikinCoordinator)
    coordinator.device = device
    coordinator.data = data
    coordinator.name = "test-ac"
    coordinator._consecutive_poll_failures = consecutive_failures
    coordinator._daily_polling_error_count = 0
    coordinator._daily_state_poll_error_count = 0
    coordinator._daily_energy_poll_error_count = 0
    coordinator._last_state_domain_response_sec = None
    coordinator._last_energy_domain_response_sec = None
    coordinator._poll_cooldown_until = None
    coordinator._error_stats_date = None
    coordinator._schedule_persist_error_stats = lambda: None
    coordinator._ensure_error_stats_date = lambda: False
    return coordinator


# --- pure helpers (single-sourced with coordinator) ---


@pytest.mark.parametrize(
    ("err", "expected"),
    [
        (TimeoutError(), "TimeoutError: TimeoutError()"),
        (RuntimeError("connection reset"), "RuntimeError: connection reset"),
        (RuntimeError(""), "RuntimeError: RuntimeError('')"),
    ],
)
def test_format_communication_error(err: Exception, expected: str) -> None:
    assert format_communication_error(err) == expected


@pytest.mark.parametrize(
    ("is_daikin", "err", "expected"),
    [
        (True, DaikinException("offline"), "offline"),
        (False, TimeoutError(), "TimeoutError: TimeoutError()"),
    ],
)
def test_poll_error_translation_error(
    is_daikin: bool, err: Exception, expected: str
) -> None:
    assert poll_error_translation_error(err, is_daikin_exception=is_daikin) == expected


@pytest.mark.parametrize(
    ("failures", "expected"),
    [(1, 30), (2, 60), (3, 90), (10, 300), (20, 300)],
)
def test_poll_failure_cooldown_seconds(failures: int, expected: int) -> None:
    assert poll_failure_cooldown_seconds(failures) == expected


@pytest.mark.parametrize(
    ("has_data", "failures", "expected"),
    [
        (True, 1, True),
        (True, 3, True),
        (True, 4, False),
        (False, 1, False),
        (False, 3, False),
    ],
)
def test_should_serve_cached_poll_data(
    has_data: bool, failures: int, expected: bool
) -> None:
    assert (
        should_serve_cached_poll_data(
            has_cached_data=has_data,
            consecutive_failures=failures,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("is_brp069", "poll_domain", "expected"),
    [
        (False, None, "state"),
        (False, "energy", "state"),
        (True, "state", "state"),
        (True, "energy", "energy"),
        (True, None, "state"),
        (True, "other", "state"),
    ],
)
def test_brp069_poll_failure_log_domain(
    is_brp069: bool, poll_domain: str | None, expected: str
) -> None:
    assert (
        brp069_poll_failure_log_domain(is_brp069=is_brp069, poll_domain=poll_domain)
        == expected
    )


# --- coordinator UpdateFailed builder ---


def test_update_failed_for_poll_error_daikin_exception() -> None:
    mod = _coordinator_module()
    err = mod._update_failed_for_poll_error(DaikinException("cannot reach host"))
    assert err.translation_domain == "daikin_local"
    assert err.translation_key == "error_communicating"
    assert err.translation_placeholders == {"error": "cannot reach host"}


def test_update_failed_for_poll_error_non_daikin_exception() -> None:
    mod = _coordinator_module()
    err = mod._update_failed_for_poll_error(TimeoutError())
    assert err.translation_key == "error_communicating"
    assert err.translation_placeholders["error"].startswith("TimeoutError:")


# --- coordinator._handle_poll_communication_error ---


def test_handle_poll_error_returns_cached_on_transient_failure() -> None:
    mod = _coordinator_module()
    device = Appliance.__new__(Appliance)
    cached = _cached_data(mod, device)
    coordinator = _make_coordinator(mod, device=device, data=cached, consecutive_failures=0)

    result = coordinator._handle_poll_communication_error(
        DaikinException("timeout"),
        now=_NOW,
        poll_t0_mono=None,
        timeout_f=30.0,
        brp069_poll_domain=None,
    )

    assert result is cached
    assert coordinator._consecutive_poll_failures == 1
    assert coordinator._daily_polling_error_count == 1
    assert coordinator._poll_cooldown_until == _NOW + timedelta(seconds=30)


def test_handle_poll_error_third_failure_still_serves_cache() -> None:
    mod = _coordinator_module()
    device = Appliance.__new__(Appliance)
    cached = _cached_data(mod, device)
    coordinator = _make_coordinator(mod, device=device, data=cached, consecutive_failures=2)

    result = coordinator._handle_poll_communication_error(
        DaikinException("flaky"),
        now=_NOW,
        poll_t0_mono=None,
        timeout_f=30.0,
        brp069_poll_domain=None,
    )

    assert result is cached
    assert coordinator._consecutive_poll_failures == 3


def test_handle_poll_error_fourth_failure_raises_translated_update_failed() -> None:
    mod = _coordinator_module()
    device = Appliance.__new__(Appliance)
    cached = _cached_data(mod, device)
    coordinator = _make_coordinator(mod, device=device, data=cached, consecutive_failures=3)

    with pytest.raises(mod.UpdateFailed) as raised:
        coordinator._handle_poll_communication_error(
            DaikinException("still down"),
            now=_NOW,
            poll_t0_mono=None,
            timeout_f=30.0,
            brp069_poll_domain=None,
        )

    assert raised.value.translation_key == "error_communicating"
    assert raised.value.translation_placeholders == {"error": "still down"}


def test_handle_poll_error_no_cache_raises_immediately() -> None:
    mod = _coordinator_module()
    device = Appliance.__new__(Appliance)
    coordinator = _make_coordinator(mod, device=device, data=None, consecutive_failures=0)

    with pytest.raises(mod.UpdateFailed):
        coordinator._handle_poll_communication_error(
            DaikinException("first failure"),
            now=_NOW,
            poll_t0_mono=None,
            timeout_f=30.0,
            brp069_poll_domain=None,
        )

    assert coordinator._consecutive_poll_failures == 1


def test_handle_poll_error_brp069_increments_state_counter() -> None:
    mod = _coordinator_module()
    device = DaikinBRP069.__new__(DaikinBRP069)
    coordinator = _make_coordinator(mod, device=device, data=None, consecutive_failures=0)

    with pytest.raises(mod.UpdateFailed):
        coordinator._handle_poll_communication_error(
            DaikinException("state poll failed"),
            now=_NOW,
            poll_t0_mono=None,
            timeout_f=30.0,
            brp069_poll_domain="state",
        )

    assert coordinator._daily_state_poll_error_count == 1
    assert coordinator._daily_energy_poll_error_count == 0


def test_handle_poll_error_brp069_increments_energy_counter() -> None:
    mod = _coordinator_module()
    device = DaikinBRP069.__new__(DaikinBRP069)
    coordinator = _make_coordinator(mod, device=device, data=None, consecutive_failures=0)

    with pytest.raises(mod.UpdateFailed):
        coordinator._handle_poll_communication_error(
            DaikinException("energy poll failed"),
            now=_NOW,
            poll_t0_mono=None,
            timeout_f=30.0,
            brp069_poll_domain="energy",
        )

    assert coordinator._daily_energy_poll_error_count == 1
    assert coordinator._daily_state_poll_error_count == 0


def test_handle_poll_error_records_capped_response_time() -> None:
    mod = _coordinator_module()
    device = Appliance.__new__(Appliance)
    coordinator = _make_coordinator(mod, device=device, data=None, consecutive_failures=0)

    with patch.object(mod.time, "monotonic", return_value=130.0):
        with pytest.raises(mod.UpdateFailed):
            coordinator._handle_poll_communication_error(
                DaikinException("slow"),
                now=_NOW,
                poll_t0_mono=100.0,
                timeout_f=30.0,
                brp069_poll_domain=None,
            )

    assert coordinator._last_state_domain_response_sec == 30.0


def test_handle_poll_error_brp069_records_energy_response_time() -> None:
    mod = _coordinator_module()
    device = DaikinBRP069.__new__(DaikinBRP069)
    coordinator = _make_coordinator(mod, device=device, data=None, consecutive_failures=0)

    with patch.object(mod.time, "monotonic", return_value=105.0):
        with pytest.raises(mod.UpdateFailed):
            coordinator._handle_poll_communication_error(
                DaikinException("energy timeout"),
                now=_NOW,
                poll_t0_mono=100.0,
                timeout_f=30.0,
                brp069_poll_domain="energy",
            )

    assert coordinator._last_energy_domain_response_sec == 5.0
    assert coordinator._last_state_domain_response_sec is None
