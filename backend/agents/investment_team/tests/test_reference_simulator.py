"""Unit tests for ``executor.reference_simulator`` — the combined multi-kind
driver that joins entry and exit replay into complete ``ReferenceTrade``
records over a full backtest window.

``test_reference_entries.py``/``test_reference_exits.py`` already cover each
rule kind's own fill mechanics exhaustively at the per-resolver level; the
tests here instead exercise what only the JOINED driver can produce: a
complete entry-plus-exit record, cross-kind competition on one bar, ladder
blending across a foreign closing rule, re-entry, end-of-series handling, and
cross-symbol emission order.
"""

from __future__ import annotations

import copy
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from investment_team.models import StrategySpec
from investment_team.strategy_lab.executor.reference_simulator import ReferenceTrade, simulate
from investment_team.strategy_lab.spec_dsl import (
    BracketStopLeg,
    BracketTakeProfitLeg,
    EntryRule,
    ExitRule,
    OcoBracketRule,
    Predicate,
    ScaledTakeProfitRule,
    SignalExitRule,
    StopLossRule,
    TakeProfitLevel,
    TakeProfitRule,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _Bar:
    """Minimal ``Bar``-shaped stand-in — the module only reads these attrs.

    Same shape the sibling ``test_reference_entries``/``test_reference_exits``
    suites use, so a bar fixture is portable between all three.
    """

    open: float
    high: float
    low: float
    close: float
    volume: float = 1000.0
    timestamp: str = "2024-01-01T00:00:00"
    symbol: str = "AAA"


def _bar(
    open_: float,
    high: float,
    low: float,
    close: float,
    ts: str,
    symbol: str = "AAA",
) -> _Bar:
    """Positional OHLC factory, in OHLC order, with an explicit timestamp.

    Every test in this file spells out its own timestamps (unlike the sibling
    suites' single-bar fixtures) because cross-symbol/`trade_num` ordering
    tests need genuinely distinct, comparable ISO timestamps across bars.
    """
    return _Bar(open=open_, high=high, low=low, close=close, timestamp=ts, symbol=symbol)


def _spec(
    exit_rules: "list[ExitRule] | None" = None,
    entry_side: str = "long",
    target_symbols: "list[str] | None" = None,
    requires_custom_code: bool = False,
    entry_rules: "list[EntryRule] | None" = None,
) -> StrategySpec:
    """Standard test spec: enters when ``bar.close > 100`` (unless overridden)."""
    return StrategySpec(
        strategy_id="strat-ref-sim-test",
        authored_by="test",
        asset_class="stocks",
        hypothesis="hyp",
        signal_definition="sig",
        timeframe="1d",
        entry_rules=(
            entry_rules
            if entry_rules is not None
            else [EntryRule(side=entry_side, when=Predicate(lhs="bar.close", op=">", rhs=100.0))]
        ),
        exit_rules=exit_rules or [],
        target_symbols=target_symbols or [],
        requires_custom_code=requires_custom_code,
    )


def _dates(n: int, start_day: int = 1) -> "list[str]":
    """``n`` distinct, strictly increasing ISO timestamps starting at day ``start_day``.

    Real date arithmetic, not string formatting into a fixed month: a fixed
    ``"2024-01-{day:02d}"`` template would silently emit an invalid date like
    ``"2024-01-32"`` once ``start_day + n`` exceeds January's own length.
    """
    start = date(2024, 1, 1) + timedelta(days=start_day - 1)
    return [(start + timedelta(days=i)).isoformat() + "T00:00:00" for i in range(n)]


# ---------------------------------------------------------------------------
# Per-kind, joined-record tests
# ---------------------------------------------------------------------------


def test_stop_loss_through_bar_produces_a_complete_trade():
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),  # trigger
        _bar(101, 101, 101, 101, d[2]),  # entry fill @101
        _bar(101, 101, 94, 95, d[3]),  # through-bar stop (5% below 101 = 95.95)
    ]
    spec = _spec([StopLossRule(pct=0.05, basis="entry_price")])
    [trade] = simulate(spec, {"AAA": bars})
    assert trade.trade_num == 1
    assert trade.symbol == "AAA"
    assert trade.side == "long"
    assert (trade.entry_bar, trade.exit_bar) == (2, 3)
    assert (trade.entry_date, trade.exit_date) == ("2024-01-03", "2024-01-04")
    assert (trade.entry_price, trade.exit_price) == (101.0, 95.95)
    assert trade.qty == 1.0
    assert (trade.exit_rule_kind, trade.exit_rule_index, trade.level_index) == (
        "stop_loss",
        0,
        None,
    )


def test_stop_loss_gap_fills_at_the_worse_open():
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 101, d[2]),  # entry fill @101
        _bar(90, 91, 88, 89, d[3]),  # gap below the 95.95 level
    ]
    spec = _spec([StopLossRule(pct=0.05, basis="entry_price")])
    [trade] = simulate(spec, {"AAA": bars})
    assert trade.exit_price == 90.0  # worse-of-open-and-level on a gap


def test_stop_loss_short_side_through_bar():
    d = _dates(4)
    bars = [
        _bar(101, 101, 101, 101, d[0]),
        _bar(
            99, 100, 98, 99, d[1]
        ),  # trigger (close<=100 not > -- use dedicated short predicate below)
        _bar(100, 100, 100, 100, d[2]),  # entry fill @100
        _bar(100, 106, 99, 101, d[3]),  # through-bar: high touches 105.00...(=100*1.05)
    ]
    spec = _spec(
        [StopLossRule(pct=0.05, basis="entry_price")],
        entry_rules=[EntryRule(side="short", when=Predicate(lhs="bar.close", op="<", rhs=100.0))],
    )
    [trade] = simulate(spec, {"AAA": bars})
    assert trade.side == "short"
    assert trade.exit_price == round(100 * 1.05, 2)


