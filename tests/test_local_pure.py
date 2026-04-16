"""Tests for ``custom_components.daikin_local.pure`` (no Home Assistant)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import voluptuous as vol

from tests.daikin_pure_loader import ensure_daikin_pure_and_const_loaded

ensure_daikin_pure_and_const_loaded()

from custom_components.daikin_local.const import (  # noqa: E402
    CONF_ENERGY_GROUP_ID,
    CONF_ENERGY_GROUP_TOTAL_HISTORY_MASTER,
    CONF_CONNECTION_TIMEOUT,
    CONF_HISTORY_AUTO_SYNC_GRACE_MINUTES,
    CONF_HISTORY_HOURS_TO_CORRECT,
    CONF_HISTORY_SKIP_EXTRA_HOURS,
    CONF_POLL_INTERVAL_ENERGY_SEC,
    CONF_POLL_INTERVAL_SEC,
    CONF_POLL_INTERVAL_STATE_SEC,
    TIMEOUT_SEC,
)
from custom_components.daikin_local.pure import (  # noqa: E402
    ATTR_DAYS_AGO,
    build_service_schema,
    connection_timeout_sec,
    coordinator_poll_interval_sec,
    domain_poll_intervals_sec,
    group_has_master,
    history_auto_sync_deferred_by_grace,
    history_skip_hours_from_options,
    history_window_from_entry_and_overrides,
    lts_row_start_to_datetime_non_str,
    recent_completed_hours_by_local_date,
)

pytestmark = pytest.mark.local


def test_group_has_master_true_when_one_entry_marked() -> None:
    master = SimpleNamespace(
        options={
            CONF_ENERGY_GROUP_ID: "pac1",
            CONF_ENERGY_GROUP_TOTAL_HISTORY_MASTER: True,
        }
    )
    slave = SimpleNamespace(
        options={
            CONF_ENERGY_GROUP_ID: "pac1",
            CONF_ENERGY_GROUP_TOTAL_HISTORY_MASTER: False,
        }
    )
    assert group_has_master([master, slave], "pac1") is True


def test_group_has_master_false_when_no_master() -> None:
    a = SimpleNamespace(
        options={
            CONF_ENERGY_GROUP_ID: "pac1",
            CONF_ENERGY_GROUP_TOTAL_HISTORY_MASTER: False,
        }
    )
    assert group_has_master([a], "pac1") is False


def test_group_has_master_false_for_blank_group() -> None:
    master = SimpleNamespace(
        options={
            CONF_ENERGY_GROUP_ID: "x",
            CONF_ENERGY_GROUP_TOTAL_HISTORY_MASTER: True,
        }
    )
    assert group_has_master([master], "") is False
    assert group_has_master([master], "   ") is False


def test_history_skip_hours_prefers_new_option() -> None:
    opts = {CONF_HISTORY_SKIP_EXTRA_HOURS: 2}
    assert history_skip_hours_from_options(opts) == 3


def test_history_skip_hours_legacy_key() -> None:
    opts = {"history_skip_hours": 4}
    assert history_skip_hours_from_options(opts) == 4


def test_history_window_override_disables_clamp() -> None:
    options = {
        CONF_HISTORY_SKIP_EXTRA_HOURS: 0,
        CONF_HISTORY_HOURS_TO_CORRECT: 5,
    }
    skip, correct, clamp = history_window_from_entry_and_overrides(
        options,
        history_skip_extra_hours=0,
        history_hours_to_correct=None,
    )
    assert clamp is False
    assert skip == 1
    assert correct == 5


def test_history_window_uses_entry_when_no_service_override() -> None:
    options = {
        CONF_HISTORY_SKIP_EXTRA_HOURS: 1,
        CONF_HISTORY_HOURS_TO_CORRECT: 3,
    }
    skip, correct, clamp = history_window_from_entry_and_overrides(
        options,
        history_skip_extra_hours=None,
        history_hours_to_correct=None,
    )
    assert clamp is True
    assert skip == 2
    assert correct == 3


def test_history_auto_sync_grace_defers_start_of_hour() -> None:
    t = datetime(2026, 4, 16, 14, 4, tzinfo=timezone.utc)
    opts = {CONF_HISTORY_AUTO_SYNC_GRACE_MINUTES: 10}
    assert history_auto_sync_deferred_by_grace(t, opts) is True
    t_ok = datetime(2026, 4, 16, 14, 10, 0, tzinfo=timezone.utc)
    assert history_auto_sync_deferred_by_grace(t_ok, opts) is False


def test_history_auto_sync_grace_zero_never_defers() -> None:
    t = datetime(2026, 4, 16, 14, 0, tzinfo=timezone.utc)
    assert history_auto_sync_deferred_by_grace(t, {}) is False


def test_connection_timeout_fallback() -> None:
    assert connection_timeout_sec({}, {}) == TIMEOUT_SEC


def test_connection_timeout_options_override_data() -> None:
    assert (
        connection_timeout_sec(
            {CONF_CONNECTION_TIMEOUT: 10},
            {CONF_CONNECTION_TIMEOUT: 99},
        )
        == 99
    )


def test_coordinator_poll_interval_fallback() -> None:
    assert coordinator_poll_interval_sec({}, {}) == TIMEOUT_SEC


def test_coordinator_poll_interval_from_data() -> None:
    assert coordinator_poll_interval_sec({CONF_POLL_INTERVAL_SEC: 60}, {}) == 60


def test_domain_poll_intervals_defaults() -> None:
    assert domain_poll_intervals_sec({}) == (900, 90)


def test_domain_poll_intervals_from_options() -> None:
    opts = {
        CONF_POLL_INTERVAL_STATE_SEC: 120,
        CONF_POLL_INTERVAL_ENERGY_SEC: 45,
    }
    assert domain_poll_intervals_sec(opts) == (120, 45)


def test_lts_row_start_unix_timestamp() -> None:
    dt = lts_row_start_to_datetime_non_str(1_700_000_000.0)
    assert dt is not None
    assert dt.tzinfo is not None


def test_recent_completed_hours_mapping_fixed_now() -> None:
    tz = timezone.utc
    now = datetime(2024, 6, 15, 14, 30, tzinfo=tz)
    m = recent_completed_hours_by_local_date(
        now,
        skip_hours=2,
        hours_to_correct=3,
        clamp=True,
    )
    day = now.date()
    hours = m.get(day, set())
    assert 12 in hours and 11 in hours and 10 in hours


def test_service_schema_empty() -> None:
    schema = build_service_schema(vol.Coerce(bool))
    out = schema({})
    assert out[ATTR_DAYS_AGO] == 0


def test_service_schema_rejects_invalid_days_ago() -> None:
    schema = build_service_schema(vol.Coerce(bool))
    with pytest.raises(vol.Invalid):
        schema({ATTR_DAYS_AGO: 2})
