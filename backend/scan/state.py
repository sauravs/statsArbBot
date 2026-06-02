"""
Scan progress state — a single lock-guarded object shared by the scan task and
the status/start/reset endpoints.

Why this fixes the prototype's race: the reference mutated a module-level dict
from a thread-pool executor while request handlers read it concurrently, and two
`POST /scan/start` calls could both observe ``running=False`` and launch
overlapping scans. Here:

  * ``try_begin()`` is the only path that flips ``running`` True, and it does so
    atomically under an asyncio lock — so at most one scan ever runs;
  * every other mutation happens only from the single running scan task on the
    event loop (the orchestrator offloads CPU work with ``asyncio.to_thread`` but
    never writes state from the worker thread), so there is no cross-thread
    mutation to race on.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ScanState:
    running: bool = False
    phase: int = 0  # 0 idle · 1 starting · 2 fetching markets · 3 testing pairs · 4 done
    progress_msg: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    markets_fetched: int = 0
    total_markets: int = 0
    pairs_tested: int = 0
    pairs_found: int = 0
    total_pairs: int = 0
    timed_out: bool = False

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def _clear_counters(self) -> None:
        """Zero the per-run counters (shared by begin/reset so they can't drift)."""
        self.markets_fetched = 0
        self.total_markets = 0
        self.pairs_tested = 0
        self.pairs_found = 0
        self.total_pairs = 0
        self.timed_out = False

    # ── start guard ──────────────────────────────────────────────────────────

    async def try_begin(self) -> bool:
        """
        Atomically claim the scan. Returns False if one is already running, so the
        caller can answer 409 without launching a second scan.
        """
        async with self._lock:
            if self.running:
                return False
            self.running = True
            self.phase = 1
            self.progress_msg = "Starting scan…"
            self.started_at = _now_iso()
            self.completed_at = None
            self.error = None
            self._clear_counters()
            return True

    async def reset(self) -> None:
        """Clear state back to idle (only when no scan is running)."""
        async with self._lock:
            if self.running:
                return
            self.phase = 0
            self.progress_msg = ""
            self.started_at = None
            self.completed_at = None
            self.error = None
            self._clear_counters()

    # ── progress updates (called only from the running scan task) ─────────────

    def set_phase(self, phase: int, msg: str) -> None:
        self.phase = phase
        self.progress_msg = msg

    def update_markets(self, fetched: int, total: int) -> None:
        self.markets_fetched = fetched
        self.total_markets = total

    def update_pairs(self, tested: int, total: int, found: int) -> None:
        self.pairs_tested = tested
        self.total_pairs = total
        self.pairs_found = found

    def finish(self, msg: str, *, timed_out: bool = False) -> None:
        self.phase = 4
        self.running = False
        self.timed_out = timed_out
        self.completed_at = _now_iso()
        self.progress_msg = msg

    def fail(self, error: str) -> None:
        self.phase = 4  # terminal — a failed scan is not still mid-fetch/mid-test
        self.running = False
        self.error = error
        self.completed_at = _now_iso()
        self.progress_msg = f"Error: {error}"

    # ── read ──────────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Serialisable view for the status endpoint (omits the lock)."""
        return {
            "running": self.running,
            "phase": self.phase,
            "progress_msg": self.progress_msg,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "markets_fetched": self.markets_fetched,
            "total_markets": self.total_markets,
            "pairs_tested": self.pairs_tested,
            "pairs_found": self.pairs_found,
            "total_pairs": self.total_pairs,
            "timed_out": self.timed_out,
        }


# Single process-wide instance (the API runs one scan at a time).
SCAN_STATE = ScanState()