def test_take_profit_gap_through_still_fills_at_the_exact_target():
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 101, d[2]),  # entry fill @101
        _bar(115, 120, 114, 118, d[3]),  # gaps past the 10% target (111.1) -- still fills AT target
    ]
    spec = _spec([TakeProfitRule(pct=0.10)])
    [trade] = simulate(spec, {"AAA": bars})
    assert trade.exit_rule_kind == "take_profit"
    assert trade.exit_price == round(101 * 1.10, 2)
    assert trade.level_index is None


def test_scaled_take_profit_single_rung_closes_and_records_its_level():
    d = _dates(4)
    target = 101 * 1.05
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 101, d[2]),  # entry fill @101
        _bar(
            101, target + 1.0, 101, 105, d[3]
        ),  # rung fires, closes the whole ladder (qty_fraction=1.0)
    ]
    ladder = ScaledTakeProfitRule(levels=[TakeProfitLevel(pct=0.05, qty_fraction=1.0)])
    spec = _spec([ladder])
    [trade] = simulate(spec, {"AAA": bars})
    assert trade.exit_rule_kind == "scaled_take_profit"
    assert trade.level_index == 0
    assert trade.exit_price == round(target, 2)


def test_signal_exit_fills_at_next_bar_open():
    d = _dates(5)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 101, d[2]),  # entry fill @101
        _bar(101, 101, 101, 90, d[3]),  # trigger: close < 95
        _bar(80, 80, 80, 80, d[4]),  # fill bar: signal closes at THIS bar's open
    ]
    spec = _spec([SignalExitRule(when=Predicate(lhs="bar.close", op="<", rhs=95.0))])
    [trade] = simulate(spec, {"AAA": bars})
    assert trade.exit_rule_kind == "signal_exit"
    assert (trade.exit_bar, trade.exit_price) == (4, 80.0)


def test_signal_exit_is_eligible_on_the_entry_bar_itself():
    """Unlike a resting order, a signal's trigger check is eligible starting on
    ``entry_bar`` itself -- only its FILL is deferred to the next bar."""
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 90, d[2]),  # entry fill @101 AND close<95 fires the signal same bar
        _bar(80, 80, 80, 80, d[3]),  # fill bar
    ]
    spec = _spec([SignalExitRule(when=Predicate(lhs="bar.close", op="<", rhs=95.0))])
    [trade] = simulate(spec, {"AAA": bars})
    assert (trade.entry_bar, trade.exit_bar) == (2, 3)
    assert trade.exit_price == 80.0


def test_signal_exit_with_a_nonpositive_fill_bar_open_does_not_fire():
    """The design doc's uniform "Nonpositive exit references" rule: a fill
    price that is not finite and positive suppresses the candidate rather
    than firing or crashing -- here the position simply stays open (no
    trade), since this is the spec's only exit rule and the series ends
    right after."""
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 90, d[2]),  # entry fill @101; close<95 fires the signal
        _bar(0.0, 0.0, 0.0, 0.0, d[3]),  # fill bar's open is nonpositive
    ]
    spec = _spec([SignalExitRule(when=Predicate(lhs="bar.close", op="<", rhs=95.0))])
    assert simulate(spec, {"AAA": bars}) == []


def test_short_take_profit_with_a_nonpositive_target_does_not_crash_simulate():
    """The same "Nonpositive exit references" rule applies to the take-profit
    family: TakeProfitRule.pct has no upper bound, so a short's target
    (``anchor * (1 - pct)``) can land at or below zero for ``pct >= 1``. A
    degenerate bar whose low is nonpositive can then "reach" that target --
    the guard must suppress just this candidate (position stays open, no
    trade), not let a nonpositive price reach ReferenceTrade construction and
    abort the whole run."""
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),  # trigger bar: close > 100
        _bar(100, 100, 100, 100, d[2]),  # entry fill @100 (short anchor=100)
        _bar(100, 100, -60, 100, d[3]),  # target=100*(1-1.5)=-50; low=-60 "reaches" it
    ]
    spec = _spec([TakeProfitRule(pct=1.5)], entry_side="short")
    assert simulate(spec, {"AAA": bars}) == []


def test_signal_only_spec_does_not_crash_on_an_entry_price_that_would_zero_the_anchor():
    """A signal-only spec (no stop/take-profit rules) never needs the
    post-slippage anchor -- signal exits use the raw entry price and the next
    bar's open, never entry_price_basis. Computing that anchor unconditionally
    would abort the whole run whenever the entry fill is small enough that the
    anchor rounds to zero, even though neither book that would consume it is
    ever built for this spec."""
    d = _dates(3)
    bars = [
        _bar(0.00001, 0.00001, 0.00001, 0.00001, d[0]),
        _bar(0.00001, 0.00001, 0.00001, 101, d[1]),  # trigger: close > 100
        _bar(0.00001, 0.00001, 0.00001, 0.00001, d[2]),  # entry fill @0.00001 -- rounds to 0
    ]
    spec = _spec([SignalExitRule(when=Predicate(lhs="bar.close", op="<", rhs=0.0))])
    assert simulate(spec, {"AAA": bars}) == []


