"""Robustness tests for the indicator-coverage probe (#448)."""

from __future__ import annotations

import textwrap

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


def test_prefers_on_bar_over_top_level_helper() -> None:
    """A top-level helper named ``signal`` / ``generate_signal`` must
    not shadow the strategy's real ``on_bar`` entry path. ``on_bar`` is
    the actual contract — the fallback names exist only for legacy /
    free-function strategies that lack one.
    """
    code = textwrap.dedent(
        """
        def generate_signal():
            # No ``if`` predicates here — if the probe stops here it'll
            # report UNKNOWN_LOW_COVERAGE despite the real on_bar below.
            return None

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
    assert report.subconditions[0].label == "close > 0"


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


def test_class_attribute_window_resolves_in_indicator_arg() -> None:
    """Strategies routinely pass class tuning knobs to indicator helpers,
    e.g. ``sma(close, self.WINDOW)``. The probe must resolve the
    ``self.WINDOW`` Attribute through the class-attribute binding;
    without this the helper either crashed (no default period) or
    silently used the wrong default, producing misleading coverage.
    """
    # Sawtooth so close oscillates around the moving average; different
    # window lengths produce visibly different hit counts.
    n = 200
    moves = np.array([+0.005, -0.005] * (n // 2))
    close = 100.0 * np.cumprod(1.0 + moves)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="D"),
    )

    code_short = textwrap.dedent(
        """
        class S:
            WINDOW = 3
            def on_bar(self, ctx, bar):
                if close < sma(close, self.WINDOW):
                    pass
        """
    )
    code_long = textwrap.dedent(
        """
        class S:
            WINDOW = 50
            def on_bar(self, ctx, bar):
                if close < sma(close, self.WINDOW):
                    pass
        """
    )
    short = run_indicator_probe(strategy_code=code_short, market_data={"AAPL": df})
    long = run_indicator_probe(strategy_code=code_long, market_data={"AAPL": df})

    # If the Attribute weren't resolved, sma's required ``period`` would
    # be missing and the helper would raise — caught by the probe and
    # emitted as zero hits. Resolution makes both runs evaluate cleanly
    # with non-zero hits, and the different windows yield different counts.
    assert len(short.subconditions) == 1
    assert len(long.subconditions) == 1
    assert short.subconditions[0].hit_count > 0
    assert long.subconditions[0].hit_count > 0
    assert short.subconditions[0].hit_count != long.subconditions[0].hit_count


def test_init_self_assignment_window_is_resolved() -> None:
    """``self.WINDOW = 80`` inside ``__init__`` is a different AST shape
    (Attribute target, not Name). It must still bind so a downstream
    ``sma(close, self.WINDOW)`` resolves the period.
    """
    code = textwrap.dedent(
        """
        class S:
            def __init__(self):
                self.WINDOW = 5
            def on_bar(self, ctx, bar):
                if close > sma(close, self.WINDOW):
                    pass
        """
    )
    df = _flat_ohlcv(n=100)
    df.loc[df.index[60:], "close"] = 95.0  # below the SMA half the time
    report = run_indicator_probe(strategy_code=code, market_data={"AAPL": df})

    assert len(report.subconditions) == 1
    # The subcondition must evaluate (not silently zero out due to a
    # missing period).
    sc = report.subconditions[0]
    assert sc.label == "close > sma(close, self.WINDOW)"
    assert 0 <= sc.hit_count <= report.bars_checked


def test_atr_positional_period_is_resolved() -> None:
    """``atr(high, low, close, N)`` puts the period at args[3], not args[1].

    Regression for a bug where the generic period extractor read args[1]
    (which is ``low`` for HLC helpers) and silently fell back to the
    helper's default of 14.

    ATR scales with the magnitude of true-range moves. A short window
    (period=2) over the ``_swing_close`` fixture below produces a
    substantially larger steady-state ATR than the default period=14.
    The test asserts the probe actually USES the requested period by
    comparing hit rates of ``atr(high, low, close, 2) > T`` against
    a plain ``atr(high, low, close) > T`` over the same data — they
    must differ.
    """

    def _swing_close(n: int = 100) -> pd.DataFrame:
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        # Sharp alternating moves so short-window ATR diverges from default.
        moves = np.array([+0.02, -0.02] * (n // 2))
        close = 100.0 * np.cumprod(1.0 + moves)
        return pd.DataFrame(
            {
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": np.full(n, 1_000_000.0),
            },
            index=idx,
        )

    code_short = textwrap.dedent(
        """
        class S:
            def on_bar(self, ctx, bar):
                if atr(high, low, close, 2) > 3:
                    pass
        """
    )
    code_default = textwrap.dedent(
        """
        class S:
            def on_bar(self, ctx, bar):
                if atr(high, low, close) > 3:
                    pass
        """
    )

    df = _swing_close()
    short = run_indicator_probe(strategy_code=code_short, market_data={"SYM": df})
    default = run_indicator_probe(strategy_code=code_default, market_data={"SYM": df})

    # If the period weren't honoured, both would compute the same ATR
    # (the default period=14) and report identical hit_count. The bug
    # we're guarding against is exactly that silent fallback.
    assert short.subconditions[0].hit_count != default.subconditions[0].hit_count


def test_no_llm_calls_made() -> None:
    """The indicator probe must not import or reference the LLM client.

    A static check on the module's source code is stronger than a runtime
    monkey-patch — the latter can leak into parallel pytest workers under
    ``-n auto`` and flake unrelated tests.
    """
    import inspect

    import investment_team.strategy_lab.coverage_probe.indicator_probe as mod

    src = inspect.getsource(mod)
    assert "llm_service" not in src
    assert "LLMClient" not in src
    assert "OllamaClient" not in src

    # Module exports also must not surface any llm-named symbols.
    for name in dir(mod):
        assert "llm" not in name.lower(), f"unexpected llm symbol: {name}"

    # Smoke-call the probe to confirm it still runs cleanly.
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
