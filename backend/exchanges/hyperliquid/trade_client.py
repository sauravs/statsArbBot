"""
Hyperliquid trade-execution client (branch `hyperliquid`, Slice 4) — order
placement, position/account queries, cancel, implementing the
:class:`~trading.broker.TradeClient` protocol.

Side-effecting counterpart to the read-only ``HyperliquidDataClient``. Wraps the
official ``hyperliquid-python-sdk`` (``Exchange`` for signed actions, ``Info`` for
account queries). EIP-712 signing is handled by the SDK; we only supply the wallet.

Two structural choices:
  * **The SDK is synchronous** (eth_account + requests), but the engine drives an
    async ``TradeClient``. Every SDK call is therefore run in a worker thread via
    ``asyncio.to_thread`` so it never blocks the event loop.
  * ``Exchange`` / ``Info`` are **injected** (built in :meth:`connect`), so tests
    drive the whole client with fakes — no SDK, network, or wallet — exactly like
    the dYdX client's ``FakeTradeClient`` gate.

Like the dYdX client, queries return safe empties and placement returns ``None`` on
failure (never raises into the engine). The SDK is imported lazily inside
:meth:`connect` so importing this module never requires it installed.

Orders are market orders via the SDK helpers (``market_open`` / ``market_close``),
which apply the venue's size/price rounding and an aggressive IOC price within
``slippage``. A live testnet run needs a funded testnet wallet + key — see
docs/HYPERLIQUID_PROGRESS.md (Slice 4b).
"""

from __future__ import annotations

import asyncio
import logging

import config
from trading.broker import OrderResult, Position

logger = logging.getLogger(__name__)


