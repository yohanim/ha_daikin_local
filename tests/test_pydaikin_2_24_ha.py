"""pydaikin 2.22-2.24 behaviour against real Home Assistant and pydaikin classes.

Covers the adaptive setpoint step (and its restore across restarts), the write
errors pydaikin raises since 2.22.1, and the BRP084 compressor-running sensor.
Devices are built with a mock session, so nothing touches the network.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant")
pytest.importorskip("pydaikin")

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.restore_state import RestoredExtraData
from pydaikin.daikin_airbase import DaikinAirBase
from pydaikin.daikin_brp069 import DaikinBRP069
from pydaikin.daikin_brp084 import DaikinBRP084
from pydaikin.exceptions import (
    DaikinCommandRejected,
    DaikinException,
    DaikinVerificationError,
)

from custom_components.daikin_local import binary_sensor
from custom_components.daikin_local.climate import (
    DaikinClimate,
    DaikinZoneClimate,
    target_temperature_step,
)
from custom_components.daikin_local.entity import async_execute_daikin_command

pytestmark = pytest.mark.requires_ha

FIRMWARE = "3_3_9"


def _device(cls, **values):
    device = cls("192.0.2.10", session=MagicMock())
    device.values["mac"] = "aabbccddeeff"
    device.values["ver"] = FIRMWARE
    for key, value in values.items():
        device.values[key] = value
    return device


def _coordinator(device) -> MagicMock:
    coordinator = MagicMock()
    coordinator.device = device
    return coordinator


# --- setpoint step ---


def test_step_brp069_starts_at_half_degree() -> None:
    assert target_temperature_step(_device(DaikinBRP069)) == 0.5


def test_step_brp069_follows_inferred_whole_degree() -> None:
    device = _device(DaikinBRP069)
    device.target_temperature_step_status = "inferred"
    assert target_temperature_step(device) == 1.0


def test_step_airbase_is_whole_degree() -> None:
    assert target_temperature_step(_device(DaikinAirBase)) == 1.0


def test_step_brp084_keeps_half_degree() -> None:
    """pydaikin reports its generic 1.0, but BRP084 encodes half degrees."""
    assert target_temperature_step(_device(DaikinBRP084)) == 0.5


def test_climate_entity_exposes_dynamic_step() -> None:
    device = _device(DaikinBRP069)
    entity = DaikinClimate(_coordinator(device))
    assert entity.target_temperature_step == 0.5
    device.target_temperature_step_status = "inferred"
    assert entity.target_temperature_step == 1.0


def test_zone_step_is_whole_degree() -> None:
    """Zone setpoints are sent rounded to whole degrees."""
    entity = DaikinZoneClimate(_coordinator(_device(DaikinAirBase)), 0)
    assert entity.target_temperature_step == 1.0


# --- learned step restored across restarts ---


def test_extra_restore_data_keys_status_by_firmware() -> None:
    device = _device(DaikinBRP069)
    device.target_temperature_step_status = "confirmed"
    data = DaikinClimate(_coordinator(device)).extra_restore_state_data
    assert data is not None
    assert data.as_dict() == {
        "target_temperature_step_status": "confirmed",
        "firmware": FIRMWARE,
    }


def test_no_restore_data_without_adaptive_step() -> None:
    entity = DaikinClimate(_coordinator(_device(DaikinBRP084)))
    assert entity.extra_restore_state_data is None


@pytest.mark.parametrize(
    ("saved_firmware", "expected"),
    [(FIRMWARE, "inferred"), ("3_3_8", "unknown")],
)
async def test_added_to_hass_restores_learned_step(
    saved_firmware: str, expected: str
) -> None:
    device = _device(DaikinBRP069)
    entity = DaikinClimate(_coordinator(device))
    entity.async_get_last_extra_data = AsyncMock(
        return_value=RestoredExtraData(
            {
                "target_temperature_step_status": "inferred",
                "firmware": saved_firmware,
            }
        )
    )
    await entity.async_added_to_hass()
    assert device.target_temperature_step_status == expected


# --- write errors (pydaikin >= 2.22.1) ---


class _Coordinator:
    async def async_execute_command(self, command) -> None:
        await command()


@pytest.mark.parametrize(
    ("error", "translation_key", "placeholders"),
    [
        (DaikinCommandRejected("PARAM NG"), "command_rejected", {"ret": "PARAM NG"}),
        (
            DaikinVerificationError("23.5", "23"),
            "setpoint_not_applied",
            {"requested": "23.5", "actual": "23"},
        ),
        (
            DaikinException("boom"),
            "error_communicating",
            {"error": "boom"},
        ),
    ],
)
async def test_command_errors_are_translated(
    error: Exception, translation_key: str, placeholders: dict[str, str]
) -> None:
    async def _command() -> None:
        raise error

    with pytest.raises(HomeAssistantError) as raised:
        await async_execute_daikin_command(_Coordinator(), _command)
    assert raised.value.translation_key == translation_key
    assert raised.value.translation_placeholders == placeholders


# --- BRP084 compressor running ---


async def test_compressor_running_sensor_on_brp084() -> None:
    device = _device(DaikinBRP084, compressor_running="1")
    entry = MagicMock()
    entry.runtime_data = _coordinator(device)
    added: list = []
    await binary_sensor.async_setup_entry(MagicMock(), entry, added.extend)
    assert len(added) == 1
    assert added[0].unique_id == "aabbccddeeff-compressor_running"
    assert added[0].is_on is True


@pytest.mark.parametrize(
    "device",
    [
        pytest.param(lambda: _device(DaikinBRP069), id="brp069"),
        pytest.param(lambda: _device(DaikinBRP084), id="brp084-without-e_2006"),
    ],
)
async def test_no_compressor_running_sensor_without_support(device) -> None:
    entry = MagicMock()
    entry.runtime_data = _coordinator(device())
    added: list = []
    await binary_sensor.async_setup_entry(MagicMock(), entry, added.extend)
    assert added == []
