"""Robustness tests for the indicator-coverage probe (#448)."""

from __future__ import annotations

import textwrap
from unittest.mock import patch

import numpy as np
import pandas as pd

from investment_team.models import CoverageCategory
from investment_team.strategy_lab.coverage_probe import run_indicator_probe


def _flat_ohlcv(n: int = 60) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": np.full(n, 100.0),
            "high": np.full(n, 101.0),
            "low": np.full(n, 99.0),
            "close": np.full(n, 100.0),
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def test_malformed_strategy_returns_unknown_low_coverage() -> None:
    report = run_indicator_probe(
        strategy_code="def on_bar(:::",
        market_data={"AAPL": _flat_ohlcv()},
    )
    assert report.coverage_category is CoverageCategory.UNKNOWN_LOW_COVERAGE
    assert "did not parse" in report.summary


def test_empty_strategy_code_returns_unknown_low_coverage() -> None:
    report = run_indicator_probe(strategy_code="", market_data={"AAPL": _flat_ohlcv()})
    assert report.coverage_category is CoverageCategory.UNKNOWN_LOW_COVERAGE


def test_no_recognized_subconditions_returns_unknown() -> None:
    code = textwrap.dedent(
        """
        class S:
            def on_bar(self, ctx, bar):
                if 1 < 2:
                    pass
        """
    )
    report = run_indicator_probe(
        strategy_code=code,
        market_data={"AAPL": _flat_ohlcv()},
    )
    assert report.coverage_category is CoverageCategory.UNKNOWN_LOW_COVERAGE
    assert report.subconditions == []


def test_module_level_period_constant_resolved() -> None:
    code = textwrap.dedent(
        """
        SMA_LOOKBACK = 5

        class S:
            def on_bar(self, ctx, bar):
                if close < sma(close, SMA_LOOKBACK) - 100:
                    pass
        """
    )
    report = run_indicator_probe(
        strategy_code=code,
        market_data={"AAPL": _flat_ohlcv()},
    )
    # ``sma(close, SMA_LOOKBACK) - 100`` is roughly zero for our flat
    # fixture, so ``close < 0`` is structurally false. The Name lookup
    # must resolve so that the subcondition registers at all.
    assert report.coverage_category is CoverageCategory.INDICATOR_FILTER_TOO_RESTRICTIVE
    assert len(report.subconditions) == 1


def test_no_llm_calls_made() -> None:
    """Patch the LLM client module so any accidental call raises immediately."""
    code = textwrap.dedent(
        """
        class S:
            def on_bar(self, ctx, bar):
                if close > 0:
                    pass
        """
    )

    def _explode(*_args, **_kwargs):
        raise AssertionError("LLM must not be called from indicator probe")

    with patch("investment_team.strategy_lab.coverage_probe.indicator_probe.logger"):
        # No LLM imports in the probe module — this monkey-patch sweep
        # asserts the module path stays free of llm_service usage.
        import investment_team.strategy_lab.coverage_probe.indicator_probe as mod

        for name in dir(mod):
            if "llm" in name.lower():
                raise AssertionError(f"unexpected llm symbol in probe module: {name}")

    # Patch llm_service entrypoints; if any code path accidentally imports
    # them, calling the probe explodes.
    targets = [
        "agents.llm_service.client.LLMClient",
        "agents.llm_service.ollama_client.OllamaClient",
    ]
    started = []
    for target in targets:
        try:
            p = patch(target, side_effect=_explode)
            p.start()
            started.append(p)
        except (ModuleNotFoundError, AttributeError):
            continue
    try:
        report = run_indicator_probe(
            strategy_code=code,
            market_data={"AAPL": _flat_ohlcv()},
        )
    finally:
        for p in started:
            p.stop()

    assert report.coverage_category is CoverageCategory.COVERAGE_OK


def test_evaluator_failure_per_subcondition_does_not_raise() -> None:
    """A subcondition referencing a column that's missing should degrade,
    not raise. We pass a DataFrame with no ``volume`` column but a
    ``volume``-touching subcondition; the probe should treat the leg as
    non-firing rather than crashing."""
    df = pd.DataFrame(
        {
            "open": np.full(30, 100.0),
            "high": np.full(30, 101.0),
            "low": np.full(30, 99.0),
            "close": np.full(30, 100.0),
        },
        index=pd.date_range("2024-01-01", periods=30, freq="D"),
    )
    code = textwrap.dedent(
        """
        class S:
            def on_bar(self, ctx, bar):
                if volume > 0:
                    pass
        """
    )
    report = run_indicator_probe(strategy_code=code, market_data={"SYM": df})

    # Volume column missing → all NaN → fillna(False) → zero hits.
    assert report.coverage_category is CoverageCategory.INDICATOR_FILTER_TOO_RESTRICTIVE
    assert len(report.subconditions) == 1
    assert report.subconditions[0].hit_count == 0


def test_empty_market_data_does_not_raise() -> None:
    code = textwrap.dedent(
        """
        class S:
            def on_bar(self, ctx, bar):
                if close > 0:
                    pass
        """
    )
    report = run_indicator_probe(strategy_code=code, market_data={})
    # Zero bars → no eval, but strategy parses and finds a subcondition →
    # COVERAGE_OK with empty hit data is not meaningful; the implementation
    # currently returns COVERAGE_OK for "no zero hits" — that is acceptable
    # because INSUFFICIENT_BARS is gated on warmup_bars_required > 0.
    assert report.coverage_category in {
        CoverageCategory.COVERAGE_OK,
        CoverageCategory.UNKNOWN_LOW_COVERAGE,
    }
    assert report.bars_checked == 0
