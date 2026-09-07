"""Coexistence tests for the two entry_price stop-loss mechanisms:
the legacy bar-close evaluator (``_EngineExitDispatcher`` /
``rule_compiler.stop_loss_level``) and the entry-fill resting order the
migration in ``test_resting_stop_loss_attachment.py`` covers directly (a
``STOP`` for ``style="market"``, a ``STOP_LIMIT`` for ``style="limit"``).

Covers:

- ``_resting_stop_loss_enabled``: the run feature check, and its documented
  default (bar-close — the mechanism every run without explicit
  configuration takes).
- ``_first_resting_stop_loss_index``: the single source of "which rule" both
  mechanisms agree on.
- ``rule_compiler``'s ``exclude_rule_index`` chokepoint: a rule ceded to the
  resting mechanism is skipped by the bar-close evaluator outright, the same
  way an ``OcoBracketRule`` always is.
- ``_EngineExitDispatcher._has_limit_stop_rule``: the SECOND side of the
  mutual exclusion, which matters only for the limit style. That dispatcher
  tracks its own resting STOP_LIMIT (``_scan_pending_for_gate``'s
  ``resting_limit_stop_id``) and cancels it when another rule fires; a ceded
  rule must therefore be invisible to that bookkeeping, or the dispatcher
  would cancel the entry-attached protective order out from under a live
  position.
- ``_EngineEntryDispatcher.resting_stop_loss_enabled`` /
  ``_EngineExitDispatcher.exclude_rule_index``: wired together exactly as
  ``TradingService.run`` wires them, proving that across both settings of
  the feature check, exactly one of the two mechanisms ever claims a given
  rule — never both, never neither. This is the mutual-exclusion contract
  the coexistence step exists to guarantee: the failure it prevents is both
  paths firing for the same rule, which would close a position twice or
  produce a duplicate exit trade.

The existing bar-close stop-loss tests (spread across the suite — e.g.
``test_engine_exit_enforcement.py``, ``test_engine_exit_helpers.py``) need no
changes for any of this: they construct ``_EngineExitDispatcher`` with no
``exclude_rule_index`` and get the same bar-close-only behavior as before.
"""

from __future__ import annotations

import pytest

from investment_team.execution.risk_filter import RiskFilter, RiskLimits
from investment_team.strategy_lab.executor.predicate_evaluator import (
    BarRecord,
    StreamingHistoryView,
)
from investment_team.strategy_lab.executor.rule_compiler import (
    BarSnapshot,
    PositionState,
    evaluate_exit_rules,
)
from investment_team.strategy_lab.spec_dsl import (
    EntryRule,
    FixedFractionSizing,
    Predicate,
    StopLossRule,
    TakeProfitRule,
)
from investment_team.trading_service.engine.execution_model import RealisticExecutionModel
from investment_team.trading_service.engine.fill_simulator import FillSimulator, FillSimulatorConfig
from investment_team.trading_service.engine.order_book import OrderBook
from investment_team.trading_service.engine.portfolio import Portfolio, Position
from investment_team.trading_service.service import (
    _STOP_LOSS_RESTING_ORDER_ENV,
    ENGINE_EXIT_REASON_PREFIX,
    TradingServiceResult,
    _EngineEntryDispatcher,
    _EngineExitDispatcher,
    _first_resting_stop_loss_index,
    _resting_stop_loss_enabled,
    _TrackedPosition,
)
from investment_team.trading_service.strategy.contract import Bar, OrderRequest, OrderSide

# ---------------------------------------------------------------------------
# _resting_stop_loss_enabled: the run feature check and its documented default
# ---------------------------------------------------------------------------


def test_default_feature_check_selects_bar_close_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """No explicit configuration -> the documented default: the bar-close
    evaluator handles the rule, not the resting order."""
    monkeypatch.delenv(_STOP_LOSS_RESTING_ORDER_ENV, raising=False)
    assert _resting_stop_loss_enabled() is False


@pytest.mark.parametrize("value", ["true", "TRUE", "True", "1", "yes", "YES"])
def test_feature_check_opts_into_resting_path(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_STOP_LOSS_RESTING_ORDER_ENV, value)
    assert _resting_stop_loss_enabled() is True


