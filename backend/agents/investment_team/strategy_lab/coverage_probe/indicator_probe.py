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


def _extract_subconditions(strategy_code: str) -> List[List[_Subcond]]:
    """Return one group of subconditions per ``if`` predicate.

    Subconditions are grouped by their parent ``if`` so the conjunction
    hit-rate check stays scoped to a single predicate. Two unrelated
    branches like ``if close > 100: enter`` and ``if close < 50: exit``
    are returned as separate groups and are never ANDed together.
    """
    if not strategy_code:
        return []
    tree = ast.parse(strategy_code)
    name_periods = _collect_name_periods(tree)
    on_bar = _find_on_bar(tree)
    if on_bar is None:
        return []

    groups: List[List[_Subcond]] = []
    total = 0
    for node in ast.walk(on_bar):
        if not isinstance(node, ast.If):
            continue
        group: List[_Subcond] = []
        for cmp_node in _flatten_test(node.test):
            sub = _build_subcond(cmp_node, name_periods)
            if sub is None:
                continue
            group.append(sub)
            total += 1
            if total >= _MAX_SUBCONDITIONS:
                if group:
                    groups.append(group)
                return groups
        if group:
            groups.append(group)
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


def _build_subcond(node: ast.Compare, name_periods: Dict[str, int]) -> Optional[_Subcond]:
    # Only support simple a <op> b shape — chained comparisons are rare in
    # generated strategies and ambiguous for hit-rate semantics.
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return None
    op = type(node.ops[0])
    op_fn = _CMP_OPS.get(op)
    if op_fn is None:
        return None

    left = _build_operand(node.left, name_periods)
    right = _build_operand(node.comparators[0], name_periods)
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


def _build_operand(node: ast.expr, name_periods: Dict[str, int]) -> Optional[_Operand]:
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
        left = _build_operand(node.left, name_periods)
        right = _build_operand(node.right, name_periods)
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
