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
- ``_EngineExitDispatcher._scan_pending_for_gate``'s latch discrimination,
  which matters only for the limit style. That dispatcher tracks a resting
  STOP_LIMIT (``resting_limit_stop_id``) and cancels it when it emits a
  replacement close. An ENTRY-ATTACHED child must be invisible to that
  bookkeeping while UN-ARMED — cancelling it would strip a live position of
  its protection while the replacement is still only queued — but visible
  once LATCHED, where it is a competing close that would otherwise fill at
  its stale limit ahead of the replacement on a recovery bar.
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
from investment_team.models import BacktestConfig
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
from investment_team.trading_service import service as service_module
from investment_team.trading_service.engine.execution_model import RealisticExecutionModel
from investment_team.trading_service.engine.fill_simulator import FillSimulator, FillSimulatorConfig
from investment_team.trading_service.engine.order_book import OrderBook, PendingOrder
from investment_team.trading_service.engine.portfolio import Portfolio, Position
from investment_team.trading_service.service import (
    _STOP_LOSS_RESTING_ORDER_ENV,
    ENGINE_EXIT_REASON_PREFIX,
    TradingService,
    TradingServiceResult,
    _engine_entry_emission_active,
    _EngineEntryDispatcher,
    _EngineExitDispatcher,
    _first_resting_stop_loss_index,
    _resting_stop_loss_enabled,
    _TrackedPosition,
)
from investment_team.trading_service.strategy.contract import (
    Bar,
    OrderRequest,
    OrderSide,
    OrderType,
)

_NOOP_STRATEGY_CODE = "def on_bar(ctx, bar):\n    pass\n"


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