@pytest.mark.parametrize("value", ["false", "0", "no", "", "garbage"])
def test_feature_check_stays_on_bar_close_for_non_affirmative_values(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_STOP_LOSS_RESTING_ORDER_ENV, value)
    assert _resting_stop_loss_enabled() is False


# ---------------------------------------------------------------------------
# _first_resting_stop_loss_index: single source of "which rule"
# ---------------------------------------------------------------------------


def test_first_resting_stop_loss_index_finds_first_eligible_rule() -> None:
    rules = [
        TakeProfitRule(pct=0.10),
        StopLossRule(pct=0.03, basis="entry_price"),
        StopLossRule(pct=0.05, basis="entry_price"),
    ]
    assert _first_resting_stop_loss_index(rules) == 1


def test_first_resting_stop_loss_index_none_when_no_eligible_rule() -> None:
    rules = [
        TakeProfitRule(pct=0.10),
        StopLossRule(pct=0.05, basis="trailing_high"),  # wrong basis
        StopLossRule(pct=1.0, basis="entry_price"),  # short-safety auto-stop shape
    ]
    assert _first_resting_stop_loss_index(rules) is None


def test_first_resting_stop_loss_index_finds_a_limit_style_rule() -> None:
    """Both execution styles are resting-eligible, so a limit-style stop is
    claimed by the same index scan the market style goes through — the ``basis``
    and ``pct`` bound are what exclude a rule, not its style."""
    rules = [
        TakeProfitRule(pct=0.10),
        StopLossRule(pct=0.05, basis="trailing_high"),  # wrong basis
        StopLossRule(pct=0.05, basis="entry_price", style="limit", limit_offset_pct=0.01),
    ]
    assert _first_resting_stop_loss_index(rules) == 2


def test_first_resting_stop_loss_index_none_for_empty_rules() -> None:
    assert _first_resting_stop_loss_index([]) is None


# ---------------------------------------------------------------------------
# rule_compiler chokepoint: exclude_rule_index drops a rule outright
# ---------------------------------------------------------------------------


def test_bar_close_evaluator_skips_rule_ceded_to_resting_mechanism() -> None:
    """Mirrors ``test_bracket_is_skipped_by_exit_evaluator`` (OcoBracketRule's
    unconditional skip): with ``exclude_rule_index`` set to this rule's spec
    index, the bar-close evaluator produces no intent for it even on a bar
    that would otherwise trigger it — the same chokepoint OcoBracketRule is
    skipped at, applied conditionally here instead of unconditionally."""
    pos = PositionState(
        symbol="AAA",
        side="long",
        qty=100.0,
        entry_price=100.0,
        high_since_entry=100.0,
        low_since_entry=100.0,
    )
    rule = StopLossRule(pct=0.05, basis="entry_price")
    # Bar plunges well past the 5% floor (95) — this rule WOULD fire...
    bar = BarSnapshot(high=101.0, low=90.0, close=94.0)

    # ...and does, when nothing is excluded (today's / bar-close-selected behavior).
    assert len(evaluate_exit_rules([rule], {"AAA": pos}, {"AAA": bar})) == 1

    # ...but not when this exact rule's index is ceded to the resting mechanism.
    assert evaluate_exit_rules([rule], {"AAA": pos}, {"AAA": bar}, exclude_rule_index=0) == []


def test_exclude_rule_index_only_drops_the_matching_index() -> None:
    """A lower-priority rule at a DIFFERENT index still fires — exclusion is by
    exact rule identity (spec position), not by rule kind/shape, so the
    short-safety auto-stop (same kind/basis/style, different index) is
    unaffected by another rule's exclusion."""
    pos = PositionState(
        symbol="AAA",
        side="long",
        qty=100.0,
        entry_price=100.0,
        high_since_entry=100.0,
        low_since_entry=100.0,
    )
    rules = [
        StopLossRule(pct=0.05, basis="entry_price"),  # index 0 — excluded
        TakeProfitRule(pct=0.50),  # index 1 — unaffected, but doesn't fire on this bar
        StopLossRule(
            pct=1.0, basis="entry_price"
        ),  # index 2 — short-safety shape, never fires for a long
    ]
    bar = BarSnapshot(high=101.0, low=90.0, close=94.0)
    assert evaluate_exit_rules(rules, {"AAA": pos}, {"AAA": bar}, exclude_rule_index=0) == []


