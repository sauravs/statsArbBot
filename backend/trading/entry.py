"""
Entry scan (PRD §3.2, F5.2) — one pass that opens new pairs on live signals.

For each cointegrated pair from the latest scan, recompute the *current* rolling
Z from live prices and, where ``|Z| ≥ entry_threshold``, open a dollar-neutral
two-leg position via :class:`~trading.bot_agent.BotAgent`. Guards (carried from the
reference bot, now DB-backed):

  * **Collateral guard** — no new entries when free collateral < ``USD_MIN_COLLATERAL``;
    re-checked after every open so a run stops as soon as it would over-commit.
  * **Already-open guard** — skip a pair already OPEN in the DB or with either leg
    already holding an on-exchange position.
  * **Approval gate** — every signal is offered to the :class:`ApprovalGate` before
    any order is placed (stub auto-approves now; Telegram in Phase 9).

Sides come from ``statcore.evaluate_entry`` (single source of truth). Sizing is
fixed notional per leg (``USD_PER_TRADE / fill-reference price``).

The data client (live prices for Z) and the trade client (account/orders) are
separate by design: prices always come from the mainnet indexer for real
liquidity, while orders hit the account's network (testnet for forward_test).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import config
from marketdata.pair_series import current_pair_snapshot
from statcore import evaluate_entry
from trading.alerts import Alerter
from trading.approval import ApprovalGate
from trading.bot_agent import BotAgent
from trading.broker import TradeClient

logger = logging.getLogger(__name__)


async def scan_for_entries(
    *,
    trade_client: TradeClient,
    data_client,  # PriceSource (read-only live prices)
    repo,  # live repository
    gate: ApprovalGate,
    alerter: Alerter,
    pairs: list[dict],
    session_id: str,
    exchange: str,
    mode: str,
    entry_threshold: float | None = None,
    window: int | None = None,
    usd_per_trade: float | None = None,
    min_collateral: float | None = None,
    now=None,
) -> dict:
    """Run one entry-scan pass. Returns a summary dict (no exceptions escape)."""
    entry_threshold = entry_threshold if entry_threshold is not None else config.ZSCORE_THRESH
    usd_per_trade = usd_per_trade if usd_per_trade is not None else config.USD_PER_TRADE
    min_collateral = min_collateral if min_collateral is not None else config.USD_MIN_COLLATERAL

    outcomes: list[dict] = []
    opened = 0

    free_collateral = await trade_client.get_free_collateral()
    if free_collateral < min_collateral:
        msg = (
            f"Insufficient free collateral ${free_collateral:,.2f} "
            f"(min ${min_collateral:,.2f}) — entry scan paused."
        )
        logger.info(msg)
        await alerter.notify(msg)
        return {
            "opened": 0,
            "evaluated": 0,
            "free_collateral": free_collateral,
            "collateral_ok": False,
            "message": msg,
            "outcomes": [],
        }

    open_trades = await repo.get_open_trades(exchange=exchange, mode=mode)
    open_pairs = {(t["base_market"], t["quote_market"]) for t in open_trades}
    positions = await trade_client.get_open_positions()

    evaluated = 0
    for pair in pairs:
        base = pair["base_market"]
        quote = pair["quote_market"]

        if (base, quote) in open_pairs:
            outcomes.append({"pair": [base, quote], "action": "skipped", "reason": "already_open"})
            continue
        if base in positions or quote in positions:
            outcomes.append({"pair": [base, quote], "action": "skipped", "reason": "leg_position_exists"})
            continue

        evaluated += 1
        snap = await current_pair_snapshot(
            data_client,
            base_market=base,
            quote_market=quote,
            hedge_ratio=pair["hedge_ratio"],
            intercept=pair.get("intercept", 0.0) or 0.0,
            window=window,
            now=now,
        )
        if snap is None:
            outcomes.append({"pair": [base, quote], "action": "skipped", "reason": "no_snapshot"})
            continue

        signal = evaluate_entry(snap.z_score, entry_threshold=entry_threshold)
        if signal is None:
            outcomes.append(
                {"pair": [base, quote], "action": "skipped", "reason": "no_signal", "z_score": snap.z_score}
            )
            continue

        base_side = signal.base_side.value
        quote_side = signal.quote_side.value
        base_size = usd_per_trade / snap.base_price
        quote_size = usd_per_trade / snap.quote_price

        approved = await gate.request(
            {
                "kind": "entry",
                "exchange": exchange,
                "mode": mode,
                "base_market": base,
                "quote_market": quote,
                "base_side": base_side,
                "quote_side": quote_side,
                "z_score": snap.z_score,
            }
        )
        if not approved:
            outcomes.append({"pair": [base, quote], "action": "rejected", "z_score": snap.z_score})
            continue

        agent = BotAgent(
            trade_client,
            alerter,
            base_market=base,
            quote_market=quote,
            base_side=base_side,
            quote_side=quote_side,
            base_size=base_size,
            quote_size=quote_size,
            entry_z_score=snap.z_score,
            hedge_ratio=pair["hedge_ratio"],
            half_life=pair["half_life"],
        )
        result = await agent.open_trades()
        snapshot = agent.entry_snapshot()

        if result == "LIVE":
            trade = await repo.create_trade(
                {
                    "session_id": session_id,
                    "exchange": exchange,
                    "mode": mode,
                    "status": "OPEN",
                    "opened_at": now or datetime.now(timezone.utc),
                    **snapshot,
                }
            )
            opened += 1
            open_pairs.add((base, quote))
            outcomes.append(
                {"pair": [base, quote], "action": "opened", "z_score": snap.z_score, "trade_id": trade["id"]}
            )

            # Re-check collateral; stop if a further open would over-commit.
            free_collateral = await trade_client.get_free_collateral()
            if free_collateral < min_collateral:
                logger.info("Collateral guard tripped after open — stopping entry scan.")
                break
        else:
            # The open failed mid-flight; BotAgent already attempted the failsafe
            # (and raised CODE-RED if even that failed). Record the attempt.
            trade = await repo.create_trade(
                {
                    "session_id": session_id,
                    "exchange": exchange,
                    "mode": mode,
                    "status": "ERROR",
                    "opened_at": now or datetime.now(timezone.utc),
                    "error": agent.error or "open failed",
                    **snapshot,
                }
            )
            outcomes.append(
                {"pair": [base, quote], "action": "error", "z_score": snap.z_score, "trade_id": trade["id"]}
            )

    return {
        "opened": opened,
        "evaluated": evaluated,
        "free_collateral": free_collateral,
        "collateral_ok": True,
        "message": f"Entry scan complete — {opened} opened, {evaluated} evaluated.",
        "outcomes": outcomes,
    }