def test_entry_price_is_rounded_to_its_own_production_bucket():
    """Design doc §3: ``ReferenceTrade.entry_price``/``exit_price`` must be
    rounded the same way production rounds ``entry_bid_price``/
    ``exit_bid_price``, or a raw fill price with more decimal places than
    either bucket allows shows as a spurious mismatch against production's
    own rounded field for every single trade."""
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),  # trigger: close > 100
        _bar(100.12345, 100.12345, 100.12345, 100.12345, d[2]),  # entry fill @100.12345
        _bar(100, 100, 90, 91, d[3]),  # through-bar stop
    ]
    spec = _spec([StopLossRule(pct=0.05, basis="entry_price")])
    [trade] = simulate(spec, {"AAA": bars})
    assert trade.entry_price == 100.12  # rounded to the 2dp bucket (>= 10), not 100.12345


def test_an_entry_price_that_would_round_to_zero_opens_no_position():
    """Fresh evidence after the entry-price-rounding fix above: a fill-bar
    open can be raw-positive-finite (passing ``fill_entry_at``'s own guard)
    yet still round away to zero at its own bucket -- e.g.
    ``round(0.00004, 4) == 0.0`` -- which would otherwise only surface at
    ``ReferenceTrade`` construction and abort the whole run. A signal exit
    that would otherwise close the position normally proves the entry itself
    never opens, not merely that the eventual trade is suppressed."""
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),  # trigger: close > 100
        _bar(0.00004, 0.00004, 0.00004, 50, d[2]),  # entry fill @0.00004 (rounds to 0);
        # also a signal trigger (close < 100), eligible on entry_bar itself
        _bar(90, 90, 90, 90, d[3]),  # would-be signal-exit fill, if a position had opened
    ]
    spec = _spec([SignalExitRule(when=Predicate(lhs="bar.close", op="<", rhs=100.0))])
    assert simulate(spec, {"AAA": bars}) == []


def test_a_degenerate_trigger_close_does_not_open_a_position_even_though_the_predicate_fires():
    """Design doc §5 "Entries": a trigger bar whose close is <= 0 or
    non-finite must not open a position, mirroring production's
    ``_compute_qty`` sizing a degenerate trigger to zero -- even though a
    predicate like ``close < 1`` still numerically fires true against a close
    of exactly 0. A ``StopLossRule`` that would certainly close a WRONGLY
    opened position by bar 2 makes this discriminating: with no gate, a
    position opens at bar 1 and a stop_loss trade is emitted by bar 2; with
    the gate, no position ever opens and nothing is emitted at all."""
    d = _dates(4)
    bars = [
        _bar(50, 50, 0.0, 0.0, d[0]),  # trigger: close < 1 fires, but close == 0 is degenerate
        _bar(100, 100, 100, 100, d[1]),  # would-be fill bar -- must NOT become an entry
        _bar(100, 100, 40, 100, d[2]),  # would trip a 50% stop if a position had wrongly opened
        _bar(100, 100, 100, 100, d[3]),
    ]
    spec = _spec(
        [StopLossRule(pct=0.5, basis="entry_price")],
        entry_rules=[EntryRule(side="long", when=Predicate(lhs="bar.close", op="<", rhs=1.0))],
    )
    assert simulate(spec, {"AAA": bars}) == []


# ---------------------------------------------------------------------------
# Multi-rule-kind competition
# ---------------------------------------------------------------------------


def test_stop_beats_take_profit_when_stop_has_the_lower_index():
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 101, d[2]),  # entry fill @101
        _bar(101, 120, 80, 100, d[3]),  # wide bar: touches both stop(95.95) and target(111.1)
    ]
    spec = _spec([StopLossRule(pct=0.05, basis="entry_price"), TakeProfitRule(pct=0.10)])
    [trade] = simulate(spec, {"AAA": bars})
    assert (trade.exit_rule_kind, trade.exit_rule_index) == ("stop_loss", 0)


def test_take_profit_beats_stop_when_take_profit_has_the_lower_index():
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 101, d[2]),  # entry fill @101
        _bar(101, 120, 80, 100, d[3]),  # same wide bar, rules reordered
    ]
    spec = _spec([TakeProfitRule(pct=0.10), StopLossRule(pct=0.05, basis="entry_price")])
    [trade] = simulate(spec, {"AAA": bars})
    assert (trade.exit_rule_kind, trade.exit_rule_index) == ("take_profit", 0)


def test_an_invalid_lower_index_take_profit_candidate_does_not_mask_a_valid_stop():
    """A degenerate take-profit candidate (nonpositive target, pct >= 1 on the
    short side) must not win the cross-book priority comparison by rule index
    alone. Filtering it only at commit time -- after stop_wins was already
    decided by comparing raw indices -- let it silently suppress a
    legitimately reachable, higher-index stop on the very same bar, leaving
    the position open with no trade emitted at all."""
    d = _dates(4)
    bars = [
        _bar(101, 101, 101, 101, d[0]),
        _bar(99, 100, 98, 99, d[1]),  # trigger: close < 100
        _bar(100, 100, 100, 100, d[2]),  # entry fill @100 (short anchor=100)
        _bar(100, 110, -60, 100, d[3]),  # stop(105) reached AND tp target(-50) "reached"
    ]
    spec = _spec(
        [TakeProfitRule(pct=1.5), StopLossRule(pct=0.05, basis="entry_price")],
        entry_rules=[EntryRule(side="short", when=Predicate(lhs="bar.close", op="<", rhs=100.0))],
    )
    [trade] = simulate(spec, {"AAA": bars})
    assert (trade.exit_rule_kind, trade.exit_rule_index) == ("stop_loss", 1)


