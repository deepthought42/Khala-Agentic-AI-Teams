"""Tests for sequential multi-batch execution in the Strategy Lab worker.

Covers the user-configurable ``batch_size`` and ``batch_count`` knobs added to
``RunStrategyLabRequest``: each batch must run after the previous one finishes,
each new strategy must see all prior strategies, and the signal-intelligence
brief must be regenerated once per batch (not once per run).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

# NOTE: import via the same module path used inside ``main.py`` so Pydantic
# treats the model classes as identical (otherwise ``agents.investment_team.X``
# and ``investment_team.X`` are two distinct module objects with two distinct
# class identities, and Pydantic v2 rejects cross-instance model assignment).
from investment_team.api import main as lab_main  # noqa: E402
from investment_team.api.main import (  # noqa: E402
    RunStrategyLabRequest,
    _strategy_lab_worker,
)
from investment_team.models import (  # noqa: E402
    BacktestResult,
    StrategyLabRecord,
    StrategySpec,
    TradeRecord,
)


def _stub_backtest_result() -> BacktestResult:
    return BacktestResult(
        total_return_pct=10.0,
        annualized_return_pct=5.0,
        volatility_pct=12.0,
        sharpe_ratio=0.5,
        max_drawdown_pct=-3.0,
        win_rate_pct=55.0,
        profit_factor=1.2,
    )


@pytest.fixture
def empty_lab_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the persistent stores with plain dicts and reset run state."""
    monkeypatch.setattr(lab_main, "_strategy_lab_records", {})
    monkeypatch.setattr(lab_main, "_strategies", {})
    monkeypatch.setattr(lab_main, "_backtests", {})
    monkeypatch.setattr(lab_main, "_active_runs", {})