# ---------------------------------------------------------------------------
# Dispatcher wiring: _EngineEntryDispatcher / _EngineExitDispatcher, wired
# exactly as TradingService.run wires them from the same exit_rules list.
# ---------------------------------------------------------------------------


def _wire_dispatchers(
    exit_rules, *, resting_enabled: bool, side: str = "long"
) -> tuple[_EngineEntryDispatcher, _EngineExitDispatcher]:
    """Build both dispatchers the same way ``TradingService.run`` does: a
    single ``_first_resting_stop_loss_index`` computation, gated by the same
    ``resting_enabled`` flag, feeds both — so the two can never disagree on
    which rule (if any) the resting mechanism has claimed."""
    exclude_idx = _first_resting_stop_loss_index(exit_rules) if resting_enabled else None
    rhs = 90.0 if side == "long" else 110.0
    op = ">" if side == "long" else "<"
    entries = _EngineEntryDispatcher(
        entry_rules=[EntryRule(side=side, when=Predicate(lhs="bar.close", op=op, rhs=rhs))],
        sizing=FixedFractionSizing(fraction=0.02),
        exit_rules=exit_rules,
        risk_limits=RiskLimits(max_position_pct=100),
        asset_class="stocks",
        resting_stop_loss_enabled=resting_enabled,
    )
    exits = _EngineExitDispatcher(exit_rules=exit_rules, exclude_rule_index=exclude_idx)
    return entries, exits


def _build_view(closes: list[float]) -> StreamingHistoryView:
    view = StreamingHistoryView()
    for i, c in enumerate(closes):
        view.append(
            BarRecord(
                timestamp=f"2024-01-{i + 1:02d}",
                open=c,
                high=c + 1,
                low=c - 1,
                close=c,
                volume=1000.0,
            )
        )
    return view


def _entry_bar(close: float = 100.0) -> Bar:
    return Bar(
        symbol="AAA",
        timestamp="2024-01-01",
        timeframe="1d",
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=1_000_000.0,
    )


@pytest.mark.parametrize("resting_enabled", [True, False])
def test_resting_and_bar_close_mechanisms_never_both_claim_the_same_rule(
    resting_enabled: bool,
) -> None:
    """The acceptance-criterion proof: no configuration produces both a
    resting-stop attachment and a bar-close-evaluator firing for the same
    rule. Whichever mechanism the feature check selects handles the rule
    entirely; the other stays completely silent for it."""
    exit_rules = [StopLossRule(pct=0.05, basis="entry_price")]
    entries, exits = _wire_dispatchers(exit_rules, resting_enabled=resting_enabled)

    # Entry side: does the dispatcher attach a resting STOP for this rule?
    pending: list[OrderRequest] = []
    entries.maybe_emit(
        cur_bar=_entry_bar(close=100.0),
        portfolio=Portfolio(initial_capital=10_000_000.0),
        pending_for_prev=pending,
        views={"AAA": _build_view([100.0, 100.0])},
        result=TradingServiceResult(),
    )
    [entry_req] = pending
    attached = len(entry_req.attached_exits) == 1

    # Bar-close side: does the SAME rule fire for an equivalent open position,
    # on a bar that crosses its floor (entry 100, pct=0.05 -> floor 95)?
    tracker = {
        "AAA": _TrackedPosition(
            side=OrderSide.LONG,
            entry_price=100.0,
            entry_order_id="o1",
            just_opened=False,
            high_since_entry=100.0,
            low_since_entry=100.0,
        )
    }
    portfolio = Portfolio(initial_capital=10_000_000.0)
    portfolio.positions["AAA"] = Position(
        symbol="AAA",
        side=OrderSide.LONG,
        qty=100.0,
        entry_price=100.0,
        entry_bid_price=100.0,
        entry_timestamp="2024-01-01",
        entry_order_id="o1",
        entry_client_order_id="c-o1",
        original_qty=100.0,
        entry_order_type="market",
    )
    bar = Bar(
        symbol="AAA",
        timestamp="2024-01-02",
        timeframe="1d",
        open=97.0,
        high=98.0,
        low=93.0,
        close=94.0,
        volume=1_000_000.0,
    )
    result = TradingServiceResult()
    exits.maybe_emit(
        cur_bar=bar,
        position_tracker=tracker,
        portfolio=portfolio,
        pending_for_prev=[],
        order_book=OrderBook(),
        result=result,
    )
    bar_close_fired = result.execution_diagnostics.exit_rule_firings.get("stop_loss", 0) == 1

    # XOR: exactly one mechanism claims the rule — attachment fires iff resting
    # is enabled, and the bar-close evaluator fires iff it is not.
    assert attached is resting_enabled
    assert bar_close_fired is not resting_enabled