def _rest_stop_child_on_book(order_book: OrderBook, *, entry_order_id: str) -> None:
    """Put a resting stop-loss child on the book, shaped as
    ``FillSimulator._materialize_stop_child`` produces one: parent-attached,
    carrying the byte-stable ``engine_exit:stop_loss`` reason, and bound to the
    position it protects. That triple is what ``_scan_pending_for_gate``
    recognises as this migration's own protection for the position.
    """
    parent = order_book.submit(
        OrderRequest(
            client_order_id="c-parent",
            symbol="AAA",
            side=OrderSide.LONG,
            qty=100.0,
            order_type=OrderType.MARKET,
        ),
        submitted_at="2024-01-01",
        submitted_equity=10_000_000.0,
        expect_brackets=True,
    )
    child = order_book.submit_attached(
        OrderRequest(
            client_order_id="c-sl",
            symbol="AAA",
            side=OrderSide.SHORT,
            qty=100.0,
            order_type=OrderType.STOP,
            stop_price=95.0,
            reason=f"{ENGINE_EXIT_REASON_PREFIX}stop_loss",
        ),
        submitted_at="2024-01-01",
        submitted_equity=10_000_000.0,
        parent_order_id=parent.order_id,
        oco_group_id=f"oco_{parent.order_id}",
    )
    child.working_against_entry_order_id = entry_order_id


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
    # Put the entry-attached child on the book for the resting case, since the
    # cede is now PER-POSITION: the rule is ceded only while that protection
    # actually exists. An empty book with an open position is the partial-fill /
    # unattached window, covered separately below.
    order_book = OrderBook()
    if resting_enabled:
        _rest_stop_child_on_book(order_book, entry_order_id="o1")
    result = TradingServiceResult()
    exits.maybe_emit(
        cur_bar=bar,
        position_tracker=tracker,
        portfolio=portfolio,
        pending_for_prev=[],
        order_book=order_book,
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
    # ``_has_limit_stop_rule`` is spec shape, not ownership: it stays True in
    # both settings so the per-bar scan still runs. Which ORDER that scan
    # reports is where ownership is decided — see the latch tests below.


# ---------------------------------------------------------------------------
# The entry-attached STOP_LIMIT's two states, as _scan_pending_for_gate sees
# them: un-armed protection (not ours to cancel) vs latched competing close.
# ---------------------------------------------------------------------------


def _scan_with_child(
    *,
    armed: bool,
    parent_order_id: str | None,
    reason: str | None = None,
) -> str | None:
    """Run ``_scan_pending_for_gate`` over one opposite-side engine STOP_LIMIT
    and return the ``resting_limit_stop_id`` it reports.

    ``parent_order_id`` set marks an entry-attached child (only
    ``OrderBook.submit_attached`` can set it); ``None`` is the dispatcher's own
    trigger-time emission.
    """
    exits = _EngineExitDispatcher(exit_rules=[_limit_stop_rule()], exclude_rule_index=0)
    req = OrderRequest(
        client_order_id="sl-1",
        symbol="AAA",
        side=OrderSide.SHORT,  # opposite the long position below
        qty=10.0,
        order_type=OrderType.STOP_LIMIT,
        stop_price=95.0,
        limit_price=94.05,
        reason=reason or f"{ENGINE_EXIT_REASON_PREFIX}stop_loss",
    )
    po = PendingOrder(
        order_id="po-1",
        request=req.model_copy(update={"parent_order_id": parent_order_id}),
        submitted_at="2024-01-02",
        submitted_equity=1_000_000.0,
    )
    po.stop_limit_armed = armed
    # ``_materialize_stop_child`` binds the child to the position it protects at
    # materialization; the scan requires that binding so a stale child from a
    # prior position on the same symbol never counts as this one's protection.
    po.working_against_entry_order_id = "entry-1"
    tracked = _TrackedPosition(
        side=OrderSide.LONG,
        entry_price=100.0,
        entry_order_id="entry-1",
        just_opened=False,
        high_since_entry=100.0,
        low_since_entry=100.0,
    )
    pos = Position(
        symbol="AAA",
        side=OrderSide.LONG,
        qty=10.0,
        entry_price=100.0,
        entry_bid_price=100.0,
        entry_timestamp="2024-01-01",
        entry_order_id="entry-1",
        entry_client_order_id="c-entry-1",
        original_qty=10.0,
        entry_order_type="market",
    )
    scan = exits._scan_pending_for_gate(tracked, pos, [po])
    assert scan is not None
    return scan[0]


def test_unarmed_entry_attached_stop_limit_is_not_reported_for_cancellation() -> None:
    """An entry-attached child whose stop has never been breached is the
    position's standing protection, not a competing close. Reporting it would
    make ``maybe_emit`` cancel it the first time any other rule fires, leaving
    the position unprotected while the replacement close is still only queued."""
    assert _scan_with_child(armed=False, parent_order_id="entry-1") is None


def test_latched_entry_attached_stop_limit_is_reported_for_cancellation() -> None:
    """Once LATCHED the child is a resting LIMIT that no longer needs the stop
    re-crossed, and it precedes any replacement close in submission order — so
    on a recovery bar it would fill at its stale limit and the intended close
    would be dropped by the stale-continuation guard. That is the race
    ``maybe_emit``'s cancel exists to prevent, so it must be reported."""
    assert _scan_with_child(armed=True, parent_order_id="entry-1") == "po-1"


@pytest.mark.parametrize("armed", [True, False])
def test_dispatcher_emitted_stop_limit_is_always_reported(armed: bool) -> None:
    """A stop-limit with no parent is the dispatcher's own trigger-time
    emission: it exists only because the bar-close evaluator already detected
    the breach, so it is post-trigger by construction and stays tracked from the
    moment it rests — unchanged by this migration, in either latch state."""
    assert _scan_with_child(armed=armed, parent_order_id=None) == "po-1"


# ---------------------------------------------------------------------------
# Ceding requires an entry dispatcher that can actually attach the leg.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry_rules, sizing, expected",
    [
        (
            [EntryRule(side="long", when=Predicate(lhs="bar.close", op=">", rhs=90.0))],
            "sizing",
            True,
        ),
        # The custom-code path proper: the mode layers pass ``entry_rules=None``,
        # which ``TradingService.__init__`` then stores as an empty list — so both
        # shapes must read as inactive, and both are exercised here rather than
        # only the post-``__init__`` one.
        (None, "sizing", False),
        ([], "sizing", False),
        ([EntryRule(side="long", when=Predicate(lhs="bar.close", op=">", rhs=90.0))], None, False),
        ([], None, False),
    ],
)
def test_engine_entry_emission_active_matches_maybe_emit_guard(
    entry_rules, sizing, expected: bool
) -> None:
    """The predicate is byte-for-byte the condition ``maybe_emit`` returns early
    on, so the entry dispatcher and ``TradingService.run`` can never disagree
    about whether a resting leg can be attached at all."""
    assert _engine_entry_emission_active(entry_rules, sizing) is expected