class HyperliquidTradeClient:
    """Live Hyperliquid account/order client. Build via :meth:`connect`."""

    def __init__(
        self,
        exchange,
        info,
        *,
        address: str,
        sz_decimals: dict[str, int],
        slippage: float | None = None,
    ) -> None:
        self._exchange = exchange
        self._info = info
        self._address = address
        self._sz_decimals = sz_decimals
        self._slippage = config.ORDER_PRICE_BUFFER if slippage is None else slippage

    # ── construction ──────────────────────────────────────────────────────────

    @classmethod
    async def connect(
        cls,
        *,
        environment: str | None = None,
        address: str | None = None,
        private_key: str | None = None,
    ) -> "HyperliquidTradeClient":
        """Connect to Hyperliquid (testnet for forward_test, mainnet for production)."""
        environment = environment or config.ENVIRONMENT
        private_key = private_key or config.HYPERLIQUID_PRIVATE_KEY
        # Check the key before importing the SDK so a missing-key misconfig fails
        # fast (and is testable) without requiring hyperliquid-python-sdk installed.
        if not private_key:
            raise RuntimeError(
                "HYPERLIQUID_PRIVATE_KEY must be set to trade live on Hyperliquid."
            )

        import eth_account
        from hyperliquid.exchange import Exchange
        from hyperliquid.info import Info

        base_url = (
            config.HYPERLIQUID_MAINNET_API_URL
            if environment == "mainnet"
            else config.HYPERLIQUID_TESTNET_API_URL
        )

        wallet = eth_account.Account.from_key(private_key)
        # The funded account can differ from the signer when using an agent/API
        # wallet; fall back to the signer's own address.
        address = address or config.HYPERLIQUID_ACCOUNT_ADDRESS or wallet.address

        info = await asyncio.to_thread(Info, base_url, True)  # skip_ws=True
        exchange = await asyncio.to_thread(
            Exchange, wallet, base_url, None, address  # vault_address=None, account_address
        )

        # Map coin → size decimals once, so order sizes are rounded to the venue's
        # increment (HL rejects over-precise sizes).
        sz_decimals: dict[str, int] = {}
        try:
            meta = await asyncio.to_thread(info.meta)
            for asset in meta.get("universe", []):
                name = asset.get("name")
                if name is not None and asset.get("szDecimals") is not None:
                    sz_decimals[name] = int(asset["szDecimals"])
        except Exception as exc:  # non-fatal — fall back to per-order default rounding
            logger.warning("HL meta (szDecimals) fetch failed: %s", exc)

        logger.info("Hyperliquid trade client connected [%s] %s", environment, address)
        return cls(exchange, info, address=address, sz_decimals=sz_decimals)

    # ── orders ────────────────────────────────────────────────────────────────

    def _round_size(self, market: str, size: float) -> float:
        return round(float(size), self._sz_decimals.get(market, 4))

    @staticmethod
    def _parse_fill(result: dict, fallback_price: float) -> tuple[float, float] | None:
        """Pull (filled_size, avg_price) from an SDK order response, or None."""
        if not isinstance(result, dict) or result.get("status") != "ok":
            logger.warning("HL order not ok: %s", result)
            return None
        statuses = (
            result.get("response", {}).get("data", {}).get("statuses", [])
        )
        for st in statuses:
            if "error" in st:
                logger.warning("HL order error: %s", st["error"])
                return None
            if "filled" in st:
                f = st["filled"]
                return float(f.get("totalSz", 0) or 0), float(f.get("avgPx", 0) or 0)
        # No fill (e.g. IOC with no liquidity) → treat as a non-fill.
        return None

    async def place_market_order(
        self, *, market: str, side: str, size: float, reduce_only: bool = False
    ) -> OrderResult | None:
        """Place a market order (IOC, slippage-buffered). Returns None on any failure.

        ``reduce_only`` routes through ``market_close`` (closes in the position's
        opposite direction, handled by the SDK); opens go through ``market_open``.
        """
        try:
            sz = self._round_size(market, size)
            if sz <= 0:
                logger.warning("HL order size rounds to 0 for %s (%s) — skipping.", market, size)
                return None

            if reduce_only:
                result = await asyncio.to_thread(
                    self._exchange.market_close, market, sz, None, self._slippage
                )
            else:
                result = await asyncio.to_thread(
                    self._exchange.market_open,
                    market,
                    side == "BUY",
                    sz,
                    None,  # px=None → mid price
                    self._slippage,
                )

            parsed = self._parse_fill(result, fallback_price=0.0)
            if parsed is None:
                return None
            filled_sz, avg_px = parsed
            logger.info("HL order filled %s %s %s @ %.6f", side, filled_sz, market, avg_px)
            return OrderResult(
                market=market,
                side=side,
                size=filled_sz or sz,
                price=round(avg_px, 8),
                reduce_only=reduce_only,
            )
        except Exception as exc:  # never raise into the engine
            logger.warning("HL place_market_order failed for %s %s %s: %s", side, size, market, exc)
            return None

    async def cancel_all_orders(self) -> None:
        """Best-effort cancel of all resting orders (market IOC orders don't rest,
        so this is a safety net for any stray limit orders)."""
        try:
            orders = await asyncio.to_thread(self._info.open_orders, self._address)
        except Exception as exc:
            logger.warning("HL cancel_all_orders: could not list orders: %s", exc)
            return
        for o in orders or []:
            try:
                await asyncio.to_thread(self._exchange.cancel, o["coin"], int(o["oid"]))
            except Exception as exc:
                logger.warning("HL could not cancel order %s: %s", o.get("oid", "?"), exc)

    # ── queries ───────────────────────────────────────────────────────────────

    async def _user_state(self) -> dict:
        return await asyncio.to_thread(self._info.user_state, self._address)

    async def get_open_positions(self) -> dict[str, Position]:
        try:
            state = await self._user_state()
            out: dict[str, Position] = {}
            for ap in state.get("assetPositions", []):
                pos = ap.get("position", {})
                coin = pos.get("coin")
                szi = float(pos.get("szi", 0) or 0)
                if not coin or szi == 0:
                    continue
                out[coin] = Position(
                    market=coin,
                    side="LONG" if szi > 0 else "SHORT",
                    size=abs(szi),
                    entry_price=float(pos.get("entryPx", 0) or 0),
                )
            return out
        except Exception as exc:
            logger.warning("HL get_open_positions failed: %s", exc)
            return {}

    async def is_open_position(self, market: str) -> bool:
        return market in await self.get_open_positions()

    async def get_free_collateral(self) -> float:
        try:
            state = await self._user_state()
            return float(state.get("withdrawable", 0) or 0)
        except Exception as exc:
            logger.warning("HL get_free_collateral failed: %s", exc)
            return 0.0

    async def get_account_equity(self) -> float:
        try:
            state = await self._user_state()
            return float(state.get("marginSummary", {}).get("accountValue", 0) or 0)
        except Exception as exc:
            logger.warning("HL get_account_equity failed: %s", exc)
            return 0.0

    async def aclose(self) -> None:
        # The SDK uses a requests session per call; nothing to close.
        return None
