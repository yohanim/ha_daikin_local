"""Pure helpers with no Home Assistant imports (unit-testable on any OS / venv).

Runtime code reuses these from ``services`` and ``coordinator`` so behaviour
stays single-sourced.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import voluptuous as vol

from .const import (
    CONF_CONNECTION_TIMEOUT,
    CONF_ENERGY_GROUP_ID,
    CONF_ENERGY_GROUP_TOTAL_HISTORY_MASTER,
    CONF_HISTORY_AUTO_SYNC_GRACE_MINUTES,
    CONF_HISTORY_HOURS_TO_CORRECT,
    CONF_HISTORY_SKIP_EXTRA_HOURS,
    CONF_INSERT_MISSING,
    CONF_POLL_INTERVAL_ENERGY_SEC,
    CONF_POLL_INTERVAL_SEC,
    CONF_POLL_INTERVAL_STATE_SEC,
    TIMEOUT_SEC,
)

# Service data field names (aligned with ``services.py`` / Home Assistant).
ATTR_DAYS_AGO = "days_ago"
ATTR_ENTITY_ID = "entity_id"


def group_has_master(entries: list[Any], group: str) -> bool:
    """True if some entry marks itself master for this non-empty group id."""
    g = group.strip()
    if not g:
        return False
    return any(
        (e.options.get(CONF_ENERGY_GROUP_ID) or "").strip() == g
        and bool(e.options.get(CONF_ENERGY_GROUP_TOTAL_HISTORY_MASTER, False))
        for e in entries
    )


def recent_completed_hours_by_local_date(
    now_local: datetime,
    *,
    include_extra_hour: bool = False,
    skip_hours: int = 2,
    hours_to_correct: int = 3,
    clamp: bool = True,
) -> dict[date, set[int]]:
    """Hour indices for completed local hours to (re)inject.

    ``now_local`` must be timezone-aware (e.g. from HA ``as_local(utcnow())``).
    """
    if clamp:
        skip_hours = max(1, int(skip_hours))
        hours_to_correct = max(0, int(hours_to_correct))
    else:
        skip_hours = int(skip_hours)
        hours_to_correct = int(hours_to_correct)

    mapping: dict[date, set[int]] = {}
    extra = 1 if include_extra_hour else 0
    for i in range(hours_to_correct + extra):
        t = now_local - timedelta(hours=skip_hours + i)
        mapping.setdefault(t.date(), set()).add(t.hour)
    return mapping


def history_skip_hours_from_options(options: dict) -> int:
    """Compute total hours to skip (includes current hour)."""
    if CONF_HISTORY_SKIP_EXTRA_HOURS in options:
        extra = int(options.get(CONF_HISTORY_SKIP_EXTRA_HOURS) or 0)
        return max(1, 1 + extra)

    legacy_total = int(options.get("history_skip_hours") or 2)
    return max(1, legacy_total)


def history_window_from_entry_and_overrides(
    options: dict,
    *,
    history_skip_extra_hours: int | None,
    history_hours_to_correct: int | None,
) -> tuple[int, int, bool]:
    """Return ``(skip_hours, hours_to_correct, clamp)`` for history imports."""
    override = (
        history_skip_extra_hours is not None or history_hours_to_correct is not None
    )
    clamp = not override
    if history_skip_extra_hours is not None:
        skip_hours = 1 + int(history_skip_extra_hours)
    else:
        skip_hours = history_skip_hours_from_options(options)
    if history_hours_to_correct is not None:
        hours_to_correct = int(history_hours_to_correct)
    else:
        hours_to_correct = int(options.get(CONF_HISTORY_HOURS_TO_CORRECT, 3))
    return skip_hours, hours_to_correct, clamp


def history_auto_sync_deferred_by_grace(
    now_local: datetime, options: dict
) -> bool:
    """Return True if auto history sync should wait (start-of-hour grace period)."""
    raw = options.get(CONF_HISTORY_AUTO_SYNC_GRACE_MINUTES, 0)
    try:
        grace = max(0, min(59, int(raw)))
    except (TypeError, ValueError):
        grace = 0
    if grace <= 0:
        return False
    return now_local.minute < grace


def lts_row_start_to_datetime_non_str(
    start: datetime | float | int | None,
) -> datetime | None:
    """Convert LTS row ``start`` when it is not a string (strings: use HA in coordinator)."""
    if start is None:
        return None
    if isinstance(start, datetime):
        return start
    if isinstance(start, (int, float)):
        return datetime.fromtimestamp(float(start), tz=timezone.utc)
    return None


def connection_timeout_sec(entry_data: dict, entry_options: dict) -> int:
    """HTTP request timeout (seconds): options override data when set."""
    return (
        entry_options.get(CONF_CONNECTION_TIMEOUT)
        or entry_data.get(CONF_CONNECTION_TIMEOUT)
        or TIMEOUT_SEC
    )


def coordinator_poll_interval_sec(entry_data: dict, entry_options: dict) -> int:
    """Coordinator tick when not using BRP069 energy cadence (seconds)."""
    return (
        entry_options.get(CONF_POLL_INTERVAL_SEC)
        or entry_data.get(CONF_POLL_INTERVAL_SEC)
        or TIMEOUT_SEC
    )


def domain_poll_intervals_sec(entry_options: dict) -> tuple[int, int]:
    """Return ``(state_interval_s, energy_interval_s)`` for BRP069 domain polling."""
    state_s = int(entry_options.get(CONF_POLL_INTERVAL_STATE_SEC) or 900)
    energy_s = int(entry_options.get(CONF_POLL_INTERVAL_ENERGY_SEC) or 90)
    return state_s, energy_s


def build_service_schema(insert_missing_validator: Any) -> vol.Schema:
    """Build the service call schema; ``insert_missing_validator`` is ``cv.boolean`` in production."""
    return vol.Schema(
        {
            vol.Optional(ATTR_DAYS_AGO, default=0): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=1)
            ),
            vol.Optional(ATTR_ENTITY_ID): vol.Coerce(str),
            vol.Optional(CONF_INSERT_MISSING): insert_missing_validator,
            vol.Optional(CONF_HISTORY_SKIP_EXTRA_HOURS): vol.Coerce(int),
            vol.Optional(CONF_HISTORY_HOURS_TO_CORRECT): vol.Coerce(int),
        }
    )