def test_an_invalid_lower_index_stop_candidate_does_not_mask_a_valid_take_profit():
    """The mirror case: a stop candidate's RAW price can pass
    RestingStopLoss.peek's own guard (positive, finite) yet still round away
    to zero once _finalize_exit_price applies production's rounding bucket --
    e.g. an entry price small enough that a deep (pct close to 1) stop's level
    survives the raw check but rounds to zero. That must not let an unusable,
    lower-index stop win the cross-book priority comparison and block a
    legitimate, higher-index take-profit reachable on the very same bar."""
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),  # trigger: close > 100
        _bar(0.0001, 0.0001, 0.0001, 0.0001, d[2]),  # entry fill @0.0001 (anchor=0.0001)
        _bar(0.0001, 0.001, 0.0, 0.0001, d[3]),  # stop(0.00001) AND target(0.00011) both reached
    ]
    spec = _spec([StopLossRule(pct=0.90, basis="entry_price"), TakeProfitRule(pct=0.10)])
    [trade] = simulate(spec, {"AAA": bars})
    assert (trade.exit_rule_kind, trade.exit_rule_index) == ("take_profit", 1)


def test_a_lower_index_stop_that_rounds_to_zero_rescans_to_a_valid_higher_index_stop():
    """The same rescan the take-profit family already gets, but for the stop
    book: a stop whose RAW price passes ``peek``'s own guard can still round
    to <= 0 once ``_finalize_exit_price`` applies production's bucket -- and
    unlike the cross-book masking above, there is no OTHER rule kind here at
    all to fall back on, so the fix must let the stop book itself offer a
    DIFFERENT, valid stop at a higher index."""
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),  # trigger: close > 100
        _bar(0.0001, 0.0001, 0.0001, 0.0001, d[2]),  # entry fill @0.0001 (anchor=0.0001)
        _bar(0.0001, 0.0001, 0.000005, 0.0001, d[3]),  # low reaches both stop levels
    ]
    spec = _spec(
        [
            StopLossRule(pct=0.90, basis="entry_price"),
            StopLossRule(pct=0.10, basis="entry_price"),
        ]
    )
    [trade] = simulate(spec, {"AAA": bars})
    assert (trade.exit_rule_kind, trade.exit_rule_index) == ("stop_loss", 1)
    assert trade.exit_price == 0.0001  # 0.00009 rounded to the 4dp bucket


def test_a_same_family_invalid_take_profit_does_not_mask_a_valid_one_at_a_higher_index():
    """A degenerate take-profit candidate must not stop
    ``RestingTakeProfitFamily`` from finding a DIFFERENT, valid candidate in
    the SAME family at a higher ``exit_rule_index`` -- distinct from the
    cross-book masking above, since there is no ``stop_loss`` rule here at
    all; ``peek()`` itself must rescan its own intents rather than committing
    to the first-by-index one regardless of usability."""
    d = _dates(4)
    bars = [
        _bar(101, 101, 101, 101, d[0]),
        _bar(99, 100, 98, 99, d[1]),  # trigger: close < 100
        _bar(100, 100, 100, 100, d[2]),  # entry fill @100 (short anchor=100)
        _bar(100, 100, -60, 100, d[3]),  # low reaches both: -50 (invalid) and 50 (valid)
    ]
    spec = _spec(
        [TakeProfitRule(pct=1.5), TakeProfitRule(pct=0.5)],
        entry_rules=[EntryRule(side="short", when=Predicate(lhs="bar.close", op="<", rhs=100.0))],
    )
    [trade] = simulate(spec, {"AAA": bars})
    assert (trade.exit_rule_kind, trade.exit_rule_index) == ("take_profit", 1)


def test_a_take_profit_target_that_rounds_to_zero_does_not_crash_simulate():
    """Further evidence beyond the nonpositive-target fix above: a positive
    raw target can still become unusable only after rounding -- e.g. a short
    anchored at 0.0001 with ``pct=0.6`` produces a reachable target of
    0.00004, which rounds to 0.0 at the 4dp bucket. The candidate must be
    treated as not having fired at all, not reach ``ReferenceTrade``
    construction and abort the whole run."""
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),  # trigger: close > 100
        _bar(0.0001, 0.0001, 0.0001, 0.0001, d[2]),  # entry fill @0.0001 (short anchor=0.0001)
        _bar(0.0001, 0.0001, 0.00001, 0.0001, d[3]),  # low reaches the 0.00004 target
    ]
    spec = _spec([TakeProfitRule(pct=0.6)], entry_side="short")
    assert simulate(spec, {"AAA": bars}) == []


def test_a_terminal_take_profit_that_rounds_to_zero_does_not_mask_a_valid_higher_index_one():
    """Further evidence beyond the round-to-zero guard above: that guard
    correctly refuses to commit the doomed candidate, but by itself leaves
    the resting phase with nothing -- the SAME masking risk as an invalid
    RAW candidate, one stage further down the pipeline. ``peek`` must rescan
    to the valid, higher-index candidate rather than leaving the bar's
    resting phase empty-handed."""
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),  # trigger: close > 100
        _bar(0.0001, 0.0001, 0.0001, 0.0001, d[2]),  # entry fill @0.0001 (short anchor=0.0001)
        _bar(0.0001, 0.0001, 0.00001, 0.0001, d[3]),  # low reaches both 0.00004 and 0.00009
    ]
    spec = _spec([TakeProfitRule(pct=0.6), TakeProfitRule(pct=0.1)], entry_side="short")
    [trade] = simulate(spec, {"AAA": bars})
    assert (trade.exit_rule_kind, trade.exit_rule_index) == ("take_profit", 1)
    assert trade.exit_price == 0.0001  # 0.00009 rounded to the 4dp bucket


