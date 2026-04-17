"""Pending-order book.

The ``OrderBook`` is the authoritative record of *accepted* strategy orders.
Strategy-emitted ``OrderRequest`` records come in through
:meth:`OrderBook.submit`, get gated by the existing
:class:`~investment_team.execution.risk_filter.RiskFilter`, receive an engine
``order_id``, and sit here until the :class:`FillSimulator` decides to fill
them (or they expire by TIF, or the strategy cancels them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..strategy.contract import OrderRequest, OrderSide, OrderType, TimeInForce


@dataclass
class PendingOrder:
    order_id: str
    request: OrderRequest
    submitted_at: str  # timestamp of the bar on which this was accepted
    submitted_equity: float  # for audit / risk-recheck if needed
    rejection_reason: Optional[str] = None  # set if the book rejects at submit-time


@dataclass
class OrderBook:
    _next_id: int = 0
    _pending: Dict[str, PendingOrder] = field(default_factory=dict)
    # Parallel index by symbol/side so fill_simulator doesn't have to scan.
    _by_symbol: Dict[str, List[str]] = field(default_factory=dict)

    # ------------------------------------------------------------------

    def submit(
        self,
        request: OrderRequest,
        *,
        submitted_at: str,
        submitted_equity: float,
    ) -> PendingOrder:
        self._next_id += 1
        order_id = f"o{self._next_id}"
        po = PendingOrder(
            order_id=order_id,
            request=request,
            submitted_at=submitted_at,
            submitted_equity=submitted_equity,
        )
        self._pending[order_id] = po
        self._by_symbol.setdefault(request.symbol, []).append(order_id)
        return po

    def cancel(self, order_id: str) -> bool:
        po = self._pending.pop(order_id, None)
        if po is None:
            return False
        ids = self._by_symbol.get(po.request.symbol)
        if ids and order_id in ids:
            ids.remove(order_id)
        return True

    def remove(self, order_id: str) -> Optional[PendingOrder]:
        po = self._pending.pop(order_id, None)
        if po is not None:
            ids = self._by_symbol.get(po.request.symbol)
            if ids and order_id in ids:
                ids.remove(order_id)
        return po

    def pending_for_symbol(self, symbol: str) -> List[PendingOrder]:
        return [self._pending[oid] for oid in self._by_symbol.get(symbol, [])]

    def all_pending(self) -> List[PendingOrder]:
        return list(self._pending.values())

    # ------------------------------------------------------------------
    # TIF expiry — callers pass the current bar timestamp; day orders
    # submitted on a strictly-earlier date are removed.
    # ------------------------------------------------------------------

    def expire_day_orders(self, current_date: str) -> List[PendingOrder]:
        expired: List[PendingOrder] = []
        for oid in list(self._pending.keys()):
            po = self._pending[oid]
            if po.request.tif != TimeInForce.DAY:
                continue
            # Compare date prefix only so intraday timestamps also work.
            if _date_only(po.submitted_at) < _date_only(current_date):
                expired.append(po)
                self.remove(oid)
        return expired


def _date_only(ts: str) -> str:
    return (ts or "")[:10]


# Convenience re-exports to make ``from .order_book import *`` unambiguous.
__all__ = [
    "OrderBook",
    "OrderSide",
    "OrderType",
    "PendingOrder",
    "TimeInForce",
]
