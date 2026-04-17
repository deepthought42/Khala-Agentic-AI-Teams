"""Portfolio state: capital, positions, mark-to-market equity, drawdown tracking.

Extracted from the equivalent inline state in
``TradeSimulationEngine._run_lookahead_safe``
(``backend/agents/investment_team/trade_simulator.py:466+``) so the new
streaming engine and the legacy engine remain byte-parity during PR 1's
parity-test window (legacy is removed in PR 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..strategy.contract import Fill, OrderSide


@dataclass
class Position:
    """An open position tracked by the engine."""

    symbol: str
    side: OrderSide
    qty: float
    entry_price: float  # post-slippage fill price
    entry_bid_price: float  # raw reference close / open before slippage
    entry_timestamp: str
    entry_order_id: str
    entry_client_order_id: str
    entry_order_type: str = "market"

    @property
    def position_value(self) -> float:
        return self.entry_price * self.qty


@dataclass
class Portfolio:
    """Tracks capital, open positions, cumulative P&L, and equity peak."""

    initial_capital: float
    capital: float = 0.0
    peak_equity: float = 0.0
    cumulative_pnl: float = 0.0
    positions: Dict[str, Position] = field(default_factory=dict)
    last_price: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.capital == 0.0:
            self.capital = self.initial_capital
        if self.peak_equity == 0.0:
            self.peak_equity = self.initial_capital

    # ------------------------------------------------------------------
    # Position lifecycle
    # ------------------------------------------------------------------

    def open(self, position: Position) -> None:
        if position.symbol in self.positions:
            raise ValueError(f"position already open for {position.symbol}")
        self.capital -= position.position_value
        self.positions[position.symbol] = position

    def close(self, symbol: str, exit_price: float) -> Optional[Position]:
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None
        # Cash returned uses the exit fill price × original qty. Realized P&L
        # is owned by the FillSimulator so it can apply slippage / fees; the
        # Portfolio just moves cash.
        self.capital += round(pos.qty * exit_price, 2)
        return pos

    def record_pnl(self, net_pnl: float) -> None:
        self.cumulative_pnl = round(self.cumulative_pnl + net_pnl, 2)

    # ------------------------------------------------------------------
    # Price / equity tracking
    # ------------------------------------------------------------------

    def update_last_price(self, symbol: str, price: float) -> None:
        self.last_price[symbol] = price

    def mark_to_market(self) -> float:
        """Return current equity (capital + M2M of all open positions)."""
        mtm = 0.0
        for sym, pos in self.positions.items():
            price_now = self.last_price.get(sym, pos.entry_price)
            if pos.side == OrderSide.LONG:
                mtm += pos.qty * price_now
            else:
                mtm += pos.qty * (2 * pos.entry_price - price_now)
        equity = self.capital + mtm
        if equity > self.peak_equity:
            self.peak_equity = equity
        return equity

    # ------------------------------------------------------------------
    # Snapshot for strategy context (parent → child stdin payload)
    # ------------------------------------------------------------------

    def position_snapshots(self) -> List[Dict[str, object]]:
        return [
            {
                "symbol": p.symbol,
                "side": p.side.value,
                "qty": p.qty,
                "entry_price": p.entry_price,
                "entry_timestamp": p.entry_timestamp,
            }
            for p in self.positions.values()
        ]

    # ------------------------------------------------------------------
    # Fill-style diagnostic builder — bridges Position → Fill protocol.
    # ------------------------------------------------------------------

    def make_entry_fill(self, pos: Position) -> Fill:
        return Fill(
            order_id=pos.entry_order_id,
            client_order_id=pos.entry_client_order_id,
            symbol=pos.symbol,
            side=pos.side,
            qty=pos.qty,
            price=pos.entry_price,
            timestamp=pos.entry_timestamp,
            reason="entry",
        )
