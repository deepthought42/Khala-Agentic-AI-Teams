"""Cost-stress replay helper (Phase 4).

Overfitting strategies often look viable at "retail" friction — a few bps on
entry and exit — but collapse when transaction costs and slippage are pushed
higher.  ``run_cost_stress`` replays a run function at a configurable set of
multipliers and returns a compact summary that the orchestrator can use to
fail strategies whose Sharpe degrades too quickly.

The helper is deliberately tiny: callers provide a ``run_fn(multiplier)``
closure that knows how to run the strategy with an inflated cost config, and
the helper applies it in order and collects the resulting metrics.  The
heavy lifting (cloning ``BacktestConfig`` with new fee values, threading
market data, etc.) lives in the caller so the helper stays free of model
dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence


@dataclass
class CostStressRow:
    """One multiplier's run summary."""

    multiplier: float
    sharpe_ratio: float
    annualized_return_pct: float
    max_drawdown_pct: float
    trade_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "multiplier": self.multiplier,
            "sharpe_ratio": self.sharpe_ratio,
            "annualized_return_pct": self.annualized_return_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "trade_count": self.trade_count,
        }


@dataclass
class CostStressReport:
    rows: List[CostStressRow] = field(default_factory=list)

    def at(self, multiplier: float, *, tol: float = 1e-6) -> Optional[CostStressRow]:
        """Return the row for the given multiplier, or ``None`` if absent."""
        for row in self.rows:
            if abs(row.multiplier - multiplier) < tol:
                return row
        return None

    def to_payload(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self.rows]


def run_cost_stress(
    *,
    run_fn: Callable[[float], Any],
    multipliers: Sequence[float],
    extract_metrics: Callable[[Any], CostStressRow],
) -> CostStressReport:
    """Invoke ``run_fn`` once per multiplier and collect the reports.

    ``extract_metrics`` translates the ``run_fn`` return into a
    ``CostStressRow`` — decoupled from ``BacktestResult`` so tests can use
    simple dataclasses.
    """
    report = CostStressReport()
    for m in multipliers:
        result = run_fn(m)
        report.rows.append(extract_metrics(result))
    return report


__all__ = ["CostStressReport", "CostStressRow", "run_cost_stress"]
