"""Static, AST-based coverage probe for Strategy Lab strategies (#447).

Inspects ``StrategySpec.strategy_code`` without executing it and flags
configurations that would deterministically prevent entries: warm-up
windows longer than the available history, hardcoded symbols missing
from the fetched universe, and position-percent literals exceeding the
strategy's own ``risk_limits.max_position_pct``.

Pure: no I/O, no market fetch, no LLM. Bounded: single ``ast.parse`` +
single ``ast.walk`` over the input source.
"""

from __future__ import annotations

import ast
import re
from typing import Iterable, List, Sequence

from investment_team.models import (
    CoverageCategory,
    CoverageReport,
    LikelyBlocker,
    StrategySpec,
)

_PERIOD_NAME_RE = re.compile(
    r"^(?:WINDOW(?:_[A-Z0-9]+)?|[A-Z0-9_]*_(?:PERIOD|LOOKBACK)|LOOKBACK[A-Z0-9_]*|MIN_HISTORY)$"
)
_PCT_NAME_RE = re.compile(r"^(?:POSITION_PCT|MAX_POSITION_PCT|[A-Z0-9_]+_PERCENT|[A-Z0-9_]+_PCT)$")
_PCT_KWARG_NAMES = frozenset({"pct", "position_pct", "max_position_pct"})


def run_static_probe(
    spec: StrategySpec,
    fetched_universe: Sequence[str],
    available_bars: int,
) -> CoverageReport:
    """Return a partial CoverageReport derived from static analysis only.

    ``available_bars`` is the count of bars the upcoming backtest can
    reach for the longest-history symbol (caller computes from
    ``BacktestConfig`` + market data length). The probe never reads
    market data itself.
    """
    universe_set = {s for s in fetched_universe if isinstance(s, str)}
    symbols_checked = len(universe_set)

    code = spec.strategy_code
    if not code:
        return CoverageReport(
            coverage_category=CoverageCategory.UNKNOWN_LOW_COVERAGE,
            summary="no strategy_code provided",
            symbols_checked=symbols_checked,
            bars_checked=max(0, int(available_bars)),
        )

    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return CoverageReport(
            coverage_category=CoverageCategory.UNKNOWN_LOW_COVERAGE,
            summary="strategy_code did not parse",
            symbols_checked=symbols_checked,
            bars_checked=max(0, int(available_bars)),
        )

    periods: List[int] = []
    hardcoded_symbols: List[str] = []
    position_pcts: List[float] = []

    for node in ast.walk(tree):
        # 1) Constant assignments: WINDOW = 80, MIN_HISTORY = 20, POSITION_PCT = 5.0
        if isinstance(node, ast.Assign):
            for target in node.targets:
                _collect_named_constant(target, node.value, periods, position_pcts)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            _collect_named_constant(node.target, node.value, periods, position_pcts)

        # 2) Call sites: ctx.submit_order(symbol="TSLA", ...), ctx.history(sym, 100)
        elif isinstance(node, ast.Call):
            attr = _attr_name(node.func)
            if attr == "submit_order":
                for kw in node.keywords:
                    if (
                        kw.arg == "symbol"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ):
                        hardcoded_symbols.append(kw.value.value)
                    elif kw.arg in _PCT_KWARG_NAMES:
                        val = _numeric_constant(kw.value)
                        if val is not None:
                            position_pcts.append(val)
            elif attr == "history" and len(node.args) >= 2:
                second = node.args[1]
                if (
                    isinstance(second, ast.Constant)
                    and isinstance(second.value, int)
                    and not isinstance(second.value, bool)
                ):
                    if second.value > 0:
                        periods.append(second.value)

    warmup_bars_required = max(periods) if periods else 0
    missing_symbols = [s for s in _dedupe(hardcoded_symbols) if s not in universe_set]
    max_pct_limit = float(spec.risk_limits.max_position_pct)
    # Strategies often express sizing as a fraction (the ideation prompt
    # documents ``qty = ctx.equity * pct / bar.close``), while
    # ``RiskLimits.max_position_pct`` is in percent units (0..100).
    # Normalize literals in (0, 1] to percent before comparing so a
    # ``POSITION_PCT = 0.10`` (10%) gets caught against a 6% limit.
    over_limit_pcts: List[tuple[float, float]] = []
    for raw in position_pcts:
        normalized = raw * 100.0 if 0.0 < raw <= 1.0 else raw
        if normalized > max_pct_limit:
            over_limit_pcts.append((float(raw), normalized))

    blockers: List[LikelyBlocker] = []
    category = CoverageCategory.COVERAGE_OK
    summary = "static probe found no blockers"

    if available_bars > 0 and warmup_bars_required > available_bars:
        category = CoverageCategory.WARMUP_EXCEEDS_HISTORY
        summary = f"warmup window {warmup_bars_required} exceeds {available_bars} available bars"
        blockers.append(
            LikelyBlocker(
                reason="warmup_exceeds_history",
                evidence=f"warmup={warmup_bars_required} > available_bars={available_bars}",
            )
        )

    if missing_symbols:
        if category == CoverageCategory.COVERAGE_OK:
            category = CoverageCategory.TARGET_SYMBOL_MISSING
            summary = f"target symbol {missing_symbols[0]!r} not present in fetched universe"
        for sym in missing_symbols:
            blockers.append(
                LikelyBlocker(
                    reason="target_symbol_missing",
                    evidence=f"target symbol {sym!r} not present in fetched universe",
                )
            )

    for raw, normalized in over_limit_pcts:
        if normalized != raw:
            evidence = (
                f"position_pct literal {raw} (={normalized}% of equity) "
                f"> risk_limits.max_position_pct {max_pct_limit}"
            )
        else:
            evidence = f"position_pct literal {raw} > risk_limits.max_position_pct {max_pct_limit}"
        blockers.append(
            LikelyBlocker(
                reason="position_pct_exceeds_risk_limit",
                evidence=evidence,
            )
        )

    return CoverageReport(
        coverage_category=category,
        summary=summary,
        symbols_checked=symbols_checked,
        bars_checked=max(0, int(available_bars)),
        warmup_bars_required=warmup_bars_required,
        entry_orders_emitted=0,
        likely_blockers=blockers,
    )


def _collect_named_constant(
    target: ast.expr,
    value: ast.expr,
    periods: List[int],
    position_pcts: List[float],
) -> None:
    name = _target_name(target)
    if name is None:
        return
    numeric = _numeric_constant(value)
    if numeric is None:
        return
    if _PERIOD_NAME_RE.match(name):
        if isinstance(numeric, float) and not numeric.is_integer():
            return
        ivalue = int(numeric)
        if ivalue > 0:
            periods.append(ivalue)
    elif _PCT_NAME_RE.match(name):
        position_pcts.append(float(numeric))


def _target_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        # e.g. ``self.WINDOW = 80`` inside ``__init__`` — flag the attr name.
        return node.attr
    return None


def _attr_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _numeric_constant(node: ast.expr) -> float | int | None:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _numeric_constant(node.operand)
        if inner is not None:
            return -inner
    return None


def _dedupe(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
