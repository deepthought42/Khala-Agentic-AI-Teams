"""Regression for zero-trade diagnostics enrichment in
``BacktestAnomalyDetector`` (issue #413, part of #404).

When the trading service supplies a ``BacktestExecutionDiagnostics`` envelope,
the zero-trade gate result must carry the deterministic category, the
executor's summary, the order counters, and (where present) the
rejection-reason histogram so the refinement agent can target the actual
failure mode. When diagnostics are missing, the existing generic message is
preserved for backwards compatibility.
"""

from __future__ import annotations

from investment_team.models import (
    BacktestExecutionDiagnostics,
    BacktestResult,
    TradeRecord,
)
from investment_team.strategy_lab.quality_gates.backtest_anomaly import (
    BacktestAnomalyDetector,
)

_GENERIC_ZERO_TRADE = "Backtest produced zero trades — strategy code never entered a position."


def _empty_metrics() -> BacktestResult:
    return BacktestResult(
        total_return_pct=0.0,
        annualized_return_pct=0.0,
        volatility_pct=0.0,
        sharpe_ratio=0.0,
        max_drawdown_pct=0.0,
        win_rate_pct=0.0,
        profit_factor=0.0,
    )


def _winning_metrics() -> BacktestResult:
    return BacktestResult(
        total_return_pct=20.0,
        annualized_return_pct=15.0,
        volatility_pct=8.0,
        sharpe_ratio=1.4,
        max_drawdown_pct=5.0,
        win_rate_pct=58.0,
        profit_factor=1.6,
    )


def _trades_minimum() -> list[TradeRecord]:
    """Six diversified, multi-day trades — enough to clear the < 5 floor,
    avg-hold-< 1d, and concentration / single-side gates so non-zero-trade
    tests don't false-positive on unrelated checks.
    """
    out: list[TradeRecord] = []
    cum = 0.0
    for i in range(6):
        net = 30.0 if i % 2 == 0 else -10.0
        cum += net
        out.append(
            TradeRecord(
                trade_num=i + 1,
                entry_date=f"2024-03-{i + 1:02d}",
                exit_date=f"2024-04-{i + 1:02d}",
                symbol="AAPL" if i % 2 == 0 else "MSFT",
                side="long" if i % 2 == 0 else "short",
                entry_price=100.0,
                exit_price=100.0 + net / 10.0,
                shares=10.0,
                position_value=1000.0,
                gross_pnl=net,
                net_pnl=net,
                return_pct=net / 1000.0 * 100,
                hold_days=20,
                outcome="win" if net > 0 else "loss",
                cumulative_pnl=cum,
            )
        )
    return out


def test_zero_trade_with_no_orders_emitted_category():
    diagnostics = BacktestExecutionDiagnostics(
        zero_trade_category="NO_ORDERS_EMITTED",
        summary="Strategy ran 250 bars but never emitted an order.",
        bars_processed=250,
    )
    detector = BacktestAnomalyDetector()
    results = detector.check(_empty_metrics(), [], diagnostics=diagnostics)
    assert len(results) == 1
    detail = results[0].details
    assert "Category: NO_ORDERS_EMITTED" in detail
    assert "Strategy ran 250 bars but never emitted an order." in detail
    assert "orders_emitted=0" in detail
    assert results[0].severity == "critical"
    assert results[0].passed is False


def test_zero_trade_with_orders_rejected_includes_reasons():
    diagnostics = BacktestExecutionDiagnostics(
        zero_trade_category="ORDERS_REJECTED",
        summary="All 12 emitted orders were rejected before fill.",
        bars_processed=300,
        orders_emitted=12,
        orders_rejected=12,
        orders_rejection_reasons={"risk_limit": 7, "insufficient_capital": 5},
    )
    detector = BacktestAnomalyDetector()
    results = detector.check(_empty_metrics(), [], diagnostics=diagnostics)
    detail = results[0].details
    assert "Category: ORDERS_REJECTED" in detail
    assert "orders_emitted=12" in detail
    assert "orders_rejected=12" in detail
    # Rejection reasons must be deterministic (sorted alphabetically by key).
    assert "rejection_reasons: insufficient_capital=5, risk_limit=7" in detail


