"""
Leaf converters for turning a Prisma model record into a JSON-safe dict.

Every ``Prisma*Repository`` builds its own ``_to_dict`` shape (those differ per
model), but the two leaf conversions are identical everywhere: a ``datetime``
becomes an ISO-8601 string and a Prisma enum becomes its ``.value``. Phase 10
consolidates the five copies that had accreted across the repositories (issue
#19) into this one seam, so the "how a row becomes JSON" contract — UTC handling,
``None`` passthrough, enum unwrapping — lives in a single, directly-testable place.
"""

from __future__ import annotations

from datetime import datetime


def iso(value) -> str | None:
    """Render a datetime as an ISO-8601 string; pass ``None`` and non-datetimes
    through (the latter ``str()``-ified, matching the prior per-repo behaviour)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def enum_value(value):
    """Unwrap a Prisma enum to its ``.value``; pass plain values through."""
    return getattr(value, "value", value)