def test_resting_order_beats_a_queued_signal_exit_on_the_same_fill_bar():
    """FIFO by materialization time: the stop was resting since entry, strictly
    earlier than a signal triggered afterward, so it wins the shared fill bar."""
    d = _dates(5)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 101, d[2]),  # entry fill @101
        _bar(101, 101, 99, 99, d[3]),  # signal trigger (close<100), queued for next bar;
        # low(99) stays above the 95.95 stop
        _bar(101, 101, 94, 95, d[4]),  # fill bar: ALSO reaches the 95.95 stop -> stop wins
    ]
    spec = _spec(
        [
            StopLossRule(pct=0.05, basis="entry_price"),
            SignalExitRule(when=Predicate(lhs="bar.close", op="<", rhs=100.0)),
        ]
    )
    [trade] = simulate(spec, {"AAA": bars})
    assert trade.exit_rule_kind == "stop_loss"
    assert trade.exit_bar == 4


def test_limit_style_stop_is_retired_the_moment_a_signal_exit_is_queued():
    """Production excludes a resting limit-style stop from further evaluation
    the instant a competing whole-position close is CHOSEN -- so once a signal
    is queued, the limit stop must not win the fill bar via FIFO even though
    its own level is technically reachable there."""
    d = _dates(5)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(100, 100, 100, 100, d[2]),  # entry fill @100 (stop=95, limit=93.1)
        _bar(
            93, 93, 90, 91, d[3]
        ),  # arms the stop (low<=95) but gaps past the limit (high<93.1); signal fires (close<95)
        _bar(
            90, 95, 89, 94, d[4]
        ),  # limit WOULD be reachable (high>=93.1) if not retired; signal fills @ open
    ]
    spec = _spec(
        [
            StopLossRule(pct=0.05, style="limit", limit_offset_pct=0.02),
            SignalExitRule(when=Predicate(lhs="bar.close", op="<", rhs=95.0)),
        ]
    )
    [trade] = simulate(spec, {"AAA": bars})
    assert trade.exit_rule_kind == "signal_exit"
    assert trade.exit_price == 90.0


def test_a_failed_signal_fill_restores_a_retired_limit_stop():
    """When the queued signal's fill bar has a nonpositive open, the fill
    never happens -- the design doc's uniform rule treats that firing as if
    it had never been met at all. The limit-style stop retired the moment the
    signal was queued must come back for a later bar, not stay permanently
    excluded for a close that turned out to have never happened."""
    d = _dates(6)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(100, 100, 100, 100, d[2]),  # entry fill @100 (stop=95, limit=93.1)
        _bar(93, 93, 90, 91, d[3]),  # arms the stop, gaps past limit; signal fires (close<95)
        _bar(
            0.0, 100.0, 0.0, 100.0, d[4]
        ),  # fill bar's open is nonpositive -- fill fails; close=100
        # does not re-trigger the signal on this same bar
        _bar(90, 95, 89, 94, d[5]),  # limit (93.1) reachable again -- must fire now restored
    ]
    spec = _spec(
        [
            StopLossRule(pct=0.05, style="limit", limit_offset_pct=0.02),
            SignalExitRule(when=Predicate(lhs="bar.close", op="<", rhs=95.0)),
        ]
    )
    [trade] = simulate(spec, {"AAA": bars})
    assert trade.exit_rule_kind == "stop_loss"
    assert trade.exit_bar == 5


def test_a_partial_rung_does_not_retire_a_resting_limit_stop():
    """Contrast with the retirement test above: a scaled rung that only
    PARTIALLY closes the position does not count as a chosen whole-position
    close, so a resting limit-style stop must keep protecting the runner."""
    d = _dates(5)
    target = 100 * 1.05
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(100, 100, 100, 100, d[2]),  # entry fill @100 (stop=95, limit=93.1)
        _bar(
            100, target + 1.0, 100, 104, d[3]
        ),  # partial rung fires (qty_fraction=0.5) -- position stays open
        _bar(93, 96, 90, 91, d[4]),  # limit stop arms AND is reachable this same bar -> fills
    ]
    ladder = ScaledTakeProfitRule(levels=[TakeProfitLevel(pct=0.05, qty_fraction=0.5)])
    spec = _spec([StopLossRule(pct=0.05, style="limit", limit_offset_pct=0.02), ladder])
    [trade] = simulate(spec, {"AAA": bars})
    assert trade.exit_rule_kind == "stop_loss"
    assert trade.exit_bar == 4


def test_ladder_rungs_then_stop_loss_closes_the_remainder_with_a_blended_price():
    """A ladder's earlier rungs contribute to exit_price (qty-weighted) even
    when a stop_loss performs the final close; level_index stays None since
    the final closing event was the stop, not a rung."""
    d = _dates(5)
    rung_target = 101 * 1.05
    stop_level = 101 * 0.95
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 101, d[2]),  # entry fill @101
        _bar(101, rung_target + 0.05, 101, 105, d[3]),  # rung fires (qty 0.5)
        _bar(105, 105, 95, 96, d[4]),  # stop closes the remaining 0.5
    ]
    ladder = ScaledTakeProfitRule(levels=[TakeProfitLevel(pct=0.05, qty_fraction=0.5)])
    spec = _spec([StopLossRule(pct=0.05, basis="entry_price"), ladder])
    [trade] = simulate(spec, {"AAA": bars})
    assert trade.exit_rule_kind == "stop_loss"
    assert trade.level_index is None
    expected = 0.5 * rung_target + 0.5 * stop_level
    assert trade.exit_price == round(expected, 2)


