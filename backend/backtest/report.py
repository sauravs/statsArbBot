"""
Markdown backtest report (PRD F8.3) — pure, no DB/IO.

Renders a finished (or partial) strategy row into a self-contained markdown report:
the parameters, headline results, per-window walk-forward table, per-pair P&L, and
the exit-reason breakdown. Stored on ``Strategy.report_md`` and shown in the UI's
reports viewer.
"""

from __future__ import annotations


def _fmt_usd(v) -> str:
    if v is None:
        return "—"
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def _fmt_pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _iso_day(value) -> str:
    if not value:
        return "—"
    return str(value)[:10]


def build_report(row: dict) -> str:
    """Build the markdown report for a strategy backtest result."""
    name = row.get("name") or row.get("id", "")
    lines: list[str] = []
    lines.append(f"# Backtest Report — {name}")
    lines.append("")
    if row.get("description"):
        lines.append(f"_{row['description']}_")
        lines.append("")

    status = row.get("status", "")
    rank = row.get("rank")
    lines.append(f"**Status:** {status}" + (f" · **Rank:** #{rank}" if rank else ""))
    lines.append("")

    # ── Parameters ────────────────────────────────────────────────────────────
    lines.append("## Parameters")
    lines.append("")
    lines.append("| Parameter | Value |")
    lines.append("|---|---|")
    lines.append(f"| Scan window | {row.get('scan_window_days')} d |")
    lines.append(f"| Trade window | {row.get('trade_window_days')} d |")
    lines.append(f"| Z-score window | {row.get('zscore_window')} |")
    lines.append(f"| Entry \\|Z\\| ≥ | {row.get('entry_threshold')} |")
    lines.append(f"| Exit \\|Z\\| < | {row.get('exit_threshold')} |")
    lines.append(f"| Stop \\|Z\\| ≥ | {row.get('stop_threshold')} |")
    lines.append(f"| Max half-life | {row.get('max_half_life_h')} h |")
    lines.append(f"| p-value max | {row.get('pvalue_max')} |")
    lines.append(f"| Starting capital | {_fmt_usd(row.get('starting_capital'))} |")
    lines.append(f"| USD per trade | {_fmt_usd(row.get('usd_per_trade'))} |")
    lines.append("")

    # ── Results ───────────────────────────────────────────────────────────────
    lines.append("## Results")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Net P&L | {_fmt_usd(row.get('net_pnl'))} |")
    lines.append(f"| Final capital | {_fmt_usd(row.get('final_capital'))} |")
    lines.append(f"| Total trades | {row.get('total_trades', 0)} |")
    lines.append(f"| Win rate | {_fmt_pct(row.get('win_rate'))} |")
    lines.append(
        f"| Windows processed | {row.get('processed_windows', 0)}"
        f"/{row.get('total_windows', 0)} |"
    )
    span = ""
    if row.get("start_time") and row.get("end_time"):
        span = f"{_iso_day(row['start_time'])} → {_iso_day(row['end_time'])}"
    if span:
        lines.append(f"| History span | {span} |")
    lines.append("")

    # ── Per-window walk-forward ──────────────────────────────────────────────
    per_window = row.get("per_window") or []
    lines.append("## Walk-Forward Windows")
    lines.append("")
    if not per_window:
        lines.append("_No windows processed._")
    else:
        lines.append("| # | Scan | Trade | Pairs | Trades | Net P&L |")
        lines.append("|---|---|---|---|---|---|")
        for w in per_window:
            scan = f"{_iso_day(w.get('scan_start'))}→{_iso_day(w.get('scan_end'))}"
            trade = f"{_iso_day(w.get('trade_start'))}→{_iso_day(w.get('trade_end'))}"
            lines.append(
                f"| {w.get('index')} | {scan} | {trade} | {w.get('pairs', 0)} | "
                f"{w.get('trades', 0)} | {_fmt_usd(w.get('net_pnl'))} |"
            )
    lines.append("")

    # ── Per-pair P&L ──────────────────────────────────────────────────────────
    per_pair = row.get("per_pair_pnl") or {}
    lines.append("## Per-Pair P&L")
    lines.append("")
    if not per_pair:
        lines.append("_No closed trades._")
    else:
        lines.append("| Pair | Trades | Wins | Net P&L |")
        lines.append("|---|---|---|---|")
        for pair, b in sorted(
            per_pair.items(), key=lambda kv: kv[1]["net_pnl"], reverse=True
        ):
            lines.append(
                f"| {pair} | {b.get('trades', 0)} | {b.get('wins', 0)} | "
                f"{_fmt_usd(b.get('net_pnl'))} |"
            )
    lines.append("")

    # ── Exit reasons ──────────────────────────────────────────────────────────
    exit_reasons = row.get("exit_reasons") or {}
    lines.append("## Exit Reasons")
    lines.append("")
    if not exit_reasons:
        lines.append("_No exits._")
    else:
        lines.append("| Reason | Count |")
        lines.append("|---|---|")
        for reason, count in sorted(
            exit_reasons.items(), key=lambda kv: kv[1], reverse=True
        ):
            lines.append(f"| {reason} | {count} |")
    lines.append("")

    return "\n".join(lines)