def test_zero_trade_with_orders_unfilled_category():
    diagnostics = BacktestExecutionDiagnostics(
        zero_trade_category="ORDERS_UNFILLED",
        summary="Orders accepted but never crossed the fill price.",
        orders_emitted=4,
        orders_accepted=4,
        orders_unfilled=4,
    )
    detector = BacktestAnomalyDetector()
    results = detector.check(_empty_metrics(), [], diagnostics=diagnostics)
    detail = results[0].details
    assert "Category: ORDERS_UNFILLED" in detail
    assert "orders_unfilled=4" in detail


def test_zero_trade_with_entry_with_no_exit_category():
    diagnostics = BacktestExecutionDiagnostics(
        zero_trade_category="ENTRY_WITH_NO_EXIT",
        summary="One position opened but never closed before end of stream.",
        orders_emitted=1,
        orders_accepted=1,
        entries_filled=1,
        exits_emitted=0,
    )
    detector = BacktestAnomalyDetector()
    results = detector.check(_empty_metrics(), [], diagnostics=diagnostics)
    detail = results[0].details
    assert "Category: ENTRY_WITH_NO_EXIT" in detail
    assert "entries_filled=1" in detail
    assert "exits_emitted=0" in detail


def test_zero_trade_diagnostics_missing_falls_back_to_generic_message():
    """No diagnostics envelope → preserve the historical exact string verbatim,
    so the existing #404 sub-issue spec and any downstream consumers that
    grepped for it keep working.
    """
    detector = BacktestAnomalyDetector()
    results = detector.check(_empty_metrics(), [])
    assert len(results) == 1
    assert results[0].details == _GENERIC_ZERO_TRADE


def test_zero_trade_diagnostics_present_but_category_none_falls_back_to_generic():
    """Executor surfaced a diagnostics envelope but couldn't classify the
    failure (category=None) → fall back to the generic message rather than
    leaking partial counters that don't explain anything.
    """
    diagnostics = BacktestExecutionDiagnostics(
        zero_trade_category=None,
        summary="",
        bars_processed=10,
    )
    detector = BacktestAnomalyDetector()
    results = detector.check(_empty_metrics(), [], diagnostics=diagnostics)
    assert results[0].details == _GENERIC_ZERO_TRADE


def test_existing_callers_without_diagnostics_kwarg_still_work():
    """Callers that pre-date #413 must keep working: positional ``check``,
    ``mode=``, and ``dsr_aware=`` invocations all return the same generic
    zero-trade gate result without a TypeError.
    """
    detector = BacktestAnomalyDetector()

    bare = detector.check(_empty_metrics(), [])
    assert bare[0].details == _GENERIC_ZERO_TRADE

    with_dsr = detector.check(_empty_metrics(), [], dsr_aware=True)
    assert with_dsr[0].details == _GENERIC_ZERO_TRADE

    paper = detector.check(_empty_metrics(), [], mode="paper")
    assert paper[0].details == _GENERIC_ZERO_TRADE


def test_non_zero_trade_behaviour_unchanged_with_diagnostics_passed():
    """Diagnostics is consulted only inside the zero-trade branch — passing it
    on a successful, non-zero-trade backtest must not perturb the gate
    results.
    """
    diagnostics = BacktestExecutionDiagnostics(
        zero_trade_category="NO_ORDERS_EMITTED",
        summary="should be ignored when trades exist",
    )
    detector = BacktestAnomalyDetector()
    with_diag = detector.check(_winning_metrics(), _trades_minimum(), diagnostics=diagnostics)
    without_diag = detector.check(_winning_metrics(), _trades_minimum())
    assert [(r.gate_name, r.passed, r.severity, r.details) for r in with_diag] == [
        (r.gate_name, r.passed, r.severity, r.details) for r in without_diag
    ]