def test_ladder_rungs_then_signal_exit_closes_the_remainder_with_a_blended_price():
    """Same rule as the stop_loss variant above, with a signal_exit performing
    the final close instead: the blend and the None level_index hold either
    way, since aggregation depends only on which rung fired, not which kind
    closed the remainder."""
    d = _dates(6)
    rung_target = 100 * 1.05
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(100, 100, 100, 100, d[2]),  # entry fill @100
        _bar(
            100, rung_target + 1.0, 100, 104, d[3]
        ),  # rung fires (qty 0.5); close=104, not < 100 -> no signal yet
        _bar(104, 104, 98, 99, d[4]),  # signal trigger (close<100), queued for next bar
        _bar(90, 90, 90, 90, d[5]),  # signal fills @ open=90
    ]
    ladder = ScaledTakeProfitRule(levels=[TakeProfitLevel(pct=0.05, qty_fraction=0.5)])
    spec = _spec([ladder, SignalExitRule(when=Predicate(lhs="bar.close", op="<", rhs=100.0))])
    [trade] = simulate(spec, {"AAA": bars})
    assert trade.exit_rule_kind == "signal_exit"
    assert trade.level_index is None
    expected = 0.5 * rung_target + 0.5 * 90.0
    assert trade.exit_price == round(expected, 2)


# ---------------------------------------------------------------------------
# Boundary and structure
# ---------------------------------------------------------------------------


def test_position_open_at_the_end_of_series_emits_no_trade():
    """A position still open when its bars run out produces no ReferenceTrade
    at all -- mirroring production's open-position reporting rather than a
    synthetic force-close."""
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 101, d[2]),  # entry fill @101, never touches the stop
        _bar(101, 101, 101, 101, d[3]),
    ]
    spec = _spec([StopLossRule(pct=0.50, basis="entry_price")])
    assert simulate(spec, {"AAA": bars}) == []


def test_a_partially_reduced_ladder_still_open_at_end_of_series_emits_no_trade():
    """Same end-of-series rule, for the harder case: a position holding only
    a partially-reduced ladder remainder still produces no ReferenceTrade --
    a fired rung does not count as a close."""
    d = _dates(4)
    target = 101 * 1.05
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 101, d[2]),  # entry fill @101
        _bar(101, target + 1.0, 101, 105, d[3]),  # rung fires (qty 0.5), remainder never closes
    ]
    ladder = ScaledTakeProfitRule(levels=[TakeProfitLevel(pct=0.05, qty_fraction=0.5)])
    spec = _spec([ladder])
    assert simulate(spec, {"AAA": bars}) == []


def test_reentry_after_a_close_produces_multiple_trades():
    d = _dates(8)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),  # trigger 1
        _bar(101, 101, 101, 101, d[2]),  # entry fill 1 @101
        _bar(101, 101, 94, 95, d[3]),  # stop 1 fires; close=95, not >100, no new trigger this bar
        _bar(50, 50, 50, 50, d[4]),
        _bar(101, 102, 100, 101, d[5]),  # trigger 2
        _bar(102, 102, 102, 102, d[6]),  # entry fill 2 @102
        _bar(102, 102, 96, 97, d[7]),  # stop 2 fires (5% below 102 = 96.9)
    ]
    spec = _spec([StopLossRule(pct=0.05, basis="entry_price")])
    trades = simulate(spec, {"AAA": bars})
    assert len(trades) == 2
    assert (trades[0].entry_bar, trades[0].exit_bar) == (2, 3)
    assert (trades[1].entry_bar, trades[1].exit_bar) == (6, 7)
    assert [t.trade_num for t in trades] == [1, 2]


def test_a_close_does_not_suppress_a_fresh_entry_trigger_on_the_same_bar():
    """Exits resolve before entries on the same bar, and entry suppression
    reads the POST-exit state: a position closing on bar i must not block a
    matching entry predicate on that SAME bar i."""
    d = _dates(6)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),  # trigger 1
        _bar(101, 101, 101, 101, d[2]),  # entry fill 1 @101
        _bar(101, 101, 94, 101, d[3]),  # stop 1 fires AND close=101>100 re-triggers entry, same bar
        _bar(102, 102, 102, 102, d[4]),  # entry fill 2 @102
        _bar(102, 102, 90, 91, d[5]),  # stop 2 fires
    ]
    spec = _spec([StopLossRule(pct=0.05, basis="entry_price")])
    trades = simulate(spec, {"AAA": bars})
    assert len(trades) == 2
    assert trades[0].exit_bar == 3
    assert trades[1].entry_bar == 4  # the very next bar after the same-bar close+reopen


def test_trade_num_ordering_follows_exit_timestamp_across_symbols():
    """A symbol processed LATER in the ``bars`` mapping can still close
    EARLIER in calendar time and must get the lower ``trade_num``."""
    dA = _dates(6)
    barsA = [
        _bar(99, 99, 99, 99, dA[0], symbol="AAA"),
        _bar(101, 102, 100, 101, dA[1], symbol="AAA"),
        _bar(101, 101, 101, 101, dA[2], symbol="AAA"),  # entry fill
        _bar(101, 101, 101, 101, dA[3], symbol="AAA"),
        _bar(101, 101, 101, 101, dA[4], symbol="AAA"),
        _bar(101, 101, 94, 95, dA[5], symbol="AAA"),  # closes on day 6
    ]
    dB = _dates(4)
    barsB = [
        _bar(99, 99, 99, 99, dB[0], symbol="BBB"),
        _bar(101, 102, 100, 101, dB[1], symbol="BBB"),
        _bar(101, 101, 101, 101, dB[2], symbol="BBB"),  # entry fill
        _bar(101, 101, 94, 95, dB[3], symbol="BBB"),  # closes on day 4 -- earlier than AAA's
    ]
    spec = _spec([StopLossRule(pct=0.05, basis="entry_price")], target_symbols=["AAA", "BBB"])
    trades = simulate(spec, {"AAA": barsA, "BBB": barsB})
    assert len(trades) == 2
    assert [t.symbol for t in trades] == ["BBB", "AAA"]
    assert [t.trade_num for t in trades] == [1, 2]


