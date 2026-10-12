from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from db_env import json_safe_value


def test_json_safe_value_none():
    assert json_safe_value(None) is None


def test_json_safe_value_decimal():
    assert json_safe_value(Decimal("1.50")) == 1.5


def test_json_safe_value_datetime():
    assert json_safe_value(datetime(2024, 1, 2, 3, 4, 5)) == "2024-01-02 03:04:05"


def test_json_safe_value_date():
    assert json_safe_value(date(2024, 1, 2)) == "2024-01-02"


def test_json_safe_value_bytes():
    assert json_safe_value(b"abc") == "abc"


def test_json_safe_value_int_passthrough():
    assert json_safe_value(7) == 7