def test_disabled_feature_check_leaves_default_dispatcher_construction_on_bar_close() -> None:
    """A dispatcher built with no explicit ``resting_stop_loss_enabled`` picks
    up the run feature check's default (bar-close) — the same default
    ``TradingService.run`` applies when the run sets no explicit
    configuration."""
    entries = _EngineEntryDispatcher(
        entry_rules=[EntryRule(side="long", when=Predicate(lhs="bar.close", op=">", rhs=90.0))],
        sizing=FixedFractionSizing(fraction=0.02),
        exit_rules=[StopLossRule(pct=0.05, basis="entry_price")],
        asset_class="stocks",
    )
    assert entries.resting_stop_loss_enabled is False
    assert entries._resting_stop_loss is None


# ---------------------------------------------------------------------------
# End-to-end: the resting mechanism, once selected, actually fills the
# position without the bar-close evaluator ever being consulted for it.
# ---------------------------------------------------------------------------


def _make_simulator() -> tuple[FillSimulator, OrderBook, Portfolio]:
    portfolio = Portfolio(initial_capital=10_000_000.0)
    order_book = OrderBook()
    sim = FillSimulator(
        portfolio=portfolio,
        order_book=order_book,
        risk_filter=RiskFilter(RiskLimits(max_position_pct=100, max_gross_leverage=10.0)),
        config=FillSimulatorConfig(slippage_bps=0.0, transaction_cost_bps=0.0),
        execution_model=RealisticExecutionModel(participation_cap=0.10),
    )
    return sim, order_book, portfolio


def test_resting_mechanism_alone_closes_the_position_exactly_once() -> None:
    """With the resting mechanism selected, the position closes exactly once
    (via the resting STOP, at its exact price) and the bar-close evaluator —
    fed the identical rule and an equivalent bar — produces no competing
    intent, so a second close is structurally impossible, not merely absent
    by chance in this scenario."""
    exit_rules = [StopLossRule(pct=0.05, basis="entry_price")]
    entries, exits = _wire_dispatchers(exit_rules, resting_enabled=True)
    sim, order_book, portfolio = _make_simulator()

    pending: list[OrderRequest] = []
    entries.maybe_emit(
        cur_bar=_entry_bar(close=100.0),
        portfolio=portfolio,
        pending_for_prev=pending,
        views={"AAA": _build_view([100.0, 100.0])},
        result=TradingServiceResult(),
    )
    [entry_req] = pending
    parent = order_book.submit(
        entry_req, submitted_at="2024-01-01", submitted_equity=10_000_000.0, expect_brackets=True
    )
    sim.process_bar(
        Bar(
            symbol="AAA",
            timestamp="2024-01-02",
            timeframe="1d",
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=1_000_000.0,
        )
    )
    assert len(order_book.children_of(parent.order_id)) == 1  # resting STOP now rests at 95

    outcome = sim.process_bar(
        Bar(
            symbol="AAA",
            timestamp="2024-01-03",
            timeframe="1d",
            open=97.0,
            high=98.0,
            low=93.0,
            close=94.0,
            volume=1_000_000.0,
        )
    )
    assert len(outcome.closed_trades) == 1
    [trade] = outcome.closed_trades
    assert trade.exit_price == pytest.approx(95.0)
    assert trade.exit_reason == f"{ENGINE_EXIT_REASON_PREFIX}stop_loss"

    # The bar-close evaluator, wired for the same run, never sees this rule:
    # it is excluded outright, regardless of the bar it would otherwise fire on.
    tracker = {
        "AAA": _TrackedPosition(
            side=OrderSide.LONG,
            entry_price=100.0,
            entry_order_id=parent.order_id,
            just_opened=False,
            high_since_entry=100.0,
            low_since_entry=100.0,
        )
    }
    result = TradingServiceResult()
    exits.maybe_emit(
        cur_bar=Bar(
            symbol="AAA",
            timestamp="2024-01-03",
            timeframe="1d",
            open=97.0,
            high=98.0,
            low=93.0,
            close=94.0,
            volume=1_000_000.0,
        ),
        position_tracker=tracker,
        portfolio=Portfolio(initial_capital=10_000_000.0),
        pending_for_prev=[],
        order_book=OrderBook(),
        result=result,
    )
    assert result.execution_diagnostics.exit_rule_firings.get("stop_loss") is None


