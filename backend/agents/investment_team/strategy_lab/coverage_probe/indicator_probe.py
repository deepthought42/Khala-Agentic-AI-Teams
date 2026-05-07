"""Indicator-coverage probe for Strategy Lab strategies (#448).

Walks the strategy's ``on_bar`` (or equivalent entry path) for ``if``
predicates whose subconditions reference a recognised OHLCV column or
one of the indicator helpers in
:mod:`investment_team.strategy_lab.executor.indicators`, evaluates each
subcondition over the fetched market data, and aggregates per-bar hit
rates plus a conjunction hit-rate into a partial :class:`CoverageReport`.

Pure: no I/O, no LLM, no subprocess. Bounded: a single ``ast.parse`` per
strategy and per-symbol vectorised pandas evaluation only when at least
one recognised subcondition exists. The probe never raises — malformed
input degrades to ``UNKNOWN_LOW_COVERAGE`` with an explanatory summary.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import pandas as pd

from investment_team.models import (
    CoverageCategory,
    CoverageReport,
    LikelyBlocker,
    SubconditionCoverage,
)
from investment_team.strategy_lab.executor import indicators as _ind

logger = logging.getLogger(__name__)

_OHLCV_COLUMNS = frozenset({"open", "high", "low", "close", "volume"})
_MAX_SUBCONDITIONS = 16
_MAX_LIKELY_BLOCKERS = 6
_MAX_LABEL_LEN = 80

_CMP_OPS: Dict[type, Callable[[pd.Series, pd.Series], pd.Series]] = {
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}

# Single-series indicator helpers (take a Series + optional period).
_SERIES_INDICATORS: Dict[str, Callable[..., pd.Series]] = {
    "sma": _ind.sma,
    "ema": _ind.ema,
    "rsi": _ind.rsi,
}

# Indicators that take (high, low, close[, ...]) and return a Series.
_HLC_INDICATORS: Dict[str, Callable[..., pd.Series]] = {
    "atr": _ind.atr,
    "adx": _ind.adx,
}

# Indicators that take (high, low, close, volume) and return a Series.
_OHLCV_INDICATORS: Dict[str, Callable[..., pd.Series]] = {
    "vwap": _ind.vwap,
}

# Tuple-returning helpers (one Series per element). We only recognise
# them inside a Subscript with a constant integer slice — bare calls are
# ambiguous because the user hasn't picked which leg to compare.
# Each entry: (signature_kind, helper, max_idx).
#   signature_kind: "series" → helper(series, *period_args)
#                   "hlc"    → helper(high, low, close, *period_args)
_TUPLE_INDICATORS: Dict[str, tuple] = {
    "macd": ("series", _ind.macd, 3),  # (macd_line, signal_line, histogram)
    "bollinger_bands": ("series", _ind.bollinger_bands, 3),  # (upper, middle, lower)
    "stochastic": ("hlc", _ind.stochastic, 2),  # (%K, %D)
}


@dataclass(frozen=True)
class _Operand:
    """Compiled half of a comparison.

    ``data_dependent`` is True iff the operand reads the DataFrame (column
    or indicator). Subconditions whose *both* operands are pure literals
    are rejected — they are constant-truth and carry no coverage signal.
    """

    fn: Callable[[pd.DataFrame], pd.Series]
    data_dependent: bool


@dataclass(frozen=True)
class _Subcond:
    label: str
    evaluate: Callable[[pd.DataFrame], pd.Series]


def run_indicator_probe(
    *,
    strategy_code: str,
    market_data: Dict[str, pd.DataFrame],
    warmup_bars_required: int = 0,
) -> CoverageReport:
    """Return a partial :class:`CoverageReport` from indicator-coverage analysis.

    Parameters
    ----------
    strategy_code:
        Source of the generated strategy. The probe scans the
        ``on_bar`` (or equivalent) method body for ``if`` predicates.
    market_data:
        Dict of ``symbol -> DataFrame`` with at least the standard
        OHLCV columns. Index is treated opaquely; ``last_true_bar``
        is rendered with ``str(...)``.
    warmup_bars_required:
        When the total recognised bars is below this value the probe
        short-circuits with :data:`CoverageCategory.INSUFFICIENT_BARS`.

    The probe is deterministic and never raises.
    """
    symbols_checked = sum(1 for df in market_data.values() if isinstance(df, pd.DataFrame))
    bars_checked = sum(len(df) for df in market_data.values() if isinstance(df, pd.DataFrame))
    base_kwargs = {
        "symbols_checked": symbols_checked,
        "bars_checked": bars_checked,
        "warmup_bars_required": int(max(0, warmup_bars_required)),
    }

    if warmup_bars_required > 0 and bars_checked < warmup_bars_required:
        return CoverageReport(
            coverage_category=CoverageCategory.INSUFFICIENT_BARS,
            summary=(
                f"insufficient bars: {bars_checked} available, {warmup_bars_required} required"
            ),
            likely_blockers=[
                LikelyBlocker(
                    reason="insufficient_bars",
                    evidence=f"bars_checked={bars_checked} < warmup={warmup_bars_required}",
                )
            ],
            **base_kwargs,
        )

    try:
        subconds = _extract_subconditions(strategy_code)
    except Exception as exc:  # noqa: BLE001 — never raise from probe
        logger.debug("indicator_probe AST extraction failed: %s", exc)
        return CoverageReport(
            coverage_category=CoverageCategory.UNKNOWN_LOW_COVERAGE,
            summary="strategy_code did not parse for indicator probe",
            **base_kwargs,
        )

    if not subconds:
        return CoverageReport(
            coverage_category=CoverageCategory.UNKNOWN_LOW_COVERAGE,
            summary="no recognized indicator subconditions found",
            **base_kwargs,
        )

    try:
        return _aggregate(subconds, market_data, base_kwargs)
    except Exception as exc:  # noqa: BLE001 — never raise from probe
        logger.debug("indicator_probe evaluation failed: %s", exc)
        return CoverageReport(
            coverage_category=CoverageCategory.UNKNOWN_LOW_COVERAGE,
            summary="indicator probe evaluation failed",
            **base_kwargs,
        )


def _aggregate(
    groups: List[List[_Subcond]],
    market_data: Dict[str, pd.DataFrame],
    base_kwargs: Dict[str, object],
) -> CoverageReport:
    flat_subconds: List[_Subcond] = [s for g in groups for s in g]
    if not flat_subconds:
        return CoverageReport(
            coverage_category=CoverageCategory.UNKNOWN_LOW_COVERAGE,
            summary="no recognized indicator subconditions found",
            **base_kwargs,
        )

    sub_hit_counts: List[int] = [0] * len(flat_subconds)
    sub_last_true: List[Optional[str]] = [None] * len(flat_subconds)
    group_conjunction_hits: List[int] = [0] * len(groups)
    group_evaluated: List[bool] = [False] * len(groups)
    total_eval_bars = 0

    for symbol, df in market_data.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        global_idx = 0
        symbol_contributed = False
        for group_idx, group in enumerate(groups):
            group_masks: List[pd.Series] = []
            for sub in group:
                try:
                    series = sub.evaluate(df)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("subcondition %r failed on %s: %s", sub.label, symbol, exc)
                    series = pd.Series(False, index=df.index, dtype=bool)
                mask = pd.Series(series, index=df.index).fillna(False).astype(bool)
                hits = int(mask.sum())
                sub_hit_counts[global_idx] += hits
                if hits:
                    last_bar = str(mask[mask].index[-1])
                    if sub_last_true[global_idx] is None or last_bar > sub_last_true[global_idx]:
                        sub_last_true[global_idx] = last_bar
                group_masks.append(mask)
                global_idx += 1
            if group_masks:
                conjunction_mask = group_masks[0]
                for m in group_masks[1:]:
                    conjunction_mask = conjunction_mask & m
                group_conjunction_hits[group_idx] += int(conjunction_mask.sum())
                group_evaluated[group_idx] = True
                symbol_contributed = True
        if symbol_contributed:
            total_eval_bars += len(df)

    if total_eval_bars == 0:
        return CoverageReport(
            coverage_category=CoverageCategory.UNKNOWN_LOW_COVERAGE,
            summary="no bars evaluated",
            subconditions=[],
            **base_kwargs,
        )

    # Deduplicate the SubconditionCoverage list by label so a subcond
    # repeated across multiple ``if`` predicates is reported once.
    subcoverages: List[SubconditionCoverage] = []
    seen_labels: set[str] = set()
    for sub, hits, last in zip(flat_subconds, sub_hit_counts, sub_last_true):
        if sub.label in seen_labels:
            continue
        seen_labels.add(sub.label)
        rate = hits / total_eval_bars
        subcoverages.append(
            SubconditionCoverage(
                label=sub.label,
                hit_count=hits,
                hit_rate=min(max(rate, 0.0), 1.0),
                last_true_bar=last,
            )
        )

    zero_hits = [sc for sc in subcoverages if sc.hit_count == 0]
    blockers: List[LikelyBlocker] = []
    if zero_hits:
        category = CoverageCategory.INDICATOR_FILTER_TOO_RESTRICTIVE
        summary = f"{len(zero_hits)} of {len(subcoverages)} indicator subconditions never fired"
        for sc in zero_hits:
            blockers.append(
                LikelyBlocker(
                    reason="indicator_filter_zero_hits",
                    evidence=sc.label,
                    hit_rate=0.0,
                )
            )
        return CoverageReport(
            coverage_category=category,
            summary=summary,
            subconditions=subcoverages,
            likely_blockers=blockers[:_MAX_LIKELY_BLOCKERS],
            **base_kwargs,
        )

    # Find any single ``if`` predicate whose legs all fire individually
    # but whose bar-wise AND is empty. We only flag CONJUNCTION_NEVER_TRUE
    # for a real per-predicate contradiction — never across unrelated
    # ``if`` branches.
    empty_conj_group: Optional[List[_Subcond]] = None
    base = 0
    for group_idx, group in enumerate(groups):
        legs = len(group)
        if (
            legs >= 2
            and group_evaluated[group_idx]
            and group_conjunction_hits[group_idx] == 0
            and all(sub_hit_counts[base + k] > 0 for k in range(legs))
        ):
            empty_conj_group = group
            break
        base += legs

    if empty_conj_group is not None:
        return CoverageReport(
            coverage_category=CoverageCategory.CONJUNCTION_NEVER_TRUE,
            summary="individual subconditions fire but their conjunction is never true",
            subconditions=subcoverages,
            likely_blockers=[
                LikelyBlocker(
                    reason="conjunction_never_true",
                    evidence=" AND ".join(s.label for s in empty_conj_group),
                    hit_rate=0.0,
                )
            ][:_MAX_LIKELY_BLOCKERS],
            **base_kwargs,
        )

    return CoverageReport(
        coverage_category=CoverageCategory.COVERAGE_OK,
        summary="indicator subconditions fired at least once",
        subconditions=subcoverages,
        likely_blockers=[],
        **base_kwargs,
    )


# ---------------------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------------------


_BLOCK_FIELDS = ("body", "orelse", "finalbody")


def _extract_subconditions(strategy_code: str) -> List[List[_Subcond]]:
    """Return one group of subconditions per ``if`` predicate.

    Subconditions are grouped by their parent ``if`` so the conjunction
    hit-rate check stays scoped to a single predicate. Two **sibling**
    branches like ``if close > 100: enter`` and ``if close < 50: exit``
    are returned as separate groups and are never ANDed together.

    A **nested** ``if`` inherits the subconditions of every enclosing
    ``if`` on its positive control-flow path: ``if close > 100: if close
    < 50: pass`` produces a single group containing both legs, so the
    coverage check sees the bar-wise AND ``close > 100 AND close < 50``
    (which is impossible) rather than two unrelated branches that would
    each fire on different bars.

    The positive branch (``body``) propagates the ancestor predicate;
    ``orelse`` does not, since negating an arbitrary indicator subcond
    is generally ambiguous and we'd rather under-flag than over-flag.
    """
    if not strategy_code:
        return []
    tree = ast.parse(strategy_code)
    name_periods = _collect_name_periods(tree)
    on_bar = _find_on_bar(tree)
    if on_bar is None:
        return []

    # Pre-pass: bind any local Name to its computed indicator. Strategies
    # following the standard template (see prompts/ideation_system.md)
    # write ``sma_var = sma(close, 200)`` then ``if bar.close > sma_var``
    # — the comparison's RHS is a Name, not a Call, so without this pass
    # the subcondition is dropped.
    name_evaluators = _collect_name_evaluators(on_bar, name_periods)

    groups: List[List[_Subcond]] = []
    state = {"total": 0}

    def _budgeted_extend(group: List[_Subcond], extras: List[_Subcond]) -> bool:
        """Append extras into group within the global subcond budget.

        Returns False when the global cap is hit (caller should stop).
        """
        for sub in extras:
            if state["total"] >= _MAX_SUBCONDITIONS:
                return False
            group.append(sub)
            state["total"] += 1
        return True

    def _visit(stmts: List[ast.stmt], ancestors: List[_Subcond]) -> bool:
        for stmt in stmts:
            if isinstance(stmt, ast.If):
                own_subs: List[_Subcond] = []
                for cmp_node in _flatten_test(stmt.test):
                    sub = _build_subcond(cmp_node, name_periods, name_evaluators)
                    if sub is not None:
                        own_subs.append(sub)
                # Build this if's group: ancestors + this predicate.
                # Ancestors are already counted in earlier groups, but
                # for THIS group they need fresh budget too (so the cap
                # bounds total work, not unique subconds).
                group: List[_Subcond] = []
                if not _budgeted_extend(group, ancestors):
                    if group:
                        groups.append(group)
                    return False
                if not _budgeted_extend(group, own_subs):
                    if group:
                        groups.append(group)
                    return False
                if group:
                    groups.append(group)
                # Positive branch inherits ancestors + own_subs.
                if not _visit(stmt.body, ancestors + own_subs):
                    return False
                # Else branch only inherits ancestors (we don't model
                # the negation of own_subs).
                if not _visit(stmt.orelse, ancestors):
                    return False
            else:
                # Descend into compound statements (For, While, With,
                # Try, FunctionDef body) but pass through ancestors so
                # ``for x in ...: if close > 100: ...`` still inherits
                # nothing, which is correct.
                for field in _BLOCK_FIELDS:
                    inner = getattr(stmt, field, None)
                    if isinstance(inner, list) and inner and isinstance(inner[0], ast.stmt):
                        if not _visit(inner, ancestors):
                            return False
                # ast.Try has handlers; each handler.body is a stmt list.
                handlers = getattr(stmt, "handlers", None)
                if isinstance(handlers, list):
                    for h in handlers:
                        h_body = getattr(h, "body", None)
                        if isinstance(h_body, list) and h_body:
                            if not _visit(h_body, ancestors):
                                return False
        return True

    body = getattr(on_bar, "body", None)
    if isinstance(body, list):
        _visit(body, [])
    return groups


def _find_on_bar(tree: ast.AST) -> Optional[ast.AST]:
    """Prefer ``on_bar`` — the real Strategy contract — when present.

    Only fall back to ``entry`` / ``signal`` / ``generate_signal`` if no
    ``on_bar`` is found. Otherwise a module-level helper named ``signal``
    placed before the strategy class would shadow the real entry path.
    """
    fallback: Optional[ast.AST] = None
    fallback_names = ("entry", "signal", "generate_signal")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name.lower()
        if name == "on_bar":
            return node
        if fallback is None and name in fallback_names:
            fallback = node
    return fallback


def _flatten_test(test: ast.expr) -> List[ast.Compare]:
    """Flatten ``a and b and (c < d)`` into individual ``Compare`` nodes."""
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        out: List[ast.Compare] = []
        for value in test.values:
            out.extend(_flatten_test(value))
        return out
    if isinstance(test, ast.Compare):
        return [test]
    return []


def _collect_name_periods(tree: ast.AST) -> Dict[str, int]:
    """Bind module-level ``NAME = <int>`` for later ``Name`` resolution."""
    bindings: Dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, int)
                    and not isinstance(node.value.value, bool)
                    and node.value.value > 0
                ):
                    bindings[target.id] = node.value.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
            and not isinstance(node.value.value, bool)
            and node.value.value > 0
        ):
            bindings[node.target.id] = node.value.value
    return bindings


def _build_subcond(
    node: ast.Compare,
    name_periods: Dict[str, int],
    name_evaluators: Optional[Dict[str, Callable[[pd.DataFrame], pd.Series]]] = None,
) -> Optional[_Subcond]:
    # Only support simple a <op> b shape — chained comparisons are rare in
    # generated strategies and ambiguous for hit-rate semantics.
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    op = type(node.ops[0])
    op_fn = _CMP_OPS.get(op)
    if op_fn is None:
        return None

    left = _build_operand(node.left, name_periods, name_evaluators)
    right = _build_operand(node.comparators[0], name_periods, name_evaluators)
    if left is None or right is None:
        return None
    if not (left.data_dependent or right.data_dependent):
        return None

    label = _format_label(node)
    l_fn = left.fn
    r_fn = right.fn

    def _eval(df: pd.DataFrame) -> pd.Series:
        return op_fn(l_fn(df), r_fn(df))

    return _Subcond(label=label, evaluate=_eval)


def _format_label(node: ast.Compare) -> str:
    try:
        text = ast.unparse(node)
    except Exception:  # noqa: BLE001
        text = "<expr>"
    text = text.strip()
    if len(text) > _MAX_LABEL_LEN:
        text = text[: _MAX_LABEL_LEN - 1] + "…"
    return text


def _build_operand(
    node: ast.expr,
    name_periods: Dict[str, int],
    name_evaluators: Optional[Dict[str, Callable[[pd.DataFrame], pd.Series]]] = None,
) -> Optional[_Operand]:
    """Compile an AST sub-expression into a ``df -> Series`` callable.

    Returns ``None`` for expressions whose evaluation we can't faithfully
    model (e.g. function calls into user code, attribute chains we don't
    recognise). Such subconditions are silently dropped.
    """
    column = _column_from(node)
    if column is not None:

        def _col(df: pd.DataFrame, c: str = column) -> pd.Series:
            if c in df.columns:
                return df[c].astype(float)
            return pd.Series(float("nan"), index=df.index)

        return _Operand(fn=_col, data_dependent=True)

    # Resolve a Name to a previously-bound indicator-call evaluator
    # (e.g. ``sma_var = sma(close, 200)`` then ``if x > sma_var``).
    # This must be checked BEFORE _numeric_literal so a Name that refers
    # to a computed indicator isn't misinterpreted as a numeric literal.
    if isinstance(node, ast.Name) and name_evaluators is not None:
        evaluator = name_evaluators.get(node.id)
        if evaluator is not None:
            return _Operand(fn=evaluator, data_dependent=True)

    literal = _numeric_literal(node, name_periods)
    if literal is not None:
        return _Operand(
            fn=lambda df, v=literal: pd.Series(v, index=df.index, dtype=float),
            data_dependent=False,
        )

    indicator_fn = _indicator_call(node, name_periods)
    if indicator_fn is not None:
        return _Operand(fn=indicator_fn, data_dependent=True)

    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Add, ast.Sub)):
        left = _build_operand(node.left, name_periods, name_evaluators)
        right = _build_operand(node.right, name_periods, name_evaluators)
        if left is not None and right is not None:
            l_fn, r_fn = left.fn, right.fn
            if isinstance(node.op, ast.Mult):

                def combined(df: pd.DataFrame) -> pd.Series:
                    return l_fn(df) * r_fn(df)
            elif isinstance(node.op, ast.Add):

                def combined(df: pd.DataFrame) -> pd.Series:
                    return l_fn(df) + r_fn(df)
            else:

                def combined(df: pd.DataFrame) -> pd.Series:
                    return l_fn(df) - r_fn(df)

            return _Operand(
                fn=combined,
                data_dependent=left.data_dependent or right.data_dependent,
            )

    return None


def _column_from(node: ast.expr) -> Optional[str]:
    """Resolve a node to an OHLCV column name, if possible."""
    if isinstance(node, ast.Name) and node.id in _OHLCV_COLUMNS:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr in _OHLCV_COLUMNS:
        return node.attr
    if isinstance(node, ast.Subscript):
        slc = node.slice
        if isinstance(slc, ast.Constant) and isinstance(slc.value, str):
            if slc.value in _OHLCV_COLUMNS:
                return slc.value
    return None


def _numeric_literal(node: ast.expr, name_periods: Dict[str, int]) -> Optional[float]:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _numeric_literal(node.operand, name_periods)
        if inner is not None:
            return -inner
    if isinstance(node, ast.Name):
        period = name_periods.get(node.id)
        if period is not None:
            return float(period)
    return None


def _indicator_call(
    node: ast.expr, name_periods: Dict[str, int]
) -> Optional[Callable[[pd.DataFrame], pd.Series]]:
    # Tuple-returning helpers are only recognised inside a Subscript with
    # a constant integer index — without one we can't tell which leg the
    # user meant to compare against.
    if isinstance(node, ast.Subscript):
        return _tuple_indicator_subscript(node, name_periods)

    if not isinstance(node, ast.Call):
        return None
    func_name = _func_name(node.func)
    if func_name is None:
        return None

    if func_name in _SERIES_INDICATORS:
        helper = _SERIES_INDICATORS[func_name]
        column = _series_arg_column(node)
        # Series helpers: rsi(series, period), sma(series, period), ...
        period = _resolve_period_arg(node, name_periods, positional_index=1)

        def _eval_series(df: pd.DataFrame) -> pd.Series:
            if column not in df.columns:
                return pd.Series(float("nan"), index=df.index)
            if period is not None:
                return helper(df[column].astype(float), int(period))
            return helper(df[column].astype(float))

        return _eval_series

    if func_name in _HLC_INDICATORS:
        helper = _HLC_INDICATORS[func_name]
        # HLC helpers: atr(high, low, close, period), adx(high, low, close, period).
        # The period is the 4th positional arg (index 3), not the 2nd.
        period = _resolve_period_arg(node, name_periods, positional_index=3)

        def _eval_hlc(df: pd.DataFrame) -> pd.Series:
            for col in ("high", "low", "close"):
                if col not in df.columns:
                    return pd.Series(float("nan"), index=df.index)
            high = df["high"].astype(float)
            low = df["low"].astype(float)
            close = df["close"].astype(float)
            if period is not None:
                return helper(high, low, close, int(period))
            return helper(high, low, close)

        return _eval_hlc

    if func_name in _OHLCV_INDICATORS:
        helper = _OHLCV_INDICATORS[func_name]

        # vwap(high, low, close, volume) — no scalar period, just OHLCV inputs.
        def _eval_ohlcv(df: pd.DataFrame) -> pd.Series:
            for col in ("high", "low", "close", "volume"):
                if col not in df.columns:
                    return pd.Series(float("nan"), index=df.index)
            return helper(
                df["high"].astype(float),
                df["low"].astype(float),
                df["close"].astype(float),
                df["volume"].astype(float),
            )

        return _eval_ohlcv

    return None


def _tuple_indicator_subscript(
    node: ast.Subscript, name_periods: Dict[str, int]
) -> Optional[Callable[[pd.DataFrame], pd.Series]]:
    """Resolve ``bollinger_bands(close, 20)[0]`` and similar.

    Recognised only when the inner ``Call`` targets a tuple-returning
    helper and the slice is a constant non-negative integer within the
    helper's tuple arity.
    """
    if not isinstance(node.value, ast.Call):
        return None
    func_name = _func_name(node.value.func)
    if func_name is None or func_name not in _TUPLE_INDICATORS:
        return None
    slc = node.slice
    if not (
        isinstance(slc, ast.Constant)
        and isinstance(slc.value, int)
        and not isinstance(slc.value, bool)
    ):
        return None

    sig_kind, helper, max_idx = _TUPLE_INDICATORS[func_name]
    idx = slc.value
    if idx < 0 or idx >= max_idx:
        return None

    call = node.value
    if sig_kind == "series":
        column = _series_arg_column(call)
        period = _resolve_period_arg(call, name_periods, positional_index=1)

        def _eval_tuple_series(df: pd.DataFrame) -> pd.Series:
            if column not in df.columns:
                return pd.Series(float("nan"), index=df.index)
            args = [df[column].astype(float)]
            if period is not None:
                args.append(int(period))
            return helper(*args)[idx]

        return _eval_tuple_series

    # sig_kind == "hlc"
    period = _resolve_period_arg(call, name_periods, positional_index=3)

    def _eval_tuple_hlc(df: pd.DataFrame) -> pd.Series:
        for col in ("high", "low", "close"):
            if col not in df.columns:
                return pd.Series(float("nan"), index=df.index)
        args = [
            df["high"].astype(float),
            df["low"].astype(float),
            df["close"].astype(float),
        ]
        if period is not None:
            args.append(int(period))
        return helper(*args)[idx]

    return _eval_tuple_hlc


def _collect_name_evaluators(
    on_bar: ast.AST, name_periods: Dict[str, int]
) -> Dict[str, Callable[[pd.DataFrame], pd.Series]]:
    """Bind local ``Name = <indicator_call>`` assignments inside ``on_bar``.

    Walks ``on_bar``'s body for simple ``name = <expr>`` and
    ``name: T = <expr>`` assignments where the RHS resolves to an
    indicator evaluator we can call. Used so that

        sma_var = sma(close, 200)
        if bar.close > sma_var:
            ...

    (the canonical generated-strategy shape) actually reaches the
    coverage check rather than getting dropped.
    """
    bindings: Dict[str, Callable[[pd.DataFrame], pd.Series]] = {}
    for node in ast.walk(on_bar):
        targets: List[ast.expr] = []
        value: Optional[ast.expr] = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        evaluator = _indicator_call(value, name_periods) if value is not None else None
        if evaluator is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bindings.setdefault(target.id, evaluator)
    return bindings

    return None


def _func_name(func: ast.expr) -> Optional[str]:
    if isinstance(func, ast.Name):
        return func.id.lower()
    if isinstance(func, ast.Attribute):
        return func.attr.lower()
    return None


def _series_arg_column(call: ast.Call) -> str:
    """Pick the source column for a single-series indicator call.

    Defaults to ``close`` when the strategy passes something we can't
    pin to an OHLCV column (e.g. ``rsi(self.history)``).
    """
    if call.args:
        col = _column_from(call.args[0])
        if col is not None:
            return col
    return "close"


def _resolve_period_arg(
    call: ast.Call,
    name_periods: Dict[str, int],
    *,
    positional_index: int = 1,
) -> Optional[int]:
    """Pull the period (integer) from positional or kwarg form.

    ``positional_index`` is the index of the period argument in the
    helper's positional signature: 1 for series helpers like
    ``rsi(series, period)``, 3 for HLC helpers like
    ``atr(high, low, close, period)``.
    """
    for kw in call.keywords:
        if kw.arg in {"period", "length", "window", "n"}:
            value = _numeric_literal(kw.value, name_periods)
            if value is not None and value > 0:
                return int(value)
    if len(call.args) > positional_index:
        value = _numeric_literal(call.args[positional_index], name_periods)
        if value is not None and value > 0:
            return int(value)
    return None
