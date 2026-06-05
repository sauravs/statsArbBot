"""
Persistence for runtime bot-config overrides — the signal thresholds (issue #74).

The Option-B thresholds (entry/exit/stop) are otherwise process-only runtime
state (like the data-source toggle) and would reset to the env defaults on every
restart. This thin seam stores them in the long-existing ``BotConfigHistory``
table — append-only, latest-wins — so an operator's chosen thresholds survive an
API restart. One JSON row per change keyed ``"signal_thresholds"``, scoped to the
default (exchange, mode); the most recent row by ``changed_at`` is the active set.

Mirrors the other ``db/*_repository.py`` seams: tests inject a fake repo (no DB /
no generated client required); the process uses :class:`PrismaBotConfigRepository`
via :func:`get_bot_config_repository`.
"""

from __future__ import annotations

import json
import logging

import config

logger = logging.getLogger(__name__)

# The single BotConfigHistory key the threshold setter reads/writes.
SIGNAL_THRESHOLDS_KEY = "signal_thresholds"


class PrismaBotConfigRepository:
    """Prisma-backed implementation. Imports the generated client lazily."""

    async def save_thresholds(
        self, entry: float, exit: float, stop: float, *, exchange: str, mode: str
    ) -> None:
        """Append the thresholds as one JSON row (append-only history)."""
        from db.client import get_db

        db = await get_db()
        await db.botconfighistory.create(
            data={
                "exchange": exchange,
                "mode": mode,
                "key": SIGNAL_THRESHOLDS_KEY,
                "value": json.dumps({"entry": entry, "exit": exit, "stop": stop}),
            }
        )

    async def get_latest_thresholds(
        self, *, exchange: str, mode: str
    ) -> dict | None:
        """The most recently saved thresholds for (exchange, mode), or ``None``.

        A malformed/legacy row is treated as absent (logged, not raised) so a bad
        persisted value can never wedge startup."""
        from db.client import get_db

        db = await get_db()
        rows = await db.botconfighistory.find_many(
            where={"exchange": exchange, "mode": mode, "key": SIGNAL_THRESHOLDS_KEY},
            order=[{"changed_at": "desc"}],
            take=1,
        )
        if not rows:
            return None
        try:
            data = json.loads(rows[0].value)
            return {
                "entry": float(data["entry"]),
                "exit": float(data["exit"]),
                "stop": float(data["stop"]),
            }
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning("ignoring malformed persisted thresholds: %s", exc)
            return None


_repo: PrismaBotConfigRepository | None = None


def get_bot_config_repository() -> PrismaBotConfigRepository:
    """Return the process-wide bot-config repository singleton."""
    global _repo
    if _repo is None:
        _repo = PrismaBotConfigRepository()
    return _repo


async def load_persisted_thresholds() -> None:
    """Apply the latest persisted thresholds to ``config`` at startup (issue #74).

    Best-effort and self-healing: no saved row → keep the env defaults; a saved
    row that fails the current validation (e.g. bounds tightened in a later
    release) is logged and ignored rather than applied."""
    saved = await get_bot_config_repository().get_latest_thresholds(
        exchange=config.DEFAULT_EXCHANGE, mode=config.DEFAULT_MODE
    )
    if saved is None:
        return
    try:
        config.set_signal_thresholds(saved["entry"], saved["exit"], saved["stop"])
        logger.info("loaded persisted signal thresholds: %s", saved)
    except ValueError as exc:
        logger.warning("persisted thresholds rejected by validation: %s", exc)