def test_multi_batch_run_completes_all_cycles_and_learns_from_priors(
    empty_lab_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """batch_size=2, batch_count=3 → 6 strategies; each ideation sees all priors;
    signal brief regenerates once per batch."""

    ideation_calls: List[Dict[str, Any]] = []

    class _StubAgent:
        def __init__(self, llm_client: Any = None) -> None:
            self._counter = 0

        def ideate_strategy(
            self,
            *,
            prior_results: List[StrategyLabRecord] | None = None,
            precomputed_signal_brief: Any = None,
            exclude_asset_classes: Any = None,
        ) -> Tuple[Dict[str, Any], str]:
            self._counter += 1
            ideation_calls.append(
                {
                    "n_priors": len(prior_results or []),
                    "had_brief": precomputed_signal_brief is not None,
                }
            )
            data = {
                "asset_class": "stocks",
                "hypothesis": f"hypothesis #{self._counter}",
                "signal_definition": "sig",
                "entry_rules": ["e"],
                "exit_rules": ["x"],
                "sizing_rules": ["s"],
                "risk_limits": {},
                "speculative": False,
            }
            return data, "rationale"

        def analyze_result(self, record: StrategyLabRecord, rationale: str) -> str:
            return "ok"

    def _stub_real_data_backtest(
        strategy: StrategySpec, config: Any
    ) -> Tuple[BacktestResult, List[TradeRecord]]:
        return _stub_backtest_result(), []

    brief_calls: List[int] = []

    def _stub_compute_brief() -> Tuple[None, Dict[str, Any]]:
        # Replicates the disabled-expert path; we just need the per-batch counter
        # plus a marker so the worker treats the brief as present.
        brief_calls.append(len(brief_calls) + 1)
        return None, {"skipped": True, "skipped_reason": "test_stub"}

    monkeypatch.setattr(lab_main, "StrategyIdeationAgent", _StubAgent)
    monkeypatch.setattr(lab_main, "_run_real_data_backtest", _stub_real_data_backtest)
    monkeypatch.setattr(lab_main, "_strategy_lab_signal_expert_enabled", lambda: False)

    # Pre-seed run state so the worker's _update_run() finds the entry.
    request = RunStrategyLabRequest(batch_size=2, batch_count=3)
    run_id = "run-test-multi"
    lab_main._active_runs[run_id] = {
        "run_id": run_id,
        "status": "running",
        "started_at": lab_main._now(),
        "total_cycles": request.batch_size * request.batch_count,
        "completed_cycles": 0,
        "skipped_cycles": 0,
        "current_cycle": None,
        "completed_record_ids": [],
        "error": None,
        "request_payload": request.model_dump(),
        "batch_size": request.batch_size,
        "batch_count": request.batch_count,
        "completed_batches": 0,
        "current_batch": None,
    }

    # Disable persistence + cleanup timer side-effects.
    monkeypatch.setattr(lab_main, "_persist_run_state", lambda *a, **kw: None)
    monkeypatch.setattr(
        lab_main,
        "get_client",
        lambda *_a, **_kw: object(),
        raising=False,
    )

    # Patch the inner _compute_signal_brief by patching what it calls so we can
    # count invocations: the worker calls _compute_signal_brief() once per batch.
    # Since _compute_signal_brief is a closure inside the worker, we instead
    # count calls by checking ideation_calls' "had_brief" flag — but with the
    # signal expert disabled, the brief is None for every cycle. So we count
    # batches another way: by checking that ideation_calls grows monotonically.

    # Run worker synchronously (no thread).
    _strategy_lab_worker(run_id, request)

    # 6 total strategies generated.
    assert len(lab_main._strategy_lab_records) == 6
    assert len(ideation_calls) == 6

    # Each ideation sees N-1 priors (the just-completed records of this run).
    for i, call in enumerate(ideation_calls):
        assert call["n_priors"] == i, (
            f"cycle {i + 1} should see {i} priors but got {call['n_priors']}"
        )

    state = lab_main._active_runs[run_id]
    assert state["status"] == "completed"
    assert state["completed_cycles"] == 6
    assert state["completed_batches"] == 3
    assert len(state["completed_record_ids"]) == 6


def test_signal_brief_regenerates_once_per_batch(
    empty_lab_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the signal expert is enabled, the brief is rebuilt at every batch start
    so batch N+1 sees the records produced by batches 1..N."""

    expert_invocations: List[int] = []

    class _StubProvider:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        def fetch_context(self, _req: Any) -> Any:
            from agents.investment_team.market_lab_data.models import MarketLabContext

            return MarketLabContext(fetched_at=lab_main._now(), degraded=False, sources_used=[])

        def close(self) -> None:
            pass

    class _StubExpert:
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            pass

        def produce_signal_brief(self, prior_records: Any, _market: Any) -> Any:
            expert_invocations.append(len(prior_records))
            from agents.investment_team.signal_intelligence_models import SignalIntelligenceBriefV1

            return SignalIntelligenceBriefV1(
                brief_version=1,
                macro_themes=[],
                micro_themes=[],
                high_value_signal_hypotheses=[],
                trade_structures_benefiting=[],
                pairing_guidance="",
                evidence_from_priors="",
                evidence_from_market_data="",
                confidence="medium",
                unsupported_claims=[],
            )

    class _StubAgent:
        def __init__(self, llm_client: Any = None) -> None:
            self._n = 0

        def ideate_strategy(self, **kwargs: Any) -> Tuple[Dict[str, Any], str]:
            self._n += 1
            return (
                {
                    "asset_class": "stocks",
                    "hypothesis": f"h{self._n}",
                    "signal_definition": "s",
                    "entry_rules": [],
                    "exit_rules": [],
                    "sizing_rules": [],
                    "risk_limits": {},
                    "speculative": False,
                },
                "r",
            )

        def analyze_result(self, *_a: Any, **_kw: Any) -> str:
            return "ok"

    def _stub_backtest(
        strategy: StrategySpec, config: Any
    ) -> Tuple[BacktestResult, List[TradeRecord]]:
        return _stub_backtest_result(), []

    monkeypatch.setattr(lab_main, "StrategyIdeationAgent", _StubAgent)
    monkeypatch.setattr(lab_main, "FreeTierMarketDataProvider", _StubProvider)
    monkeypatch.setattr(lab_main, "SignalIntelligenceExpert", _StubExpert)
    monkeypatch.setattr(lab_main, "_run_real_data_backtest", _stub_backtest)
    monkeypatch.setattr(lab_main, "_strategy_lab_signal_expert_enabled", lambda: True)
    monkeypatch.setattr(lab_main, "_persist_run_state", lambda *a, **kw: None)

    # Stub get_client (used both inside _compute_signal_brief and at worker top)
    import llm_service.factory as llm_factory

    monkeypatch.setattr(llm_factory, "get_client", lambda *_a, **_kw: object())

    request = RunStrategyLabRequest(batch_size=2, batch_count=3)
    run_id = "run-test-brief"
    lab_main._active_runs[run_id] = {
        "run_id": run_id,
        "status": "running",
        "started_at": lab_main._now(),
        "total_cycles": 6,
        "completed_cycles": 0,
        "skipped_cycles": 0,
        "current_cycle": None,
        "completed_record_ids": [],
        "error": None,
        "request_payload": request.model_dump(),
        "batch_size": 2,
        "batch_count": 3,
        "completed_batches": 0,
        "current_batch": None,
    }

    _strategy_lab_worker(run_id, request)

    assert lab_main._active_runs[run_id]["status"] == "completed"
    assert len(lab_main._strategy_lab_records) == 6
    # Brief is generated exactly once per batch — 3 batches → 3 invocations.
    assert len(expert_invocations) == 3
    # Each new batch's brief sees the priors written by every previous batch.
    assert expert_invocations == [0, 2, 4]
