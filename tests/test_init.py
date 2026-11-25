"""Tests for custom_components.daikin_local.__init__ (no full Home Assistant)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.coordinator_test_support import load_init_module
from tests.daikin_pure_loader import ensure_daikin_pure_and_const_loaded

ensure_daikin_pure_and_const_loaded()

pytestmark = pytest.mark.local


# ---------------------------------------------------------------------------
# Helpers shared by migration tests
# ---------------------------------------------------------------------------


def _entry(
    *,
    version: int,
    data: dict | None = None,
    options: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        version=version,
        data=data or {},
        options=options or {},
        entry_id="test-entry",
    )


def _hass() -> SimpleNamespace:
    """Minimal hass stub that applies updates to the entry in place."""
    applied: list[dict] = []

    def _update(entry, **kwargs):
        applied.append(dict(kwargs))
        for k, v in kwargs.items():
            setattr(entry, k, v)

    return SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=_update),
        _applied=applied,
    )


# ---------------------------------------------------------------------------
# async_migrate_entry
# ---------------------------------------------------------------------------


async def test_unknown_version_raises() -> None:
    mod = load_init_module()
    with pytest.raises(mod.ConfigEntryError) as raised:
        await mod.async_migrate_entry(_hass(), _entry(version=99))
    assert raised.value.translation_key == "migration_unknown_version"
    assert raised.value.translation_placeholders == {"version": "99"}


async def test_unknown_version_does_not_mutate_entry() -> None:
    mod = load_init_module()
    hass = _hass()
    with pytest.raises(mod.ConfigEntryError):
        await mod.async_migrate_entry(hass, _entry(version=99, data={"key": "v"}))
    assert hass._applied == []


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
async def test_known_version_migrates_to_current_in_one_call(version: int) -> None:
    """Home Assistant calls the migration once: every step must run in it."""
    mod = load_init_module()
    hass = _hass()
    entry = _entry(
        version=version,
        data={"api_key": "x", "timeout": 30, "host": "h"},
        options={"history_skip_hours": 2, "history_sync_minutes_after_hour": 5, "timeout": 30},
    )
    result = await mod.async_migrate_entry(hass, entry)
    assert result is None
    assert entry.version == mod.CONFIG_ENTRY_VERSION
    assert [step["version"] for step in hass._applied] == list(
        range(version + 1, mod.CONFIG_ENTRY_VERSION + 1)
    )


async def test_v1_migration_reaches_final_layout() -> None:
    mod = load_init_module()
    entry = _entry(
        version=1,
        data={"api_key": "s", "timeout": 45, "host": "h", "onecta_client_id": "c"},
        options={"history_skip_hours": 3},
    )
    await mod.async_migrate_entry(_hass(), entry)
    assert entry.data == {
        "host": "h",
        "connection_timeout": 45,
        "poll_interval_sec": 45,
    }
    assert entry.options == {"history_skip_extra_hours": 2}


async def test_v1_drops_credential_keys() -> None:
    mod = load_init_module()
    hass = _hass()
    entry = _entry(version=1, data={"api_key": "s", "password": "p", "uuid": "u", "host": "h"})
    await mod.async_migrate_entry(hass, entry)
    new_data = hass._applied[0]["data"]
    assert "api_key" not in new_data
    assert "password" not in new_data
    assert "uuid" not in new_data
    assert "host" in new_data


async def test_v2_renames_skip_hours() -> None:
    mod = load_init_module()
    hass = _hass()
    entry = _entry(version=2, options={"history_skip_hours": 3})
    await mod.async_migrate_entry(hass, entry)
    new_opts = hass._applied[0]["options"]
    assert "history_skip_hours" not in new_opts
    assert new_opts["history_skip_extra_hours"] == 2  # max(0, 3-1)


async def test_v4_splits_timeout_into_connection_and_poll() -> None:
    mod = load_init_module()
    hass = _hass()
    entry = _entry(version=4, data={"timeout": 45, "host": "h"}, options={})
    await mod.async_migrate_entry(hass, entry)
    new_data = hass._applied[0]["data"]
    assert new_data["connection_timeout"] == 45
    assert new_data["poll_interval_sec"] == 45
    assert "timeout" not in new_data


async def test_v5_drops_onecta_keys() -> None:
    mod = load_init_module()
    hass = _hass()
    entry = _entry(
        version=5,
        data={"host": "h", "onecta_cloud_fan_enabled": True, "onecta_client_id": "cid"},
        options={"onecta_refresh_token": "tok"},
    )
    await mod.async_migrate_entry(hass, entry)
    assert "onecta_cloud_fan_enabled" not in hass._applied[0]["data"]
    assert "onecta_refresh_token" not in hass._applied[0]["options"]
    assert "host" in hass._applied[0]["data"]


# ---------------------------------------------------------------------------
# async_setup — services registered once at domain level
# ---------------------------------------------------------------------------


async def test_async_setup_returns_true_and_calls_setup_services() -> None:
    mod = load_init_module()
    calls: list[int] = []

    async def _fake(_hass):
        calls.append(1)

    with patch.object(mod, "async_setup_services", side_effect=_fake):
        result = await mod.async_setup(MagicMock(), {})

    assert result is True
    assert calls == [1]

