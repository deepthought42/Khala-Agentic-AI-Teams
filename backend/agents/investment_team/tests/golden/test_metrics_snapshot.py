"""Snapshot the current metric output for two reference strategies.

These values are pre-refactor baselines. Later phases (1: daily equity-curve
metrics, 2: look-ahead bias fix, 3-4: risk/cost, 5: engine split) are expected
to change these numbers; when they do, update the snapshot deliberately.
"""

from __future__ import annotations

import math

import pytest

from investment_team.trade_simulator import TradeSimulationEngine, compute_metrics

from .deterministic_strategies import mean_reversion, sma_crossover
from .synthetic_data import build_fixture_universe


def _run(strategy_factory):
    engine = TradeSimulationEngine(
        initial_capital=100_000.0,
        transaction_cost_bps=5.0,
        slippage_bps=2.0,
        pre_filter_pct=0.0,
        max_evaluations=100_000,
    )
    return engine.run(build_fixture_universe(), strategy_factory())


def _window(trades):
    starts = [t.entry_date for t in trades]
    ends = [t.exit_date for t in trades]
    return min(starts), max(ends)


def _assert_metric(actual, expected, label):
    # 2 d.p. is the simulator's rounding resolution for these fields
    assert actual == pytest.approx(expected, abs=0.02), (
        f"{label}: actual={actual} expected={expected}"
    )


def test_sma_crossover_trade_count():
    sim = _run(sma_crossover)
    assert len(sim.trades) == 52
    assert sim.forced_close_count == 3


def test_mean_reversion_trade_count():
    sim = _run(mean_reversion)
    assert len(sim.trades) == 68
    assert sim.forced_close_count == 2


def test_sma_crossover_metrics_snapshot():
    """Locks the *pre-refactor* metric output.

    The absurdly high Sharpe (392) and near-zero annualized vol are artifacts
    of the inter-trade-return estimator in ``compute_metrics``; Phase 1
    replaces this with a daily-equity-curve estimator and the snapshot will
    be updated in that PR.
    """
    sim = _run(sma_crossover)
    assert sim.trades
    start, end = _window(sim.trades)
    m = compute_metrics(sim.trades, 100_000.0, start, end)
    _assert_metric(m.total_return_pct, 7.50, "total_return_pct")
    _assert_metric(m.annualized_return_pct, 7.84, "annualized_return_pct")
    _assert_metric(m.win_rate_pct, 67.31, "win_rate_pct")
    _assert_metric(m.profit_factor, 4.15, "profit_factor")
    _assert_metric(m.max_drawdown_pct, 0.57, "max_drawdown_pct")
    assert math.isfinite(m.volatility_pct) and m.volatility_pct >= 0.0


def test_mean_reversion_metrics_snapshot():
    """Pre-refactor mean-reversion snapshot. Will change in Phase 1."""
    sim = _run(mean_reversion)
    start, end = _window(sim.trades)
    m = compute_metrics(sim.trades, 100_000.0, start, end)
    _assert_metric(m.total_return_pct, -8.40, "total_return_pct")
    _assert_metric(m.annualized_return_pct, -8.78, "annualized_return_pct")
    _assert_metric(m.win_rate_pct, 41.18, "win_rate_pct")
    _assert_metric(m.profit_factor, 0.23, "profit_factor")
    _assert_metric(m.max_drawdown_pct, 8.49, "max_drawdown_pct")


def test_mean_reversion_metrics_are_finite():
    sim = _run(mean_reversion)
    if not sim.trades:
        pytest.skip("no trades produced")
    start, end = _window(sim.trades)
    m = compute_metrics(sim.trades, 100_000.0, start, end)
    for field in (
        "total_return_pct",
        "annualized_return_pct",
        "volatility_pct",
        "sharpe_ratio",
        "max_drawdown_pct",
        "win_rate_pct",
        "profit_factor",
    ):
        val = getattr(m, field)
        assert math.isfinite(val), f"{field} is not finite: {val}"
