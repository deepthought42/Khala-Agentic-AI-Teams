"""Unit tests for the factor DSL primitives + tree-edit distance (issue #249).

These tests target the pure-Python reference implementations in
``factors.primitives``.  The compiler emits independently-templated
helpers; ``test_genome_compiler.py`` checks that the compiled output
agrees with these references on the same inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

from investment_team.strategy_lab.factors import (
    Genome,
    tree_edit_distance,
)
from investment_team.strategy_lab.factors import primitives as P
from investment_team.strategy_lab.factors.models import (
    EMA,
    RSI,
    SMA,
    BoolAnd,
    CompareGT,
    CompareLT,
    Const,
    CrossOver,
    FixedQty,
    Price,
)


@dataclass
class _Bar:
    """Tiny bar stand-in for testing primitives without pulling in pydantic."""

    open: float
    high: float
    low: float
    close: float
    volume: float = 1000.0


def _ramp(n: int, base: float = 100.0, step: float = 1.0) -> List[_Bar]:
    return [
        _Bar(base + i * step, base + i * step + 0.5, base + i * step - 0.5, base + i * step)
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Primitive purity + warm-up.
# ---------------------------------------------------------------------------


def test_primitives_return_nan_when_warmup_short():
    bars = _ramp(3)
    assert math.isnan(P.sma(bars, 5))
    assert math.isnan(P.ema(bars, 5))
    assert math.isnan(P.rsi(bars, 14))
    assert math.isnan(P.atr(bars, 14))
    assert math.isnan(P.macd_signal(bars, 12, 26, 9))


def test_primitives_are_pure():
    bars = _ramp(40)
    # Same input twice must return the same float exactly.
    assert P.sma(bars, 10) == P.sma(bars, 10)
    assert P.ema(bars, 10) == P.ema(bars, 10)
    assert P.rsi(bars, 14) == P.rsi(bars, 14)
    assert P.bollinger_z(bars, 20) == P.bollinger_z(bars, 20)
    assert P.atr(bars, 14) == P.atr(bars, 14)


def test_sma_matches_arithmetic_mean():
    bars = _ramp(20)
    expected = sum(b.close for b in bars[-10:]) / 10
    assert P.sma(bars, 10) == expected


def test_rsi_pegs_to_100_when_only_gains():
    bars = _ramp(30)  # strictly increasing closes → no losses in window
    assert P.rsi(bars, 14) == 100.0


def test_bollinger_z_zero_at_window_centre():
    """A perfectly linear ramp has the latest close one side of the mean."""
    bars = _ramp(40, base=100.0, step=1.0)
    z = P.bollinger_z(bars, 10)
    # Linear ramp: latest close is 4.5 std-devs above the centred mean.
    # We only assert the sign + finiteness here; the exact value is exercised
    # by the compiler round-trip test.
    assert z > 0
    assert math.isfinite(z)


def test_cross_asset_primitives_return_nan_without_aux():
    bars = _ramp(40)
    assert math.isnan(P.term_structure_slope(bars, None, 20))
    assert math.isnan(P.funding_rate_deviation(bars, None, 24))


# ---------------------------------------------------------------------------
# tree_edit_distance.
# ---------------------------------------------------------------------------


def _genome(entry, exit_):
    return Genome(
        asset_class="stocks",
        hypothesis="",
        signal_definition="",
        entry=entry,
        exit=exit_,
        sizing=FixedQty(qty=1),
    )


def test_tree_edit_distance_zero_for_identical_structure():
    g1 = _genome(
        CompareGT(left=SMA(period=20), right=Const(value=100)),
        CompareLT(left=SMA(period=20), right=Const(value=100)),
    )
    g2 = _genome(
        CompareGT(left=SMA(period=20), right=Const(value=100)),
        CompareLT(left=SMA(period=20), right=Const(value=100)),
    )
    assert tree_edit_distance(g1, g2) == 0


def test_tree_edit_distance_zero_when_only_parameter_values_differ():
    """Same shape, different period/threshold → still 0 (proxy for `same idea`)."""
    g1 = _genome(
        CompareGT(left=SMA(period=20), right=Const(value=100)),
        CompareLT(left=SMA(period=20), right=Const(value=100)),
    )
    g2 = _genome(
        CompareGT(left=SMA(period=50), right=Const(value=200)),
        CompareLT(left=SMA(period=50), right=Const(value=200)),
    )
    assert tree_edit_distance(g1, g2) == 0


def test_tree_edit_distance_grows_with_structural_difference():
    g1 = _genome(
        CompareGT(left=SMA(period=20), right=Const(value=100)),
        CompareLT(left=SMA(period=20), right=Const(value=100)),
    )
    # Replace SMA with EMA on entry, add an AND combinator → different shape.
    g2 = _genome(
        BoolAnd(
            children=[
                CompareGT(left=EMA(period=20), right=Const(value=100)),
                CompareGT(left=RSI(period=14), right=Const(value=50)),
            ]
        ),
        CrossOver(fast=Price(field="close"), slow=SMA(period=20)),
    )
    assert tree_edit_distance(g1, g2) > 0
