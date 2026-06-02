"""
Validation-report data structures for the historical-data ingest (Phase 2.5).

The ingest gate requires a report that shows, per market, the cleaned row count
and the bars rejected by each rule, plus which markets were excluded for
insufficient coverage. These dataclasses hold that accounting and render it to
Markdown for ``data/ingest_report.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .cleaning import CleaningStats


@dataclass
class MarketReport:
    """One OHLCV market's cleaning + ingest outcome."""

    market: str
    source_dir: str
    stats: CleaningStats
    included: bool
    cached_rows: int = 0
    first_ts: str | None = None
    last_ts: str | None = None
    exclusion_reason: str | None = None  # e.g. "low_coverage", "no_clean_rows", "load_error"


@dataclass
class FundingReport:
    """One market's funding-rate ingest outcome."""

    market: str
    source_dir: str
    raw_rows: int
    duplicates_dropped: int
    clean_rows: int
    cached_rows: int = 0


@dataclass
class IngestReport:
    """Aggregate report across all markets in an ingest run."""

    min_coverage_rows: int
    exchange: str = "dydx"
    resolution: str = "1HOUR"
    dry_run: bool = False
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    markets: list[MarketReport] = field(default_factory=list)
    funding: list[FundingReport] = field(default_factory=list)

    # ── aggregates ───────────────────────────────────────────────────────────

    @property
    def markets_included(self) -> int:
        return sum(1 for m in self.markets if m.included)

    @property
    def markets_excluded(self) -> int:
        return sum(1 for m in self.markets if not m.included)

    @property
    def total_raw_rows(self) -> int:
        return sum(m.stats.raw_rows for m in self.markets)

    @property
    def total_clean_rows(self) -> int:
        return sum(m.stats.clean_rows for m in self.markets)

    @property
    def total_dropped_rows(self) -> int:
        return sum(m.stats.dropped_total for m in self.markets)

    @property
    def total_cached_rows(self) -> int:
        return sum(m.cached_rows for m in self.markets)

    @property
    def total_funding_cached(self) -> int:
        return sum(f.cached_rows for f in self.funding)

    # ── rendering ──────────────────────────────────────────────────────────────

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append("# Historical Data Ingest — Validation Report")
        lines.append("")
        lines.append(f"- **Generated:** {self.generated_at.isoformat()}")
        lines.append(f"- **Exchange / resolution:** {self.exchange} / {self.resolution}")
        lines.append(f"- **Min coverage (clean rows):** {self.min_coverage_rows}")
        lines.append(f"- **Mode:** {'DRY RUN (no DB writes)' if self.dry_run else 'wrote to OhlcvCache'}")
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Markets scanned: **{len(self.markets)}** "
                     f"(included **{self.markets_included}**, excluded **{self.markets_excluded}**)")
        lines.append(f"- Raw OHLCV rows: **{self.total_raw_rows:,}**")
        lines.append(f"- Clean OHLCV rows: **{self.total_clean_rows:,}** "
                     f"(dropped **{self.total_dropped_rows:,}**)")
        lines.append(f"- OHLCV rows cached: **{self.total_cached_rows:,}**")
        if self.funding:
            lines.append(f"- Funding rows cached: **{self.total_funding_cached:,}** "
                         f"across {len(self.funding)} markets")
        lines.append("")
        lines.append("## Per-market OHLCV")
        lines.append("")
        header = (
            "| Market | Dir | Raw | Dupes | Non-pos | Inconsist. | Zero-vol | Flat | "
            "Clean | Gaps | MaxGap(h) | Cached | Included | Reason |"
        )
        lines.append(header)
        lines.append("|" + "---|" * 14)
        # Included first (by clean rows desc), then excluded.
        ordered = sorted(
            self.markets,
            key=lambda m: (not m.included, -m.stats.clean_rows, m.market),
        )
        for m in ordered:
            s = m.stats
            lines.append(
                f"| {m.market} | {m.source_dir} | {s.raw_rows} | {s.duplicates_dropped} | "
                f"{s.dropped_nonpositive} | {s.dropped_inconsistent} | {s.dropped_zero_volume} | "
                f"{s.dropped_flat} | {s.clean_rows} | {s.gap_count} | {s.largest_gap_hours} | "
                f"{m.cached_rows} | {'yes' if m.included else 'no'} | {m.exclusion_reason or ''} |"
            )
        if self.funding:
            lines.append("")
            lines.append("## Per-market funding")
            lines.append("")
            lines.append("| Market | Dir | Raw | Dupes | Clean | Cached |")
            lines.append("|" + "---|" * 6)
            for f in sorted(self.funding, key=lambda x: x.market):
                lines.append(
                    f"| {f.market} | {f.source_dir} | {f.raw_rows} | "
                    f"{f.duplicates_dropped} | {f.clean_rows} | {f.cached_rows} |"
                )
        lines.append("")
        return "\n".join(lines)
