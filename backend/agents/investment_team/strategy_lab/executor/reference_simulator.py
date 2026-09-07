"""Combined multi-kind driver for the reference-ledger simulator.

Step 4 of the reference-ledger simulator designed in
``system_design/reference_ledger_trade_model.md`` — the module that finally
answers the question the whole simulator exists to answer: *given a spec's
entry/exit rules and a fixed sequence of bars, what is the complete list of
trades?* :mod:`reference_entries` and :mod:`reference_exits` each model one
rule kind in isolation, walking the whole bar series "as if the other kinds'
rules did not exist" (their own module docstrings say so explicitly). Joining
them is not concatenation: a ``scaled_take_profit`` ladder's earlier rungs
must contribute to the recorded ``exit_price`` even when a DIFFERENT rule
(a ``stop_loss`` or a ``signal_exit``) performs the position's final close,
and a position opened but never closed needs the same documented treatment
the real engine gives one — no synthetic force-close.

This module builds one :class:`RestingStopLoss` and one
:class:`RestingTakeProfitFamily` (both from :mod:`reference_exits`) per open
position and drives them bar by bar via their ``peek``/``commit``/``advance``
split, so it can compare a stop candidate against a take-profit-family
candidate BEFORE either commits, exactly the comparison the two modules'
standalone ``replay_*`` wrappers cannot make (each drives its own book to
completion in isolation). ``SignalExitRule`` has no analogous stepper object
— its own trigger check is genuinely stateless per bar (see
:func:`_peek_signal_exit`) — so this module evaluates it directly via the
same shared ``rule_compiler.evaluate_exit_rules_for_position``
:func:`~.reference_exits.resolve_signal_exit` itself calls.

Per-bar evaluation order
------------------------
Every open position, on every bar, is processed in this fixed order (design
doc §5 "Per-bar evaluation order"):

1. **Resting candidates**, once eligible (``entry_bar + 1`` onward — a
   resting order is not eligible on its own materialization bar). Both books
   are peeked; a two-way tie breaks by ascending working-rules index, the
   same tie-break ``rule_compiler.first_exit_intent_for_position`` already
   uses. Only the winner commits; the stop book's watermark advances exactly
   once regardless of which book (if either) wins.
2. **A signal exit queued on an earlier bar, due to fill THIS bar** — but
   only reached if step 1 did not already fully close the position: a
   reachable resting order beats a same-fill-bar queued ``signal_exit`` close
   (production's FIFO-by-submission-order rule), while a merely PARTIAL rung
   does not — the position is still open, so the queued close still fires
   against whatever remains, blended with any partial rungs via
   :meth:`~.reference_exits.RestingTakeProfitFamily.blend_terminal`.
3. **A fresh ``signal_exit`` trigger check** (eligible from ``entry_bar``
   itself, unlike the resting kinds), queuing a close for the NEXT bar's open
   when one fires. The moment a new signal is queued, any resting
   ``style="limit"`` stop is retired outright
   (:meth:`~.reference_exits.RestingStopLoss.retire_limit_style_rules`) —
   production excludes a resting limit-style stop from further evaluation the
   instant a competing whole-position close is chosen, so it must not get a
   later chance to win step 1 via FIFO against the now-queued signal.

Exits are resolved for a symbol before its entries are re-evaluated on the
SAME bar, and entry suppression reads the POST-exit state — so a position
that closes on bar ``i`` does not block a fresh entry trigger on that same
bar (design doc's third ordering rule). This is what makes re-entry work:
:mod:`reference_entries`'s own ``replay_entry_rules`` never re-opens a
symbol; this module's own bar walk does, by construction.

Deliberately three separate per-bar rule-decision calls, not one
-------------------------------------------------------------------
The stop book, the take-profit family, and the signal-exit check each pass
the shared ``evaluate_exit_rules_for_position`` a DIFFERENT ``PositionState``:
the stop book's watermark genuinely ratchets bar over bar; the take-profit
family's is FROZEN at the post-slippage anchor (the frozen watermark is what
makes reusing the shared evaluator's watermark-based rung test behave like a
current-bar-only test — see ``RestingTakeProfitFamily``'s own docstring for
the proof); the signal-exit check's carries the PRE-slippage entry price and
is never read by a signal predicate at all. Merging these into one call would
silently break the take-profit family's fabricated-fill guarantee — three
calls per bar is the cost of not doing that.

Cross-symbol emission order
----------------------------
Each symbol is walked independently (there is no shared equity ledger yet to
couple them — see "What this module does not model" below), and every
resulting trade is then stably sorted by ``(exit bar timestamp, symbol)``
before ``trade_num`` is assigned, 1-based, in that final order. This
reproduces the design doc's global emission order — a trade is emitted at its
final closing event, ordered across symbols by ``(timestamp, symbol)``, the
same tie-break ``HistoricalReplayStream.__iter__`` uses — without needing a
genuinely interleaved walk, PRECISELY BECAUSE no state this module tracks
(no equity, no capital, no risk gates) couples one symbol's bar-by-bar
decisions to another's. That equivalence ends the moment a later step adds
any of those: a real walk would then have to interleave symbols bar by bar
for the shared state to stay correct, not merely for correct trade ORDERING.

What this module does not model (see the design doc for the full design)
--------------------------------------------------------------------------
* **Quantity is always the nominal ``1.0``.** Real sizing needs
  ``spec.sizing``'s per-kind formulas, the ``max_position_pct`` clamp,
  whole-share handling, the risk-limit admission gates
  (``max_open_positions``/``max_gross_leverage``/
  ``max_symbol_concentration_pct``), and a running capital/equity ledger —
  none of which exist yet. ``1.0`` is the same nominal both
  :class:`~.reference_exits.RestingStopLoss` and
  :class:`~.reference_exits.RestingTakeProfitFamily` already use internally,
  and it satisfies :class:`ReferenceTrade`'s own ``qty > 0`` invariant. A
  caller diffing these records against production's real, sized ``qty``
  must not expect them to match until that layer is built.
* **``oco_bracket`` is out of scope entirely.** :func:`simulate` REJECTS a
  spec whose working exit rules contain an ``OcoBracketRule`` rather than
  silently ignoring it or modelling only some of its legs — a bracket spec
  produced no reference trades at all before this change, and a partial,
  silently-wrong model would be worse than a clear rejection. Modelling both
  bracket legs (OCO sibling cancellation, the same-bar double-touch tie-break
  where the stop leg wins) is future work.
* **No reference-side analogue of ``open_position_entry_reasons``.** A
  position still open when a symbol's bars run out — including one holding
  only a partially-reduced ladder remainder — simply produces no
  ``ReferenceTrade``, mirroring production's own treatment
  (``TradingServiceResult`` reports it via a separate entry-reason list, never
  as a synthetic force-close ``TradeRecord``); this module has no equivalent
  list to populate.
* **``simulate`` omits the design doc's ``starting_equity`` parameter.** The
  doc's signature is ``simulate(spec, bars, starting_equity,
  entry_slippage_bps)`` — ``starting_equity``'s only specified use is seeding
  the equity figure entry-quantity sizing resolves against, and sizing is not
  modelled yet (see above), so accepting the parameter here would be dead
  weight this module cannot honor. It will be added when the sizing layer
  lands; see the design doc's own "Implementation status" note.

Exclusions
----------
Per the design doc's module boundary (shared with :mod:`reference_entries`
and :mod:`reference_exits`), nothing here imports — directly or
transitively — ``trading_service/service.py`` or
``trading_service/engine/{fill_simulator,order_book,execution_model,portfolio}.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Literal, Mapping, NamedTuple, Optional, Sequence, Tuple

from ...models import StrategySpec
from ..spec_dsl import ExitRule, OcoBracketRule
from .predicate_evaluator import HistoryView, PandasHistoryView, evaluate_entry_rules
from .reference_entries import ReferenceEntryFill, bars_to_frame, fill_entry_at
from .reference_exits import (
    PrefixHistoryView,
    RestingStopLoss,
    RestingTakeProfitFamily,
    bar_snapshot,
    decimals_for,
    entry_price_basis,
    round_reference_price,
    scaled_take_profit_rules,
    signal_exit_rules,
    stop_loss_rules_for_side,
    take_profit_rules,
    working_exit_rules,
)
from .rule_compiler import PositionState, evaluate_exit_rules_for_position

if TYPE_CHECKING:
    # Deferred for the same reason the sibling modules defer it: importing any
    # ``trading_service`` submodule at runtime executes
    # ``trading_service/__init__.py`` -> ``service.py``, which top-level-imports
    # every forbidden ``engine/`` module. ``from __future__ import
    # annotations`` makes every annotation here a string, so the name below is
    # never resolved at runtime.
    from ...trading_service.strategy.contract import Bar

ExitRuleKind = Literal[
    "stop_loss",
    "take_profit",
    "scaled_take_profit",
    "signal_exit",
    "bracket_stop_loss",
    "bracket_take_profit",
]
_EXIT_RULE_KINDS = frozenset(
    (
        "stop_loss",
        "take_profit",
        "scaled_take_profit",
        "signal_exit",
        "bracket_stop_loss",
        "bracket_take_profit",
    )
)


@dataclass(frozen=True)
class ReferenceTrade:
    """One fully closed reference position — entry and exit together.

    The design doc's §3 record, joining :class:`~.reference_entries.ReferenceEntryFill`
    with whichever exit kind performed the position's final close. Construction
    validates every invariant immediately and raises ``ValueError`` on
    violation — the same fail-fast shape ``ExitIntent`` and the three narrower
    exit records already use, so a ``ReferenceTrade`` cannot exist in an
    invalid state regardless of caller (this module's own :func:`simulate`, a
    test, or a future matching module's translation adapter).

    Field order matches the design doc's §3 table exactly.
    """

    trade_num: int
    symbol: str
    side: Literal["long", "short"]
    entry_bar: int
    entry_rule_index: int
    exit_bar: int
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    qty: float
    exit_rule_kind: ExitRuleKind
    exit_rule_index: int
    level_index: Optional[int] = None

    def __post_init__(self) -> None:
        """Enforce this record's structural contract at construction.

        Preconditions: none beyond typing.
        Postconditions: raises ``ValueError`` when any of the following does
        not hold, otherwise the instance is structurally valid:
        ``trade_num >= 1``; ``entry_bar >= 0``; ``entry_bar < exit_bar``
        (strict — no modeled exit kind can complete on ``entry_bar`` itself);
        ``entry_rule_index >= 0`` and ``exit_rule_index >= 0``; ``qty > 0``;
        ``entry_price``/``exit_price`` are positive finite numbers; ``side``
        is ``"long"`` or ``"short"``; ``exit_rule_kind`` is one of the six §4
        vocabulary values; and ``level_index is not None`` if and only if
        ``exit_rule_kind == "scaled_take_profit"`` (and, when present,
        ``level_index >= 0``).
        """
        if self.trade_num < 1:
            raise ValueError(f"trade_num must be >= 1, got {self.trade_num!r}")
        if self.entry_bar < 0:
            raise ValueError(f"entry_bar must be >= 0, got {self.entry_bar!r}")
        if self.exit_bar <= self.entry_bar:
            raise ValueError(
                f"exit_bar must be > entry_bar ({self.entry_bar!r}), got {self.exit_bar!r}"
            )
        if self.entry_rule_index < 0:
            raise ValueError(f"entry_rule_index must be >= 0, got {self.entry_rule_index!r}")
        if self.exit_rule_index < 0:
            raise ValueError(f"exit_rule_index must be >= 0, got {self.exit_rule_index!r}")
        if not self.qty > 0:
            raise ValueError(f"qty must be > 0, got {self.qty!r}")
        if not (self.entry_price > 0 and math.isfinite(self.entry_price)):
            raise ValueError(
                f"entry_price must be a positive finite number, got {self.entry_price!r}"
            )
        if not (self.exit_price > 0 and math.isfinite(self.exit_price)):
            raise ValueError(
                f"exit_price must be a positive finite number, got {self.exit_price!r}"
            )
        if self.side not in ("long", "short"):
            raise ValueError(f"side must be 'long' or 'short', got {self.side!r}")
        if self.exit_rule_kind not in _EXIT_RULE_KINDS:
            raise ValueError(
                f"exit_rule_kind must be one of {sorted(_EXIT_RULE_KINDS)!r}, "
                f"got {self.exit_rule_kind!r}"
            )
        if self.exit_rule_kind == "scaled_take_profit":
            if self.level_index is None:
                raise ValueError(
                    "level_index is required when exit_rule_kind is 'scaled_take_profit'"
                )
            if self.level_index < 0:
                raise ValueError(f"level_index must be >= 0, got {self.level_index!r}")
        elif self.level_index is not None:
            raise ValueError(
                f"level_index must be None when exit_rule_kind is {self.exit_rule_kind!r}, "
                f"got {self.level_index!r}"
            )


class _RawTrade(NamedTuple):
    """One closed position's full :class:`ReferenceTrade` payload, minus ``trade_num``.

    ``trade_num`` is assigned only once, in a single final pass after every
    symbol's independent walk completes and every raw trade is merged into
    one global emission order (see :func:`simulate`'s own docstring) — so this
    intermediate additionally carries the exit bar's FULL ISO timestamp
    (``exit_sort_key``), needed only to order trades across symbols before
    that assignment and discarded once it is applied. ``ReferenceTrade``
    itself carries just the truncated ``exit_date``, matching production's own
    ``TradeRecord``.
    """

    exit_sort_key: str
    symbol: str
    side: Literal["long", "short"]
    entry_bar: int
    entry_rule_index: int
    exit_bar: int
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    qty: float
    exit_rule_kind: ExitRuleKind
    exit_rule_index: int
    level_index: Optional[int]


@dataclass
class _OpenPosition:
    """Mutable per-position bookkeeping the bar walk owns while a position is open.

    Unlike the frozen records elsewhere in this module's sibling modules, this
    is pure internal driver state, discarded the moment the position closes
    (or the bars run out with it still open) — never exposed to a caller.

    ``pending_signal`` is ``(exit_rule_index, fill_bar)`` for a
    ``signal_exit`` trigger detected on an earlier bar and not yet resolved,
    or ``None`` when no signal is currently queued.
    """

    entry: ReferenceEntryFill
    stop_book: Optional[RestingStopLoss]
    tp_book: Optional[RestingTakeProfitFamily]
    pending_signal: Optional[Tuple[int, int]] = None


def _open_position(
    fill: ReferenceEntryFill,
    working_rules: Sequence[ExitRule],
    entry_slippage_bps: float,
) -> _OpenPosition:
    """Arm a freshly filled position's resting-order books.

    Preconditions: ``fill`` is a just-produced entry fill; ``working_rules``
    is the WORKING exit-rule list from :func:`~.reference_exits.working_exit_rules`
    (not raw ``spec.exit_rules``); ``entry_slippage_bps`` is finite and in
    ``[0, 10_000)``.
    Postconditions: returns an ``_OpenPosition`` with ``stop_book`` set when
    ``working_rules`` contains at least one side-compatible ``StopLossRule``,
    else ``None``; ``tp_book`` set when ``working_rules`` contains at least
    one ``TakeProfitRule``/``ScaledTakeProfitRule``, else ``None``;
    ``pending_signal`` starts ``None``. Both books, when present, are anchored
    at the same post-slippage :func:`~.reference_exits.entry_price_basis`,
    computed only when at least one book actually needs it — a signal-only
    spec (no stop/take-profit rules at all) never calls it, so a fill price
    small enough that the anchor would round to zero cannot abort the run
    over an anchor neither book would have used anyway.
    """
    stop_candidates = stop_loss_rules_for_side(working_rules, fill.side)
    has_tp_family = bool(take_profit_rules(working_rules)) or bool(
        scaled_take_profit_rules(working_rules)
    )
    anchor = (
        entry_price_basis(fill.entry_price, fill.side, entry_slippage_bps)
        if stop_candidates or has_tp_family
        else None
    )
    stop_book = (
        RestingStopLoss(side=fill.side, symbol=fill.symbol, anchor=anchor, rules=stop_candidates)
        if stop_candidates
        else None
    )
    tp_book = (
        RestingTakeProfitFamily(
            side=fill.side, symbol=fill.symbol, anchor=anchor, rules=working_rules
        )
        if has_tp_family
        else None
    )
    return _OpenPosition(entry=fill, stop_book=stop_book, tp_book=tp_book)


def _finalize_exit_price(pos: _OpenPosition, raw_closing_price: float) -> Optional[float]:
    """The rounded ``ReferenceTrade.exit_price`` for a stop/signal closing fill.

    Applies the design doc's uniform "Nonpositive exit references" rule at
    the point this module's own aggregation introduces: a raw fill price that
    is not finite and positive suppresses this candidate's fire, exactly as if
    its trigger had not been met, and — new here — so does a price that rounds
    (or blends) away to zero or below. The caller must treat a ``None`` return
    as "this rule does not close the position on this bar" and continue the
    walk, never let it reach :class:`ReferenceTrade` construction.

    Preconditions: none (``raw_closing_price`` may be any float). Called only
    for a STOP or ``signal_exit`` close — a take-profit-family close instead
    rounds its own already-committed
    :class:`~.reference_exits._TakeProfitFireResult` directly, matching
    :func:`~.reference_exits.resolve_take_profit_family_exit`'s existing,
    already-tested behavior. A take-profit candidate's price is NOT
    analytically bounded away from zero the way this function's own STOP/
    signal callers effectively are in practice — an unbounded ``pct`` can
    still put a short's target at or below zero — so that family is guarded
    separately, at the point its candidate is peeked in
    :func:`_process_exit_bar` (before it can even enter that bar's
    cross-book priority comparison), rather than here.
    Postconditions: returns ``None`` when ``raw_closing_price`` is not a finite
    positive number, or when the correctly rounded/blended price would be
    ``<= 0``. Otherwise returns the price a :class:`ReferenceTrade` should
    record: when ``pos.tp_book`` is ``None``,
    :func:`~.reference_exits.round_reference_price` of ``raw_closing_price``
    directly; when ``pos.tp_book`` exists (whether or not it ever committed a
    rung), the quantity-weighted blend of its prior fills plus this closing
    price via :meth:`~.reference_exits.RestingTakeProfitFamily.blend_terminal`,
    rounded using THIS closing price's own bucket — mirrors
    ``_TakeProfitFireResult``'s documented "bucket from terminal, round the
    blend once" discipline. Does not mutate ``pos.tp_book``.
    """
    if not (raw_closing_price > 0 and math.isfinite(raw_closing_price)):
        return None
    if pos.tp_book is None:
        price = round_reference_price(raw_closing_price)
    else:
        raw_blended, terminal_price = pos.tp_book.blend_terminal(raw_closing_price)
        price = round(raw_blended, decimals_for(terminal_price))
    return price if price > 0 else None


def _peek_signal_exit(
    working_rules: Sequence[ExitRule],
    entry: ReferenceEntryFill,
    view: HistoryView,
    trigger_bar: int,
    bar: "Bar",
) -> Optional[int]:
    """The lowest-index ``SignalExitRule`` firing at ``trigger_bar``, or ``None``.

    Mirrors :func:`~.reference_exits.resolve_signal_exit`'s own per-bar body
    exactly — same frozen ``PositionState`` (the PRE-slippage ``entry_price``
    for both the anchor and the (unread) watermarks), same
    :class:`~.reference_exits.PrefixHistoryView` truncation so a signal
    predicate's "now" means ``trigger_bar``, never the dataset's final bar —
    so the combined driver's signal-exit trigger decision never drifts from
    the already-tested standalone replay.

    Preconditions: ``working_rules`` is the WORKING exit-rule list;
    ``0 <= trigger_bar < view.length()``; ``bar`` is
    ``symbol_bars[trigger_bar]``.
    Postconditions: returns the winning rule's ``exit_rule_index``, or
    ``None`` when no ``SignalExitRule`` fires at ``trigger_bar`` — including
    when ``working_rules`` carries no ``SignalExitRule`` at all, checked
    before any evaluator call.
    Invariants: no side effects; deterministic in its inputs.
    """
    if not signal_exit_rules(working_rules):
        return None
    position = PositionState(
        symbol=entry.symbol,
        side=entry.side,
        qty=1.0,
        entry_price=entry.entry_price,
        high_since_entry=entry.entry_price,
        low_since_entry=entry.entry_price,
    )
    intents = evaluate_exit_rules_for_position(
        working_rules,
        entry.symbol,
        position,
        bar_snapshot(bar),
        view=PrefixHistoryView(view, trigger_bar),
        first_only=False,
    )
    winner = next((intent for intent in intents if intent.rule_kind == "signal_exit"), None)
    return winner.rule_index if winner is not None else None


def _finish_trade(
    pos: _OpenPosition,
    exit_bar: int,
    bar: "Bar",
    exit_price: float,
    exit_rule_kind: ExitRuleKind,
    exit_rule_index: int,
    level_index: Optional[int],
) -> _RawTrade:
    """Build the closed-position record for ``pos``, minus ``trade_num``.

    Preconditions: ``exit_price`` already passed the positive-finite check
    (:func:`_finalize_exit_price`, or the take-profit family's own committed
    result); ``bar`` is ``symbol_bars[exit_bar]``.
    Postconditions: returns a ``_RawTrade`` combining ``pos.entry`` with the
    given exit fields; ``qty`` is the nominal ``1.0`` (see this module's own
    docstring on quantity scope).
    """
    return _RawTrade(
        exit_sort_key=bar.timestamp,
        symbol=pos.entry.symbol,
        side=pos.entry.side,
        entry_bar=pos.entry.entry_bar,
        entry_rule_index=pos.entry.entry_rule_index,
        exit_bar=exit_bar,
        entry_date=pos.entry.entry_date,
        exit_date=bar.timestamp[:10],
        entry_price=pos.entry.entry_price,
        exit_price=exit_price,
        qty=1.0,
        exit_rule_kind=exit_rule_kind,
        exit_rule_index=exit_rule_index,
        level_index=level_index,
    )


def _process_exit_bar(
    pos: _OpenPosition,
    i: int,
    bar: "Bar",
    view: HistoryView,
    working_rules: Sequence[ExitRule],
) -> Optional[_RawTrade]:
    """Run one bar's full exit-side phase order for an open position.

    The per-bar core of :func:`_simulate_symbol`'s walk — see this module's
    own docstring for the full phase-order argument (resting candidates, a
    signal exit due this bar, then a fresh signal-exit trigger check).

    Preconditions: ``pos`` is open (not yet closed); ``i`` is the bar index
    currently being processed, strictly increasing across calls for the same
    ``pos``; ``bar is symbol_bars[i]``.
    Postconditions: returns the closing ``_RawTrade`` the FIRST time some rule
    fully closes ``pos`` this bar, or ``None`` when ``pos`` remains open after
    this bar (whether nothing fired, or only a partial rung did). Mutates
    ``pos`` in place: the stop book's watermark, the take-profit family's
    fills/cursors, and ``pos.pending_signal`` all advance as this bar's events
    require.
    """
    resting_eligible = i >= pos.entry.entry_bar + 1
    if resting_eligible:
        stop_candidate = pos.stop_book.peek(bar) if pos.stop_book is not None else None
        tp_candidate = pos.tp_book.peek(bar) if pos.tp_book is not None else None
        if tp_candidate is not None and not (
            tp_candidate.price > 0 and math.isfinite(tp_candidate.price)
        ):
            # A degenerate candidate (non-finite, or <= 0 — reachable when a
            # valid pct >= 1 target on the short side lands at or below zero
            # and a garbage nonpositive bar low reaches it; see
            # TakeProfitRule/TakeProfitLevel.pct's unbounded Field(gt=0)) is
            # discarded HERE, before it can enter the stop_wins priority
            # comparison below — not merely before commit(). Filtering it
            # only inside the tp branch (checked after stop_wins was already
            # decided) let an invalid LOWER-index candidate still win that
            # comparison by rule-index alone, masking a legitimate
            # higher-index stop reachable on the very same bar and leaving
            # the position open with no trade emitted. Discarding it here
            # makes it invisible to this bar's resting phase entirely, so a
            # valid stop candidate is free to win on its own merits, and
            # commit() still never sees it — the book's
            # fills/cursor/remaining_qty stay untouched and a later bar or
            # another rule kind may still close the position, exactly as if
            # the rule had not triggered this bar (the design doc's uniform
            # nonpositive-exit-reference rule). Letting it reach
            # ReferenceTrade construction instead would abort the whole
            # simulate() run over one bad bar, which that rule forbids.
            tp_candidate = None
        # Symmetric with the tp_candidate filter above: a stop candidate's RAW
        # price can be positive and finite (passing RestingStopLoss.peek's own
        # guard) yet still round or blend away to <= 0 once _finalize_exit_price
        # applies production's own rounding bucket and any prior take-profit
        # rungs' blend — e.g. an entry price small enough that a deep stop's
        # level survives peek's raw check but rounds to zero. Finalizing it
        # HERE, before stop_wins, means an unusable stop is discarded before it
        # can win that priority comparison by rule-index alone, exactly the
        # same masking risk the tp_candidate filter above addresses for the
        # reverse pairing — a lower-index stop that turns out unusable must not
        # block a legitimate higher-index take-profit reachable on the same
        # bar. The finalized price is reused directly below rather than
        # recomputed, since _finalize_exit_price has no side effects to redo.
        stop_price: Optional[float] = None
        if stop_candidate is not None:
            stop_price = _finalize_exit_price(pos, stop_candidate[1])
            if stop_price is None:
                stop_candidate = None
        if pos.stop_book is not None:
            # Ratcheted exactly once per bar regardless of which book (if
            # either) wins — mirrors RestingStopLoss.step's own "extended
            # either way" postcondition.
            pos.stop_book.advance(bar)

        stop_wins = stop_candidate is not None and (
            tp_candidate is None or stop_candidate[0] < tp_candidate.exit_rule_index
        )
        if stop_wins:
            idx, _ = stop_candidate
            return _finish_trade(pos, i, bar, stop_price, "stop_loss", idx, None)
        elif tp_candidate is not None:
            fired = pos.tp_book.commit(tp_candidate)
            if fired is not None:
                price = round(fired.raw_price, decimals_for(fired.terminal_price))
                return _finish_trade(
                    pos,
                    i,
                    bar,
                    price,
                    fired.exit_rule_kind,
                    fired.exit_rule_index,
                    fired.level_index,
                )
            # Rung fired but left the position open — fall through to check
            # a queued/fresh signal exit on this same bar.

    if pos.pending_signal is not None and pos.pending_signal[1] == i:
        rule_idx, _ = pos.pending_signal
        # Consumed regardless of outcome: a degenerate fill-bar open drops
        # THIS firing rather than retrying it on a later bar, mirroring
        # resolve_signal_exit's own "continue" (which moves on to a FRESH
        # trigger check, never retries the same trigger) — phase 3 below
        # provides that fresh check on this very bar.
        pos.pending_signal = None
        price = _finalize_exit_price(pos, bar.open)
        if price is not None:
            return _finish_trade(pos, i, bar, price, "signal_exit", rule_idx, None)
        elif pos.stop_book is not None:
            # The queued close this firing represents never actually
            # happened — a nonpositive/non-finite/zero-rounding fill-bar
            # open, per the uniform nonpositive-exit-reference rule, is
            # treated exactly as if the trigger had not been met. Retiring
            # any limit-style stop when the signal was QUEUED (phase 3 below)
            # was solely a consequence of that firing having been chosen;
            # since it turned out not to have happened after all, the
            # retirement must not outlive it either, or a stop that would
            # otherwise still be live loses a legitimate close on every later
            # bar for no reason tied to any real event. See
            # RestingStopLoss.restore_limit_style_rules's own docstring for
            # why this bar's own resting phase (already evaluated above,
            # before this outcome was known) is not itself replayed.
            pos.stop_book.restore_limit_style_rules()

    if i >= pos.entry.entry_bar:
        new_idx = _peek_signal_exit(working_rules, pos.entry, view, i, bar)
        if new_idx is not None:
            pos.pending_signal = (new_idx, i + 1)
            if pos.stop_book is not None:
                # The moment a competing whole-position close is CHOSEN, a
                # resting limit-style stop is retired outright — see
                # RestingStopLoss.retire_limit_style_rules's own docstring.
                pos.stop_book.retire_limit_style_rules()

    return None


def _simulate_symbol(
    spec: StrategySpec,
    working_rules: Sequence[ExitRule],
    symbol: str,
    symbol_bars: Sequence["Bar"],
    entry_slippage_bps: float,
) -> List[_RawTrade]:
    """Walk one symbol's full bar series, opening and closing positions in turn.

    Preconditions: ``symbol_bars`` is non-empty and strictly increasing by
    timestamp (already validated by :func:`simulate`); ``working_rules`` is
    the WORKING exit-rule list; ``entry_slippage_bps`` is finite and in
    ``[0, 10_000)``.
    Postconditions: returns every fully closed position's ``_RawTrade``, in
    the order this symbol's positions close (non-decreasing ``entry_bar``,
    per the design doc's own "one symbol never holds two overlapping
    positions" argument). A position still open when ``symbol_bars`` ends —
    including a re-entry after an earlier close — produces no trade for that
    open remainder. When ``spec.target_symbols`` is non-empty and ``symbol``
    is not in it, returns an empty list without evaluating any bar.
    Invariants: no side effects on ``spec``/``symbol_bars``; deterministic in
    its inputs.
    """
    if spec.target_symbols and symbol not in spec.target_symbols:
        return []
    n = len(symbol_bars)
    view = PandasHistoryView(bars_to_frame(symbol_bars), {})
    out: List[_RawTrade] = []
    pos: Optional[_OpenPosition] = None
    for i in range(n):
        if pos is not None:
            raw_trade = _process_exit_bar(pos, i, symbol_bars[i], view, working_rules)
            if raw_trade is not None:
                out.append(raw_trade)
                pos = None
        if pos is None:
            # Reads the POST-exit state above: a position closed earlier in
            # THIS same iteration does not suppress a fresh entry trigger on
            # this same bar (design doc's third "Per-bar evaluation order"
            # rule).
            match = evaluate_entry_rules(spec.entry_rules, view, i)
            if match is not None:
                rule, rule_idx = match
                fill = fill_entry_at(symbol, symbol_bars, i, rule.side, rule_idx)
                if fill is not None:
                    pos = _open_position(fill, working_rules, entry_slippage_bps)
    return out


def simulate(
    spec: StrategySpec,
    bars: "Mapping[str, Sequence[Bar]]",
    *,
    entry_slippage_bps: float = 0.0,
) -> List[ReferenceTrade]:
    """Pure re-simulation of ``spec.entry_rules``/``spec.exit_rules`` over ``bars``.

    The design doc's ``simulate()`` entry point (§2), minus the
    ``starting_equity`` parameter the sizing layer would need — see this
    module's own docstring for why it is omitted for now.

    Preconditions:
        - ``spec`` is a validated ``StrategySpec`` with
          ``requires_custom_code`` False (enforced by
          :func:`~.reference_exits.working_exit_rules`, called first).
        - ``spec``'s working exit rules (``spec.exit_rules`` plus any
          engine-injected short safety stop) contain no ``OcoBracketRule`` —
          bracket modelling is out of scope for this module (see its own
          docstring); ``simulate`` raises ``ValueError`` rather than
          silently ignoring the bracket or modelling only some of its legs.
        - ``entry_slippage_bps`` is finite and ``0 <= entry_slippage_bps <
          10_000``.
        - When ``spec.target_symbols`` is non-empty, every symbol it names is
          a key in ``bars`` — an empty ``bars`` mapping does not vacuously
          satisfy this. Without this check a target symbol simply absent from
          ``bars`` silently produces no trades for it, indistinguishable from
          a strategy that legitimately never triggered; ``simulate`` raises
          ``ValueError`` instead.
        - For every symbol key in ``bars``: the sequence is non-empty,
          strictly increasing by ``timestamp``, and every ``Bar`` in it has
          ``bar.symbol`` equal to that mapping key. Validated uniformly for
          every key present, regardless of ``spec.target_symbols`` — this
          module does not distinguish an "auxiliary" symbol's validation
          requirements from a traded one's.

    Returns:
        One ``ReferenceTrade`` per fully closed position, in global emission
        order: ordered by ``(exit bar timestamp, symbol)`` across every
        symbol in ``bars``, with ``trade_num`` assigned 1-based in that order.
        A position still open when its symbol's bars run out — including one
        holding only a partially-reduced ``scaled_take_profit`` remainder —
        produces no row, mirroring production's own treatment of an
        unclosed position.

    Invariants:
        - No side effects: does not mutate ``spec`` or ``bars``, performs no
          I/O.
        - Deterministic: identical inputs always produce an identical output
          list.
        - Imports no module reaching ``trading_service/service.py`` or the
          four forbidden ``trading_service/engine/`` modules (see this
          module's own docstring).
    """
    working_rules = working_exit_rules(spec)
    for idx, rule in enumerate(working_rules):
        if isinstance(rule, OcoBracketRule):
            raise ValueError(
                "reference-ledger simulate() does not model oco_bracket rules: "
                f"spec's working exit rules contain one at index {idx}"
            )
    if not (math.isfinite(entry_slippage_bps) and 0 <= entry_slippage_bps < 10_000):
        raise ValueError(
            f"entry_slippage_bps must be finite and in [0, 10_000), got {entry_slippage_bps!r}"
        )
    if spec.target_symbols:
        missing = [s for s in spec.target_symbols if s not in bars]
        if missing:
            raise ValueError(
                f"bars is missing required symbol(s) {missing!r} referenced by spec.target_symbols"
            )
    for symbol, symbol_bars in bars.items():
        if len(symbol_bars) == 0:
            raise ValueError(f"bars[{symbol!r}] must be non-empty")
        prev_timestamp: Optional[str] = None
        for bar in symbol_bars:
            if bar.symbol != symbol:
                raise ValueError(
                    f"bars[{symbol!r}] contains a Bar whose symbol is {bar.symbol!r}, "
                    "not the mapping key"
                )
            if prev_timestamp is not None and not bar.timestamp > prev_timestamp:
                raise ValueError(
                    f"bars[{symbol!r}] is not strictly increasing by timestamp at {bar.timestamp!r}"
                )
            prev_timestamp = bar.timestamp

    raw_trades: List[_RawTrade] = []
    for symbol, symbol_bars in bars.items():
        raw_trades.extend(
            _simulate_symbol(spec, working_rules, symbol, symbol_bars, entry_slippage_bps)
        )
    raw_trades.sort(key=lambda t: (t.exit_sort_key, t.symbol))

    return [
        ReferenceTrade(
            trade_num=n,
            symbol=t.symbol,
            side=t.side,
            entry_bar=t.entry_bar,
            entry_rule_index=t.entry_rule_index,
            exit_bar=t.exit_bar,
            entry_date=t.entry_date,
            exit_date=t.exit_date,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            qty=t.qty,
            exit_rule_kind=t.exit_rule_kind,
            exit_rule_index=t.exit_rule_index,
            level_index=t.level_index,
        )
        for n, t in enumerate(raw_trades, start=1)
    ]