def test_target_symbols_gating_skips_an_auxiliary_symbol_entirely():
    d = _dates(4)
    triggering_bars = [
        _bar(99, 99, 99, 99, d[0], symbol="ZZZ"),
        _bar(101, 102, 100, 101, d[1], symbol="ZZZ"),
        _bar(101, 101, 101, 101, d[2], symbol="ZZZ"),
        _bar(101, 101, 94, 95, d[3], symbol="ZZZ"),
    ]
    spec = _spec([StopLossRule(pct=0.05, basis="entry_price")], target_symbols=["AAA"])
    trades = simulate(
        spec, {"AAA": [_bar(99, 99, 99, 99, ts, symbol="AAA") for ts in d], "ZZZ": triggering_bars}
    )
    assert trades == []


# ---------------------------------------------------------------------------
# simulate() preconditions
# ---------------------------------------------------------------------------


def test_simulate_rejects_a_custom_code_spec():
    spec = _spec(requires_custom_code=True, entry_rules=[])
    with pytest.raises(ValueError, match="custom_code"):
        simulate(spec, {"AAA": [_bar(99, 99, 99, 99, "2024-01-01T00:00:00")]})


def test_simulate_rejects_a_spec_with_an_oco_bracket_rule():
    spec = _spec(
        [
            OcoBracketRule(
                stop_loss=BracketStopLeg(pct=0.05), take_profit=BracketTakeProfitLeg(pct=0.10)
            )
        ]
    )
    with pytest.raises(ValueError, match="oco_bracket"):
        simulate(spec, {"AAA": [_bar(99, 99, 99, 99, "2024-01-01T00:00:00")]})


@pytest.mark.parametrize("bps", [-1.0, 10_000.0, 20_000.0, float("nan"), float("inf")])
def test_simulate_rejects_out_of_range_or_nonfinite_slippage(bps):
    spec = _spec([StopLossRule(pct=0.05)])
    with pytest.raises(ValueError, match="entry_slippage_bps"):
        simulate(
            spec, {"AAA": [_bar(99, 99, 99, 99, "2024-01-01T00:00:00")]}, entry_slippage_bps=bps
        )


def test_simulate_accepts_slippage_just_under_the_upper_bound():
    """Pins the ``[0, 10_000)`` contract from the acceptance side too, not
    just the rejection side above -- a tightened valid range would silently
    pass a rejection-only test suite."""
    spec = _spec([StopLossRule(pct=0.05)])
    simulate(
        spec,
        {"AAA": [_bar(99, 99, 99, 99, "2024-01-01T00:00:00")]},
        entry_slippage_bps=9_999.0,
    )  # must not raise


def test_simulate_rejects_empty_bars_for_a_symbol():
    spec = _spec([StopLossRule(pct=0.05)])
    with pytest.raises(ValueError, match="non-empty"):
        simulate(spec, {"AAA": []})


def test_simulate_rejects_non_increasing_timestamps():
    spec = _spec([StopLossRule(pct=0.05)])
    bars = [
        _bar(99, 99, 99, 99, "2024-01-02T00:00:00"),
        _bar(99, 99, 99, 99, "2024-01-01T00:00:00"),  # goes backwards
    ]
    with pytest.raises(ValueError, match="strictly increasing"):
        simulate(spec, {"AAA": bars})


def test_simulate_rejects_a_bar_symbol_mismatched_with_the_mapping_key():
    spec = _spec([StopLossRule(pct=0.05)])
    bars = [_bar(99, 99, 99, 99, "2024-01-01T00:00:00", symbol="AAA")]
    with pytest.raises(ValueError, match="mapping key"):
        simulate(spec, {"ZZZ": bars})


def test_simulate_rejects_a_target_symbol_missing_from_bars():
    """Without this check a target symbol simply absent from ``bars`` (but
    others present) silently produces no trades for it -- indistinguishable
    from a strategy that legitimately never triggered."""
    spec = _spec([StopLossRule(pct=0.05)], target_symbols=["AAA", "BBB"])
    bars = {"AAA": [_bar(99, 99, 99, 99, "2024-01-01T00:00:00")]}
    with pytest.raises(ValueError, match="missing"):
        simulate(spec, bars)


def test_simulate_rejects_target_symbols_against_an_empty_bars_mapping():
    spec = _spec([StopLossRule(pct=0.05)], target_symbols=["AAA"])
    with pytest.raises(ValueError, match="missing"):
        simulate(spec, {})


# ---------------------------------------------------------------------------
# ReferenceTrade.__post_init__ invariants
# ---------------------------------------------------------------------------


def _trade(**overrides) -> ReferenceTrade:
    kwargs = dict(
        trade_num=1,
        symbol="AAA",
        side="long",
        entry_bar=1,
        entry_rule_index=0,
        exit_bar=2,
        entry_date="2024-01-01",
        exit_date="2024-01-02",
        entry_price=100.0,
        exit_price=105.0,
        qty=1.0,
        exit_rule_kind="take_profit",
        exit_rule_index=0,
        level_index=None,
    )
    kwargs.update(overrides)
    return ReferenceTrade(**kwargs)


def test_valid_trade_constructs():
    assert _trade().exit_price == 105.0


def test_trade_rejects_an_empty_symbol():
    with pytest.raises(ValueError, match="symbol"):
        _trade(symbol="")


def test_trade_rejects_an_empty_entry_date():
    with pytest.raises(ValueError, match="entry_date"):
        _trade(entry_date="")


def test_trade_rejects_an_empty_exit_date():
    with pytest.raises(ValueError, match="exit_date"):
        _trade(exit_date="")