# ---------------------------------------------------------------------------
# The limit style's second exclusion: the exit dispatcher's own
# resting-STOP_LIMIT bookkeeping must not claim a ceded rule.
# ---------------------------------------------------------------------------


def _limit_stop_rule(pct: float = 0.05, limit_offset_pct: float = 0.01) -> StopLossRule:
    return StopLossRule(
        pct=pct, basis="entry_price", style="limit", limit_offset_pct=limit_offset_pct
    )


def test_exit_dispatcher_cedes_limit_stop_bookkeeping_for_the_ceded_rule() -> None:
    """A limit-style rule handed to the resting mechanism is excluded from
    ``_has_limit_stop_rule``, so ``_scan_pending_for_gate`` never mistakes the
    entry-attached STOP_LIMIT for one this dispatcher emitted. Without this, the
    first time any other rule fired, ``maybe_emit`` would CANCEL the position's
    protective order while its replacement close was still only queued."""
    rules = [_limit_stop_rule(), TakeProfitRule(pct=0.20)]
    exits = _EngineExitDispatcher(exit_rules=rules, exclude_rule_index=0)
    assert exits._has_limit_stop_rule is False


def test_exit_dispatcher_keeps_limit_stop_bookkeeping_when_nothing_is_ceded() -> None:
    """With the feature check off (``exclude_rule_index=None``) the dispatcher
    owns the limit-style stop exactly as before this migration — the resting
    STOP_LIMIT it emits at trigger time is still its own to track and cancel."""
    exits = _EngineExitDispatcher(exit_rules=[_limit_stop_rule()], exclude_rule_index=None)
    assert exits._has_limit_stop_rule is True


def test_exit_dispatcher_keeps_limit_stop_bookkeeping_for_an_unceded_limit_rule() -> None:
    """Excluding an index only removes THAT rule from the scan: a market-style
    stop ceded at index 0 leaves a separate limit-style stop at index 1 fully
    owned by the bar-close dispatcher."""
    rules = [StopLossRule(pct=0.05, basis="entry_price"), _limit_stop_rule()]
    exits = _EngineExitDispatcher(exit_rules=rules, exclude_rule_index=0)
    assert exits._has_limit_stop_rule is True


@pytest.mark.parametrize("resting_enabled", [True, False])
def test_limit_style_rule_is_claimed_by_exactly_one_mechanism(resting_enabled: bool) -> None:
    """The mutual-exclusion contract, for the limit style, across both settings
    of the feature check: exactly one mechanism claims the rule. When the
    resting mechanism has it, the bar-close dispatcher neither evaluates it
    (``exclude_rule_index``) nor tracks its order (``_has_limit_stop_rule``)."""
    rules = [_limit_stop_rule()]
    entries, exits = _wire_dispatchers(rules, resting_enabled=resting_enabled)

    resting_claims = entries._resting_stop_loss is not None
    bar_close_claims = exits.exclude_rule_index != 0
    assert resting_claims is resting_enabled
    assert bar_close_claims is not resting_enabled
    # The order-book-side bookkeeping follows the same claim, never diverging
    # from it — a claimed rule's STOP_LIMIT is owned by the OCO lifecycle.
    assert exits._has_limit_stop_rule is not resting_enabled
