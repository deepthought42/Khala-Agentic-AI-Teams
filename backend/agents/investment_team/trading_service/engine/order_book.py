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
    # TIF expiry — remove DAY orders whose submitted_at date is strictly
    # earlier than ``cutoff_date``.
    #
    # An order submitted after bar B(d1) gets its first fill attempt on
    # its symbol's next bar. In multi-symbol timelines that next bar may
    # still share the same date (e.g. AAA(d1) → BBB(d1) → AAA(d2)): if
    # we expire on the first d2 event using d2 as the cutoff, AAA's order
    # is killed before AAA(d2) ever sees it. Callers therefore pass the
    # *previous* bar's timestamp so orders born on date d1 remain alive
    # for the entirety of the first date that is strictly after d1.
    # ------------------------------------------------------------------

    def expire_day_orders(self, cutoff_date: str) -> List[PendingOrder]:
        expired: List[PendingOrder] = []
        for oid in list(self._pending.keys()):
            po = self._pending[oid]
            if po.request.tif != TimeInForce.DAY:
                continue
            # Compare date prefix only so intraday timestamps also work.
            if _date_only(po.submitted_at) < _date_only(cutoff_date):
                expired.append(po)
                self.remove(oid)
        return expired

    def cancel_by_client_order_id(self, client_order_id: str) -> bool:
        """Cancel the (at most one) pending order carrying this client ID.

        Strategy code only knows the client-side IDs it generated via
        ``ctx.submit_order`` (``c1``, ``c2``, …); the engine's internal
        ``order_id`` never crosses the subprocess boundary before fill.
        This lookup translates without requiring a round-trip ack.
        """
        for oid, po in self._pending.items():
            if po.request.client_order_id == client_order_id:
                return self.cancel(oid)
        return False


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