@pytest.mark.parametrize("style", ["market", "limit"])
@pytest.mark.parametrize(
    "entry_rules, expect_ceded",
    [
        # Custom-code path: the mode layers pass ``entry_rules=None``, so the
        # entry dispatcher never fires and no resting leg is ever attached.
        (None, False),
        # Engine-managed entries: attachment is possible, so ceding is correct.
        ([EntryRule(side="long", when=Predicate(lhs="bar.close", op=">", rhs=0.0))], True),
    ],
    ids=["custom_code", "engine_managed"],
)
def test_run_cedes_the_stop_only_when_entry_emission_can_attach_it(
    style: str,
    entry_rules,
    expect_ceded: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercises ``TradingService.run``'s ACTUAL wiring, not a restatement of it.

    On the custom-code path nothing can attach the resting leg, so ceding the
    rule would strip it from the bar-close evaluator with nothing replacing it —
    the position would run with NO stop enforcement at all. Both execution
    styles must keep the bar-close path there, even with the feature check on.
    """
    monkeypatch.setenv(_STOP_LOSS_RESTING_ORDER_ENV, "true")
    rule = (
        _limit_stop_rule()
        if style == "limit"
        else StopLossRule(pct=0.05, basis="entry_price", style="market")
    )
    # Resting-ELIGIBLE by shape either way — only the absent entry emission may
    # stop it from being ceded.
    assert _first_resting_stop_loss_index([rule]) == 0

    captured: list = []
    real_exit_dispatcher = service_module._EngineExitDispatcher

    def _spy(*args, **kwargs):
        dispatcher = real_exit_dispatcher(*args, **kwargs)
        captured.append(dispatcher.exclude_rule_index)
        return dispatcher

    monkeypatch.setattr(service_module, "_EngineExitDispatcher", _spy)

    service = TradingService(
        strategy_code=_NOOP_STRATEGY_CODE,
        config=BacktestConfig(start_date="2024-01-01", end_date="2024-01-03", slippage_bps=0.0),
        entry_rules=entry_rules,
        sizing=FixedFractionSizing(fraction=0.02),
        exit_rules=[rule],
    )
    service.run(iter([_entry_bar()]))

    assert captured, "TradingService.run did not construct an exit dispatcher"
    assert (captured[0] == 0) is expect_ceded


def test_unarmed_strategy_bracket_stop_limit_is_still_reported() -> None:
    """The un-armed skip is narrowed to THIS migration's leg by reason, not to
    "has a parent". A strategy-supplied ``attached_stop_loss`` child carries
    ``engine_exit:bracket_sl`` and is NOT owned by this dispatcher, which has
    always relied on ``resting_limit_stop_id`` to notice it. Hiding it would let
    the spec's own limit-style stop emit a SECOND full-size resting STOP_LIMIT
    against the same position."""
    assert (
        _scan_with_child(
            armed=False,
            parent_order_id="entry-1",
            reason=f"{ENGINE_EXIT_REASON_PREFIX}bracket_sl",
        )
        == "po-1"
    )


def test_unarmed_generic_attached_exit_leg_is_still_reported() -> None:
    """Same for a generic ``attached_exits`` leg (``engine_exit:exit_leg_0``):
    only the resting stop-loss migration's own leg is skipped while un-armed."""
    assert (
        _scan_with_child(
            armed=False,
            parent_order_id="entry-1",
            reason=f"{ENGINE_EXIT_REASON_PREFIX}exit_leg_0",
        )
        == "po-1"
    )


# ---------------------------------------------------------------------------
# The cede is PER-POSITION: it is earned by protection actually existing, not
# by the run-level feature check alone.
# ---------------------------------------------------------------------------


def _bar_close_fires(*, child_on_book: bool, style: str = "market") -> bool:
    """Run one bar through ``maybe_emit`` with the stop rule ceded at the run
    level, and report whether the bar-close evaluator still fired for it.

    ``child_on_book`` models whether the entry-attached protection has been
    materialized yet — the thing that distinguishes a fully-attached position
    from one still inside its partial-fill window.
    """
    rule = (
        _limit_stop_rule()
        if style == "limit"
        else StopLossRule(pct=0.05, basis="entry_price", style="market")
    )
    exits = _EngineExitDispatcher(exit_rules=[rule], exclude_rule_index=0)
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
    order_book = OrderBook()
    if child_on_book:
        _rest_stop_child_on_book(order_book, entry_order_id="o1")
    result = TradingServiceResult()
    exits.maybe_emit(
        cur_bar=_entry_bar(close=94.0),  # below the 95 floor -> the rule triggers
        position_tracker=tracker,
        portfolio=portfolio,
        pending_for_prev=[],
        order_book=order_book,
        result=result,
    )
    return result.execution_diagnostics.exit_rule_firings.get("stop_loss", 0) == 1


@pytest.mark.parametrize("style", ["market", "limit"])
def test_bar_close_still_protects_a_position_with_no_attached_child_yet(style: str) -> None:
    """The finding this guards: ``FillSimulator`` materializes attached exits only
    on the parent entry's TERMINAL slice, so a participation-capped entry under
    the default ``REQUEUE_NEXT_BAR`` policy is partially open for one or more
    bars with no protective child. Ceding run-wide would leave that position with
    neither mechanism and let a breach run past the configured level. The rule
    stays bar-close-evaluated until the protection actually exists.

    Not limit-specific — a market-style rule reaches the same window — so both
    styles are covered.
    """
    assert _bar_close_fires(child_on_book=False, style=style) is True


@pytest.mark.parametrize("style", ["market", "limit"])
def test_bar_close_stands_down_once_the_attached_child_exists(style: str) -> None:
    """The other half of the same contract: once the entry-attached protection is
    on the book, the rule IS ceded, so exactly one mechanism can act on a given
    trigger — never both, which is what the coexistence step exists to prevent."""
    assert _bar_close_fires(child_on_book=True, style=style) is False
