"""Tests for the "device unreachable" repair issue (no full Home Assistant needed)."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.coordinator_test_support import load_coordinator_module, pydaikin_types
from tests.daikin_pure_loader import ensure_daikin_pure_and_const_loaded

DaikinException, Appliance, _ = pydaikin_types()
ensure_daikin_pure_and_const_loaded()

from custom_components.daikin_local.pure import (
    UNREACHABLE_ISSUE_AFTER,
    unreachable_issue_due,
)

pytestmark = pytest.mark.local

_T0 = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _coordinator(mod):
    coordinator = object.__new__(mod.DaikinCoordinator)
    coordinator.device = Appliance.__new__(Appliance)
    coordinator.data = mod.DaikinData(
        appliance=coordinator.device,
        calculated_total_energy_today=0.0,
        today_energy=0.0,
        today_cool_energy=0.0,
        today_heat_energy=0.0,
    )
    coordinator.name = "Salon"
    coordinator.hass = SimpleNamespace()
    coordinator.config_entry = SimpleNamespace(
        entry_id="entry-1", data={"host": "192.0.2.10"}, options={}
    )
    coordinator._consecutive_poll_failures = 0
    coordinator._daily_polling_error_count = 0
    coordinator._daily_state_poll_error_count = 0
    coordinator._daily_energy_poll_error_count = 0
    coordinator._last_state_domain_response_sec = None
    coordinator._last_energy_domain_response_sec = None
    coordinator._poll_cooldown_until = None
    coordinator._error_stats_date = None
    coordinator._failing_since = None
    coordinator._unreachable_issue_active = False
    coordinator._schedule_persist_error_stats = lambda: None
    coordinator._ensure_error_stats_date = lambda: False
    return coordinator


def _fail(coordinator, mod, now: datetime) -> None:
    try:
        coordinator._handle_poll_communication_error(
            DaikinException("down"),
            now=now,
            poll_t0_mono=None,
            timeout_f=30.0,
            brp069_poll_domain=None,
        )
    except mod.UpdateFailed:
        pass


# --- pure rule ---


def test_unreachable_issue_due_threshold() -> None:
    assert unreachable_issue_due(None, _T0) is False
    assert unreachable_issue_due(_T0, _T0 + UNREACHABLE_ISSUE_AFTER - timedelta(seconds=1)) is False
    assert unreachable_issue_due(_T0, _T0 + UNREACHABLE_ISSUE_AFTER) is True


# --- coordinator wiring ---


def test_issue_raised_once_after_threshold_then_cleared_on_success() -> None:
    mod = load_coordinator_module()
    coordinator = _coordinator(mod)
    with (
        patch.object(mod, "async_create_unreachable_issue") as create,
        patch.object(mod, "async_delete_unreachable_issue") as delete,
    ):
        _fail(coordinator, mod, _T0)
        _fail(coordinator, mod, _T0 + timedelta(minutes=29))
        create.assert_not_called()
        assert coordinator._failing_since == _T0

        _fail(coordinator, mod, _T0 + timedelta(minutes=30))
        _fail(coordinator, mod, _T0 + timedelta(minutes=45))
        create.assert_called_once_with(
            coordinator.hass, "entry-1", name="Salon", host="192.0.2.10"
        )
        assert coordinator._unreachable_issue_active is True

        coordinator._mark_poll_success()
        delete.assert_called_once_with(coordinator.hass, "entry-1")
        assert coordinator._failing_since is None
        assert coordinator._unreachable_issue_active is False
        assert coordinator._consecutive_poll_failures == 0

        # A fresh outage starts a new 30-minute window.
        _fail(coordinator, mod, _T0 + timedelta(hours=2))
        assert create.call_count == 1


def test_success_without_issue_does_not_delete() -> None:
    mod = load_coordinator_module()
    coordinator = _coordinator(mod)
    with patch.object(mod, "async_delete_unreachable_issue") as delete:
        _fail(coordinator, mod, _T0)
        coordinator._mark_poll_success()
    delete.assert_not_called()


# --- issues helpers (config_entry_id on 2026.11+, fallback before) ---


def _issues_module():
    load_coordinator_module()  # installs HA stubs when Home Assistant is absent
    return importlib.import_module("custom_components.daikin_local.issues")


def test_create_issue_passes_config_entry_id() -> None:
    issues = _issues_module()
    fake_ir = MagicMock()
    with patch.object(issues, "ir", fake_ir):
        issues.async_create_unreachable_issue(
            "hass", "entry-1", name="Salon", host="192.0.2.10"
        )
    fake_ir.async_create_issue.assert_called_once()
    args, kwargs = fake_ir.async_create_issue.call_args
    assert args[1:] == ("daikin_local", "device_unreachable_entry-1")
    assert kwargs["config_entry_id"] == "entry-1"
    assert kwargs["translation_key"] == "device_unreachable"
    assert kwargs["translation_placeholders"] == {"name": "Salon", "host": "192.0.2.10"}
    assert kwargs["is_fixable"] is False


def test_create_issue_falls_back_without_config_entry_id() -> None:
    """HA < 2026.11 rejects the config_entry_id keyword."""
    issues = _issues_module()
    seen: list[dict] = []

    def _legacy_create(hass, domain, issue_id, **kwargs):
        if "config_entry_id" in kwargs:
            raise TypeError("unexpected keyword argument 'config_entry_id'")
        seen.append(kwargs)

    fake_ir = MagicMock()
    fake_ir.async_create_issue.side_effect = _legacy_create
    with patch.object(issues, "ir", fake_ir):
        issues.async_create_unreachable_issue(
            "hass", "entry-1", name="Salon", host="192.0.2.10"
        )
    assert len(seen) == 1
    assert seen[0]["translation_key"] == "device_unreachable"


def test_delete_issue_uses_entry_scoped_id() -> None:
    issues = _issues_module()
    fake_ir = MagicMock()
    with patch.object(issues, "ir", fake_ir):
        issues.async_delete_unreachable_issue("hass", "entry-1")
    fake_ir.async_delete_issue.assert_called_once_with(
        "hass", "daikin_local", "device_unreachable_entry-1"
    )
