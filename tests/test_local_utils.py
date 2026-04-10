"""Tests for ``utils.py`` (stdlib only; no integration ``__init__``)."""

from __future__ import annotations

import pytest

from tests.daikin_pure_loader import load_utils_standalone

_utils = load_utils_standalone()
parse_daikin_list = _utils.parse_daikin_list
calculate_energy_sum = _utils.calculate_energy_sum

pytestmark = pytest.mark.local


def test_parse_daikin_list_slash_string() -> None:
    assert parse_daikin_list("0/1/2/3") == [0, 1, 2, 3]


def test_parse_daikin_list_keeps_zeros() -> None:
    assert parse_daikin_list("0/0/5") == [0, 0, 5]


def test_parse_daikin_list_invalid_string() -> None:
    assert parse_daikin_list("not_a_number/1") == []


def test_parse_daikin_list_from_list() -> None:
    assert parse_daikin_list([1, 2, 3]) == [1, 2, 3]


def test_parse_daikin_list_empty_string_edge() -> None:
    assert parse_daikin_list("") == []


def test_calculate_energy_sum_empty() -> None:
    assert calculate_energy_sum([]) == 0.0


def test_calculate_energy_sum_units() -> None:
    assert calculate_energy_sum([10, 5]) == 1.5
