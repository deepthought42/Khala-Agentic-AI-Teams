"""Basic per-subcondition tests for the indicator-coverage probe (#448)."""

from __future__ import annotations

import textwrap

import numpy as np
import pandas as pd

from investment_team.models import CoverageCategory
from investment_team.strategy_lab.coverage_probe import run_indicator_probe


def _flat_ohlcv(n: int = 60, base: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": np.full(n, base),
            "high": np.full(n, base + 1.0),
            "low": np.full(n, base - 1.0),
            "close": np.full(n, base),
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def _swing_ohlcv(n: int = 200, leg: int = 50, step: float = 0.005) -> pd.DataFrame:
    """Sawtooth price series that drives RSI to its extremes.

    50 bars at -0.5%/bar take RSI well below 30; 50 bars at +0.5%/bar
    take it above 70. Two full cycles in 200 bars give every RSI
    threshold in (0..100) at least one strict crossing per cycle.
    """
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    moves: list[float] = []
    while len(moves) < n:
        moves.extend([-step] * leg)
        moves.extend([+step] * leg)
    moves = moves[:n]
    close = 100.0 * np.cumprod(1.0 + np.array(moves))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def test_always_true_subcondition_returns_coverage_ok() -> None:
    code = textwrap.dedent(
        """
        class S:
            def on_bar(self, ctx, bar):
                if close > 0:
                    pass
        """
    )
    report = run_indicator_probe(
        strategy_code=code,
        market_data={"AAPL": _flat_ohlcv()},
    )

    assert report.coverage_category is CoverageCategory.COVERAGE_OK
    assert len(report.subconditions) == 1
    sc = report.subconditions[0]
    assert sc.hit_rate == 1.0
    assert sc.hit_count == 60
    assert sc.last_true_bar is not None
    assert report.bars_checked == 60


def test_never_true_subcondition_returns_too_restrictive() -> None:
    code = textwrap.dedent(
        """
        class S:
            def on_bar(self, ctx, bar):
                if close < -50:
                    pass
        """
    )
    report = run_indicator_probe(
        strategy_code=code,
        market_data={"AAPL": _swing_ohlcv()},
    )

    assert report.coverage_category is CoverageCategory.INDICATOR_FILTER_TOO_RESTRICTIVE
    assert len(report.subconditions) == 1
    assert report.subconditions[0].hit_count == 0
    assert report.subconditions[0].hit_rate == 0.0
    assert len(report.likely_blockers) == 1
    blocker = report.likely_blockers[0]
    assert blocker.reason == "indicator_filter_zero_hits"
    assert blocker.hit_rate == 0.0


def test_partial_fire_subcondition_populates_last_true_bar() -> None:
    code = textwrap.dedent(
        """
        class S:
            def on_bar(self, ctx, bar):
                if close < sma(close, 5):
                    pass
        """
    )
    report = run_indicator_probe(
        strategy_code=code,
        market_data={"AAPL": _swing_ohlcv()},
    )

    assert report.coverage_category is CoverageCategory.COVERAGE_OK
    assert len(report.subconditions) == 1
    sc = report.subconditions[0]
    assert 0.0 < sc.hit_rate < 1.0
    assert sc.hit_count > 0
    assert sc.last_true_bar is not None


def test_insufficient_bars_short_circuits() -> None:
    code = textwrap.dedent(
        """
        class S:
            def on_bar(self, ctx, bar):
                if close > 0:
                    pass
        """
    )
    report = run_indicator_probe(
        strategy_code=code,
        market_data={"AAPL": _flat_ohlcv(n=5)},
        warmup_bars_required=200,
    )

    assert report.coverage_category is CoverageCategory.INSUFFICIENT_BARS
    assert report.subconditions == []
    assert report.bars_checked == 5
    assert report.warmup_bars_required == 200
    assert len(report.likely_blockers) == 1
    assert report.likely_blockers[0].reason == "insufficient_bars"


def test_volume_scaled_subcondition_recognized() -> None:
    df = _flat_ohlcv()
    df.loc[df.index[40:], "volume"] = 2_000_000.0  # half the bars at 2x baseline
    code = textwrap.dedent(
        """
        class S:
            def on_bar(self, ctx, bar):
                if volume > volume * 1.5:
                    pass
        """
    )
    report = run_indicator_probe(
        strategy_code=code,
        market_data={"SYM": df},
    )

    # ``volume > volume * 1.5`` is structurally a never-true subcondition;
    # the probe should classify it as too-restrictive.
    assert report.coverage_category is CoverageCategory.INDICATOR_FILTER_TOO_RESTRICTIVE
    assert len(report.subconditions) == 1
    assert report.subconditions[0].hit_rate == 0.0
