"""
dYdX v4 trade-execution client (Phase 5a) — order placement, position/account
queries, cancel, implementing the :class:`~trading.broker.TradeClient` protocol.

This is the side-effecting counterpart to the read-only ``DydxDataClient``. It
wraps ``dydx-v4-client`` (node + indexer + wallet) and ports the reference bot's
``func_private.py`` / ``func_connections.py`` logic: a 5%-buffered market order
against the oracle price, short-term FOK, fill-confirmed by polling positions.

``dydx-v4-client`` is imported lazily inside :meth:`connect` so the rest of the
backend (and the whole test suite, which injects a fake) imports this module
without the SDK installed. The Phase-5a automated gate uses a ``FakeTradeClient``;
this real client is exercised against live testnet manually (it needs a funded
subaccount + network — see PROGRESS.md).
"""

from __future__ import annotations

import asyncio
import logging
import random

import config
from trading.broker import OrderResult, Position

logger = logging.getLogger(__name__)


class DydxTradeClient:
    """Live dYdX v4 account/order client. Build via :meth:`connect`."""

    def __init__(self, node, indexer, wallet, *, address: str, subaccount: int) -> None:
        self._node = node
        self._indexer = indexer
        self._wallet = wallet
        self._address = address
        self._subaccount = subaccount

    # ── construction ──────────────────────────────────────────────────────────

    @classmethod
    async def connect(
        cls,
        *,
        environment: str | None = None,
        address: str | None = None,
        private_key: str | None = None,
        subaccount: int | None = None,
    ) -> "DydxTradeClient":
        """Connect to dYdX v4 (testnet for forward_test, mainnet for production)."""
        from dydx_v4_client.indexer.rest.indexer_client import IndexerClient
        from dydx_v4_client.key_pair import KeyPair
        from dydx_v4_client.network import TESTNET, make_mainnet
        from dydx_v4_client.node.client import NodeClient
        from dydx_v4_client.wallet import Wallet

        environment = environment or config.ENVIRONMENT
        address = address or config.DYDX_WALLET_ADDRESS
        private_key = private_key or config.DYDX_PRIVATE_KEY
        subaccount = subaccount if subaccount is not None else config.DYDX_SUBACCOUNT_INDEX

        if not address or not private_key:
            raise RuntimeError(
                "DYDX_WALLET_API_KEY and DYDX_PRIVATE_KEY must be set to trade live."
            )

        if environment == "mainnet":
            network = make_mainnet(
                node_url=config.DYDX_MAINNET_NODE_URL,
                rest_indexer=config.DYDX_MAINNET_INDEXER,
                websocket_indexer="",
            )
            node = await NodeClient.connect(network.node)
            indexer = IndexerClient(network.rest_indexer)
        else:
            node = await NodeClient.connect(TESTNET.node)
            indexer = IndexerClient(TESTNET.rest_indexer)

        key_pair = KeyPair.from_hex(private_key.removeprefix("0x").removeprefix("0X"))
        account = await node.get_account(address)
        wallet = Wallet(key_pair, account.account_number, account.sequence)
        logger.info("dYdX trade client connected [%s] %s", environment, address)
        return cls(node, indexer, wallet, address=address, subaccount=subaccount)

    # ── orders ──────────────────────────────────────────────────────────────────

    async def place_market_order(
        self, *, market: str, side: str, size: float, reduce_only: bool = False
    ) -> OrderResult | None:
        """Place a 5%-buffered short-term market order. Returns None on any failure."""
        try:
            from dydx_v4_client import MAX_CLIENT_ID, OrderFlags
            from dydx_v4_client.indexer.rest.constants import OrderType
            from dydx_v4_client.node.market import Market
            from v4_proto.dydxprotocol.clob.order_pb2 import Order

            mkt_resp = await self._indexer.markets.get_perpetual_markets(market)
            mkt_data = mkt_resp["markets"][market]
            mkt_builder = Market(mkt_data)

            oracle_price = float(mkt_data.get("oraclePrice", 0) or 0)
            if oracle_price <= 0:
                ob = await self._indexer.markets.get_perpetual_market_orderbook(market)
                asks, bids = ob.get("asks", []), ob.get("bids", [])
                if asks and bids:
                    oracle_price = (float(asks[0]["price"]) + float(bids[0]["price"])) / 2
            if oracle_price <= 0:
                logger.warning("Cannot resolve price for %s — skipping order.", market)
                return None

            if side == "BUY":
                accept_price = oracle_price * (1 + config.ORDER_PRICE_BUFFER)
                order_side = Order.Side.SIDE_BUY
            else:
                accept_price = oracle_price * (1 - config.ORDER_PRICE_BUFFER)
                order_side = Order.Side.SIDE_SELL

            client_id = random.randint(0, MAX_CLIENT_ID)
            current_block = await self._node.latest_block_height()
            order_id = mkt_builder.order_id(
                self._address, self._subaccount, client_id, OrderFlags.SHORT_TERM
            )
            new_order = mkt_builder.order(
                order_id=order_id,
                order_type=OrderType.MARKET,
                side=order_side,
                size=float(size),
                price=accept_price,
                time_in_force=Order.TimeInForce.TIME_IN_FORCE_UNSPECIFIED,
                reduce_only=reduce_only,
                good_til_block=current_block + config.ORDER_EXPIRY_BLOCKS,
            )
            await self._node.place_order(self._wallet, new_order)
            self._wallet.sequence += 1
            logger.info("Order placed %s %s %s @ ~%.4f", side, size, market, oracle_price)
            return OrderResult(
                market=market,
                side=side,
                size=float(size),
                price=round(accept_price, 8),
                client_id=client_id,
                reduce_only=reduce_only,
            )
        except Exception as exc:  # never raise into the engine
            logger.warning("place_market_order failed for %s %s %s: %s", side, size, market, exc)
            return None

    async def cancel_all_orders(self) -> None:
        """Best-effort cancel of all OPEN orders for the subaccount."""
        from v4_proto.dydxprotocol.clob.order_pb2 import OrderId
        from v4_proto.dydxprotocol.subaccounts.subaccount_pb2 import SubaccountId

        try:
            orders = await self._indexer.account.get_subaccount_orders(
                self._address, self._subaccount, status="OPEN"
            )
        except Exception as exc:
            logger.warning("cancel_all_orders: could not list orders: %s", exc)
            return
        if not orders:
            return
        current_block = await self._node.latest_block_height()
        for order in orders:
            try:
                raw_flags = order.get("orderFlags", "0")
                order_id = OrderId(
                    subaccount_id=SubaccountId(owner=self._address, number=self._subaccount),
                    client_id=int(order.get("clientId", 0)),
                    order_flags=int(raw_flags) if str(raw_flags).isdigit() else 0,
                    clob_pair_id=int(order.get("clobPairId", 0)),
                )
                await self._node.cancel_order(
                    self._wallet, order_id, good_til_block=current_block + config.ORDER_EXPIRY_BLOCKS
                )
                self._wallet.sequence += 1
                await asyncio.sleep(0.3)
            except Exception as exc:
                logger.warning("could not cancel order %s: %s", order.get("id", "?"), exc)

    # ── queries ──────────────────────────────────────────────────────────────────

    async def get_open_positions(self) -> dict[str, Position]:
        try:
            resp = await self._indexer.account.get_subaccount_perpetual_positions(
                self._address, self._subaccount, status="OPEN"
            )
            out: dict[str, Position] = {}
            for p in resp.get("positions", []):
                out[p["market"]] = Position(
                    market=p["market"],
                    side=p.get("side", ""),
                    size=abs(float(p.get("size", 0) or 0)),
                    entry_price=float(p.get("entryPrice", 0) or 0),
                )
            return out
        except Exception as exc:
            logger.warning("get_open_positions failed: %s", exc)
            return {}

    async def is_open_position(self, market: str) -> bool:
        return market in await self.get_open_positions()

    async def _subaccount_field(self, field: str) -> float:
        try:
            resp = await self._indexer.account.get_subaccount(self._address, self._subaccount)
            return float(resp.get("subaccount", {}).get(field, 0) or 0)
        except Exception as exc:
            logger.warning("subaccount %s fetch failed: %s", field, exc)
            return 0.0

    async def get_free_collateral(self) -> float:
        return await self._subaccount_field("freeCollateral")

    async def get_account_equity(self) -> float:
        return await self._subaccount_field("equity")

    async def aclose(self) -> None:
        # NodeClient/IndexerClient manage their own transports; nothing to close.
        return None
