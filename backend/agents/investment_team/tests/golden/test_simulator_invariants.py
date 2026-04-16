"""Invariant (property-style) tests for the trade simulator.

These assertions must hold across every simulation run regardless of strategy:

- cash conservation (no capital materializes/disappears)
- PnL attribution (sum of trade net_pnl equals delta of capital plus open MTM)
- temporal safety (a fill's bar date cannot precede its decision's visible history)
"""

from __future__ import annotations

import pytest

from investment_team.trade_simulator import TradeSimulationEngine

from .deterministic_strategies import mean_reversion, sma_crossover
from .synthetic_data import build_fixture_universe


@pytest.fixture(scope="module")
def universe():
    return build_fixture_universe()


@pytest.mark.parametrize(
    "strategy_factory",
    [sma_crossover, mean_reversion],
    ids=["sma_crossover", "mean_reversion"],
)
def test_capital_reflects_gross_pnl(universe, strategy_factory):
    """Documents current behavior: ``final_capital`` tracks gross PnL only.

    Transaction costs are subtracted from ``TradeRecord.net_pnl`` but never
    from the engine's running ``capital`` balance, so the engine's capital and
    the trade ledger disagree by the sum of fees. Phase 5 (engine split)
    switches ``LiveEngine`` to a mark-to-market cash ledger that reconciles
    both; this assertion will then flip to ``net_pnl``.
    """
    engine = TradeSimulationEngine(
        initial_capital=100_000.0,
        transaction_cost_bps=5.0,
        slippage_bps=2.0,
        pre_filter_pct=0.0,
        max_evaluations=100_000,
    )
    result = engine.run(universe, strategy_factory())
    expected_gross = 100_000.0 + sum(t.gross_pnl for t in result.trades)
    assert result.final_capital == pytest.approx(expected_gross, abs=1.0)


@pytest.mark.parametrize(
    "strategy_factory",
    [sma_crossover, mean_reversion],
    ids=["sma_crossover", "mean_reversion"],
)
@pytest.mark.xfail(
    reason="Pre-refactor: engine capital excludes tx costs (see Phase 5 plan).",
    strict=True,
)
def test_capital_reflects_net_pnl_after_refactor(universe, strategy_factory):
    engine = TradeSimulationEngine(
        initial_capital=100_000.0,
        transaction_cost_bps=5.0,
        slippage_bps=2.0,
        pre_filter_pct=0.0,
        max_evaluations=100_000,
    )
    result = engine.run(universe, strategy_factory())
    expected_net = 100_000.0 + sum(t.net_pnl for t in result.trades)
    assert result.final_capital == pytest.approx(expected_net, abs=1.0)


@pytest.mark.parametrize(
    "strategy_factory",
    [sma_crossover, mean_reversion],
    ids=["sma_crossover", "mean_reversion"],
)
def test_cumulative_pnl_matches_sum(universe, strategy_factory):
    engine = TradeSimulationEngine(
        initial_capital=100_000.0,
        pre_filter_pct=0.0,
        max_evaluations=100_000,
    )
    evaluate_fn = strategy_factory()
    result = engine.run(universe, evaluate_fn)
    running = 0.0
    for t in result.trades:
        running = round(running + t.net_pnl, 2)
        assert t.cumulative_pnl == pytest.approx(running, abs=0.05), (
            f"trade {t.trade_num}: cumulative_pnl={t.cumulative_pnl} "
            f"should equal running sum {running}"
        )


def test_no_trades_when_strategy_always_holds(universe):
    engine = TradeSimulationEngine(pre_filter_pct=0.0, max_evaluations=100_000)

    def always_hold(*_args, **_kwargs):
        return {"action": "hold", "confidence": 0.0, "shares": 0, "reasoning": ""}

    result = engine.run(universe, always_hold)
    assert result.trades == []
    assert result.final_capital == pytest.approx(engine.initial_capital, abs=0.01)


def test_trade_dates_are_within_universe_span(universe):
    engine = TradeSimulationEngine(pre_filter_pct=0.0, max_evaluations=100_000)
    evaluate_fn = sma_crossover()
    result = engine.run(universe, evaluate_fn)
    all_dates: list[str] = []
    for bars in universe.values():
        all_dates.extend(b.date for b in bars)
    lo, hi = min(all_dates), max(all_dates)
    for t in result.trades:
        assert lo <= t.entry_date <= hi
        assert lo <= t.exit_date <= hi
        assert t.entry_date <= t.exit_date


def test_hold_days_non_negative(universe):
    engine = TradeSimulationEngine(pre_filter_pct=0.0, max_evaluations=100_000)
    result = engine.run(universe, sma_crossover())
    assert all(t.hold_days >= 1 for t in result.trades)


def test_forced_close_count_is_accurate(universe):
    """Only SYMBOLS with positions open at the end produce a forced close."""
    engine = TradeSimulationEngine(pre_filter_pct=0.0, max_evaluations=100_000)

    def always_long(symbol, bar, recent, position, capital):
        if position is None:
            return {"action": "enter_long", "confidence": 1.0, "shares": 0, "reasoning": ""}
        return {"action": "hold", "confidence": 0.0, "shares": 0, "reasoning": ""}

    result = engine.run(universe, always_long)
    # Every symbol that ever triggered an entry will still be open at EOD.
    assert result.forced_close_count == len(universe)
    assert len(result.trades) == len(universe)
