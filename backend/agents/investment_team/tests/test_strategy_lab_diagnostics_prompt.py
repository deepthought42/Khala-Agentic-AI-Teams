"""Tests for ``_format_execution_diagnostics`` (issue #414, part of #404).

The orchestrator wraps the executor's ``BacktestExecutionDiagnostics`` envelope
into a single compact JSON line that gets appended to the refinement prompt's
``failure_details`` string. The line lets the refinement agent see structured
evidence (categories, counters, rejection reasons, lifecycle events) that the
prose summary in the gate ``details`` text leaves out.
"""

from __future__ import annotations

import json

from investment_team.models import (
    BacktestExecutionDiagnostics,
    OpenPositionDiagnostic,
    OrderLifecycleEvent,
)
from investment_team.strategy_lab.orchestrator import (
    _DIAGNOSTICS_LAST_EVENTS_CAP,
    _format_execution_diagnostics,
)


def _block_payload(line: str) -> dict:
    """Strip the ``Execution Diagnostics: `` prefix and parse the JSON body."""
    prefix = "Execution Diagnostics: "
    assert line.startswith(prefix), line
    return json.loads(line[len(prefix) :])


def test_returns_empty_string_when_diagnostics_missing():
    assert _format_execution_diagnostics(None) == ""


def test_returns_empty_string_when_category_unset():
    """Healthy backtests must not bloat the refinement prompt — the helper
    only emits a block when the executor classified a zero-trade failure."""
    diagnostics = BacktestExecutionDiagnostics(
        zero_trade_category=None,
        summary="",
        bars_processed=250,
        orders_emitted=12,
        entries_filled=12,
        closed_trades=12,
    )
    assert _format_execution_diagnostics(diagnostics) == ""


def test_emits_compact_json_block_with_expected_keys():
    diagnostics = BacktestExecutionDiagnostics(
        zero_trade_category="ORDERS_REJECTED",
        summary="All 12 emitted orders were rejected before fill.",
        bars_processed=300,
        orders_emitted=12,
        orders_accepted=0,
        orders_rejected=12,
        orders_rejection_reasons={"risk_limit": 7, "insufficient_capital": 5},
        last_order_events=[
            OrderLifecycleEvent(
                event_type="rejected",
                symbol="AAPL",
                side="long",
                reason="risk_limit",
                detail="position_size_exceeded",
            ),
        ],
        open_positions_at_end=[
            OpenPositionDiagnostic(
                symbol="MSFT",
                side="long",
                qty=10.0,
                entry_price=300.0,
                entry_timestamp="2024-06-15T15:30:00",
            ),
        ],
    )

    line = _format_execution_diagnostics(diagnostics)
    payload = _block_payload(line)

    assert payload["zero_trade_category"] == "ORDERS_REJECTED"
    assert payload["summary"] == "All 12 emitted orders were rejected before fill."
    assert payload["orders_emitted"] == 12
    assert payload["orders_rejected"] == 12
    assert payload["orders_rejection_reasons"] == {
        "risk_limit": 7,
        "insufficient_capital": 5,
    }
    assert len(payload["last_order_events"]) == 1
    assert payload["last_order_events"][0]["event_type"] == "rejected"
    assert payload["open_positions_at_end"][0]["symbol"] == "MSFT"


def test_last_order_events_truncated_to_cap_keeping_most_recent():
    """``BacktestExecutionDiagnostics.last_order_events`` already caps at 20
    inside the trading service; the prompt block trims further to the most
    recent ``_DIAGNOSTICS_LAST_EVENTS_CAP`` to keep the JSON line short."""
    over_cap = _DIAGNOSTICS_LAST_EVENTS_CAP + 5
    events = [
        OrderLifecycleEvent(
            event_type="emitted",
            symbol="AAPL",
            side="long",
            detail=f"event_{i}",
        )
        for i in range(over_cap)
    ]
    diagnostics = BacktestExecutionDiagnostics(
        zero_trade_category="ORDERS_UNFILLED",
        summary="never crossed the fill price",
        last_order_events=events,
    )

    line = _format_execution_diagnostics(diagnostics)
    payload = _block_payload(line)

    kept = payload["last_order_events"]
    assert len(kept) == _DIAGNOSTICS_LAST_EVENTS_CAP
    # Most recent are kept (suffix), not the prefix.
    assert kept[0]["detail"] == f"event_{over_cap - _DIAGNOSTICS_LAST_EVENTS_CAP}"
    assert kept[-1]["detail"] == f"event_{over_cap - 1}"


def test_json_is_compact_and_key_sorted_for_determinism():
    """The block goes into LLM prompts — deterministic key ordering keeps
    cache hits stable across runs and the compact separators minimize tokens.
    """
    diagnostics = BacktestExecutionDiagnostics(
        zero_trade_category="NO_ORDERS_EMITTED",
        summary="no orders",
        bars_processed=100,
        orders_emitted=0,
    )

    line = _format_execution_diagnostics(diagnostics)
    body = line[len("Execution Diagnostics: ") :]

    # Compact: no whitespace after separators.
    assert ", " not in body
    assert ": " not in body

    # Key-sorted: re-encoding with sort_keys must be byte-identical.
    payload = json.loads(body)
    assert json.dumps(payload, separators=(",", ":"), sort_keys=True) == body
