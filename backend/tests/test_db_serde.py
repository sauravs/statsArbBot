"""Unit tests for the shared Prisma serialisation helpers (Phase 10, db/serde.py).

The single home for "how a model record becomes JSON" — extracted from the five
repository copies (issue #19).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from db.serde import enum_value, iso


def test_iso_renders_datetime():
    dt = datetime(2026, 6, 4, 12, 30, tzinfo=timezone.utc)
    assert iso(dt) == dt.isoformat()


def test_iso_passes_none_through():
    assert iso(None) is None


def test_iso_strs_non_datetime():
    # Matches the prior per-repo behaviour (defensive fallback).
    assert iso(42) == "42"


class _Mode(str, Enum):
    FORWARD = "forward_test"


def test_enum_value_unwraps_enum():
    assert enum_value(_Mode.FORWARD) == "forward_test"


def test_enum_value_passes_plain_value_through():
    assert enum_value("production") == "production"
    assert enum_value(None) is None