@pytest.mark.parametrize("field", ["symbol", "entry_date", "exit_date"])
def test_trade_rejects_a_non_string_value_for_a_string_field(field):
    """Truthiness alone would let a non-string, truthy value (e.g. an int)
    through -- the docstring promises a non-empty STRING, which ``not value``
    alone does not enforce."""
    with pytest.raises(ValueError, match=field):
        _trade(**{field: 123})


def test_trade_rejects_trade_num_below_one():
    with pytest.raises(ValueError, match="trade_num"):
        _trade(trade_num=0)


def test_trade_rejects_a_negative_entry_bar():
    with pytest.raises(ValueError, match="entry_bar"):
        _trade(entry_bar=-1)


@pytest.mark.parametrize("exit_bar", [0, 1])
def test_trade_rejects_exit_bar_not_strictly_after_entry_bar(exit_bar):
    with pytest.raises(ValueError, match="exit_bar"):
        _trade(entry_bar=1, exit_bar=exit_bar)


def test_trade_rejects_a_negative_entry_rule_index():
    with pytest.raises(ValueError, match="entry_rule_index"):
        _trade(entry_rule_index=-1)


def test_trade_rejects_a_negative_exit_rule_index():
    with pytest.raises(ValueError, match="exit_rule_index"):
        _trade(exit_rule_index=-1)


@pytest.mark.parametrize("qty", [0.0, -1.0])
def test_trade_rejects_nonpositive_qty(qty):
    with pytest.raises(ValueError, match="qty"):
        _trade(qty=qty)


@pytest.mark.parametrize("price", [0.0, -1.0, float("nan"), float("inf")])
def test_trade_rejects_nonpositive_or_nonfinite_entry_price(price):
    with pytest.raises(ValueError, match="entry_price"):
        _trade(entry_price=price)


@pytest.mark.parametrize("price", [0.0, -1.0, float("nan"), float("inf")])
def test_trade_rejects_nonpositive_or_nonfinite_exit_price(price):
    with pytest.raises(ValueError, match="exit_price"):
        _trade(exit_price=price)


def test_trade_rejects_a_bad_side():
    with pytest.raises(ValueError, match="side"):
        _trade(side="up")


def test_trade_rejects_an_unknown_exit_rule_kind():
    with pytest.raises(ValueError, match="exit_rule_kind"):
        _trade(exit_rule_kind="bogus")


def test_trade_scaled_take_profit_requires_a_level_index():
    with pytest.raises(ValueError, match="level_index"):
        _trade(exit_rule_kind="scaled_take_profit", level_index=None)


def test_trade_scaled_take_profit_rejects_a_negative_level_index():
    with pytest.raises(ValueError, match="level_index"):
        _trade(exit_rule_kind="scaled_take_profit", level_index=-1)


def test_trade_non_scaled_kind_rejects_a_level_index():
    with pytest.raises(ValueError, match="level_index"):
        _trade(exit_rule_kind="take_profit", level_index=0)


def test_trade_accepts_every_six_vocabulary_kind_directly():
    """simulate() itself never emits a bracket kind yet (oco_bracket specs are
    rejected), but the record type's own contract accepts all six §4 values —
    a future bracket-modelling step needs no schema change."""
    for kind in (
        "stop_loss",
        "take_profit",
        "signal_exit",
        "bracket_stop_loss",
        "bracket_take_profit",
    ):
        assert _trade(exit_rule_kind=kind).exit_rule_kind == kind
    assert _trade(exit_rule_kind="scaled_take_profit", level_index=0).level_index == 0


# ---------------------------------------------------------------------------
# Determinism, no-mutation, forbidden imports
# ---------------------------------------------------------------------------


def test_simulate_is_deterministic():
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 101, d[2]),
        _bar(101, 101, 94, 95, d[3]),
    ]
    spec = _spec([StopLossRule(pct=0.05, basis="entry_price")])
    first = simulate(spec, {"AAA": bars})
    second = simulate(spec, {"AAA": bars})
    assert first == second


def test_simulate_does_not_mutate_spec_or_bars():
    """Deep copies, not ``list(...)`` shallow copies: a shallow copy shares
    the same bar/rule objects with the original, so it can't detect an
    in-place mutation of one of them -- only that the list's own identity of
    elements didn't change. Compares the whole ``spec``, not just
    ``exit_rules``, so a mutation of any other field (``target_symbols``,
    etc.) is caught too."""
    d = _dates(4)
    bars = [
        _bar(99, 99, 99, 99, d[0]),
        _bar(101, 102, 100, 101, d[1]),
        _bar(101, 101, 101, 101, d[2]),
        _bar(101, 101, 94, 95, d[3]),
    ]
    spec = _spec([StopLossRule(pct=0.05, basis="entry_price")])
    bars_before = copy.deepcopy(bars)
    spec_before = copy.deepcopy(spec)
    simulate(spec, {"AAA": bars})
    assert bars == bars_before
    assert spec == spec_before


def test_module_imports_no_forbidden_engine_module():
    """The design doc's module boundary, asserted rather than left to prose:
    importing this module must not drag in the live engine or the live
    trading service (``trading_service.service``/``trading_service.engine``).

    Run in a subprocess for the same reason the sibling ``reference_exits``
    suite does: in this process the forbidden modules are already loaded by
    other tests, so checking ``sys.modules`` here would prove nothing.
    """
    from investment_team.strategy_lab.executor import reference_simulator

    code = (
        "import sys\n"
        f"sys.path[:] = {list(sys.path)!r}\n"
        f"import {reference_simulator.__name__}\n"
        "hits = [\n"
        "    m\n"
        "    for m in sys.modules\n"
        "    if m.endswith('trading_service.service')\n"
        "    or m.endswith('trading_service.engine')\n"
        "    or '.trading_service.engine.' in m\n"
        "]\n"
        "print(sorted(hits))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "[]", proc.stdout
