"""
Strategy Ideation Agent — generates swing trading strategies using LLM, informed by past results.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from llm_service.interface import LLMClient

from .models import StrategyLabRecord, TradeRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_IDEATION_SYSTEM = (
    "You are an expert quantitative trading strategy designer specializing in swing trading. "
    "Your role is to generate novel, testable trading strategies for stocks and cryptocurrency markets. "
    "Focus on strategies that could realistically achieve 8%+ annualized returns through systematic rules."
)

_IDEATION_PROMPT = """\
Generate a novel swing trading strategy for stocks or cryptocurrency.

Swing trading targets holding periods of 2–14 days, capturing short-term price swings.
Goal: exceed 8% annualized return with controlled drawdown.

## Prior Strategy Results ({n_prior} tested so far, chronological)
{prior_results_text}

## Instructions
Each prior entry includes: outcome (WINNING/LOSING vs 8% annual), key metrics, the ideation rationale, and the post-backtest analysis (why it succeeded or failed).
Generate ONE new strategy that DIFFERS from all of the above — explore under-tested approaches and learn from those outcomes.
Return ONLY a JSON object with no markdown:
{{
  "asset_class": "stocks" or "crypto",
  "hypothesis": "1-2 sentence investment thesis",
  "signal_definition": "specific technical or fundamental signal description",
  "entry_rules": ["entry rule 1", "entry rule 2", "entry rule 3"],
  "exit_rules": ["exit rule 1", "exit rule 2"],
  "sizing_rules": ["sizing rule 1"],
  "risk_limits": {{"max_position_pct": 5, "stop_loss_pct": 3}},
  "speculative": false,
  "rationale": "why you chose this strategy given prior results"
}}
"""

_ANALYSIS_DRAFT_SYSTEM = (
    "You are a senior quantitative trading analyst. You reason carefully from evidence: "
    "strategy rules, aggregate backtest metrics, and per-trade simulated results. "
    "You do not invent statistics; every claim must be grounded in the data provided."
)

_ANALYSIS_DRAFT_WIN = """\
Draft a rigorous analysis of this WINNING swing-trading strategy (annualized return above 8% threshold).

## Strategy (definition under test)
Asset class: {asset_class}
Hypothesis: {hypothesis}
Signal: {signal_definition}
Entry rules: {entry_rules}
Exit rules: {exit_rules}
Sizing / risk: {sizing_rules}
Rationale for testing: {rationale}

## Aggregated backtest metrics
Annualized return: {annualized_return_pct:.1f}%
Total return: {total_return_pct:.1f}%
Sharpe ratio: {sharpe_ratio:.2f}
Max drawdown: {max_drawdown_pct:.1f}%
Win rate: {win_rate_pct:.1f}%
Profit factor: {profit_factor:.2f}
Volatility: {volatility_pct:.1f}%

## Simulated trade ledger (evidence)
{simulated_trades_section}

## Instructions
Think step by step: what in the strategy design plausibly produced strong risk-adjusted returns?
Relate the hypothesis and rules to (1) Sharpe/drawdown/volatility, (2) win rate vs profit factor, (3) patterns in the simulated trades (hold periods, win/loss mix, concentration).
Write 5–8 sentences. Be specific—avoid generic praise. Explain *why* this strategy class succeeded in this backtest.

Return ONLY JSON with no markdown:
{{"draft_narrative": "your draft analysis"}}
"""

_ANALYSIS_DRAFT_LOSE = """\
Draft a rigorous analysis of this LOSING swing-trading strategy (annualized return below 8% threshold).

## Strategy (definition under test)
Asset class: {asset_class}
Hypothesis: {hypothesis}
Signal: {signal_definition}
Entry rules: {entry_rules}
Exit rules: {exit_rules}
Sizing / risk: {sizing_rules}
Rationale for testing: {rationale}

## Aggregated backtest metrics
Annualized return: {annualized_return_pct:.1f}%
Total return: {total_return_pct:.1f}%
Sharpe ratio: {sharpe_ratio:.2f}
Max drawdown: {max_drawdown_pct:.1f}%
Win rate: {win_rate_pct:.1f}%
Profit factor: {profit_factor:.2f}
Volatility: {volatility_pct:.1f}%

## Simulated trade ledger (evidence)
{simulated_trades_section}

## Instructions
Think step by step: what failure modes explain weak performance—signal timing, risk/reward asymmetry, cost drag, or rules misaligned with the market regime implied by the results?
Use the trade-level evidence where it supports your reasoning.
Write 5–8 sentences. Be specific about *why* this strategy underperformed.

Return ONLY JSON with no markdown:
{{"draft_narrative": "your draft analysis"}}
"""

_SELF_REVIEW_SYSTEM = (
    "You are a critical peer reviewer for quantitative research. "
    "You ensure narrative analysis is faithful to strategy specs, backtest aggregates, and simulated trade facts. "
    "You correct any contradiction or overclaim before signing off."
)

_SELF_REVIEW_PROMPT = """\
Perform a self-review of the draft analysis below.

## Strategy facts (source of truth)
Asset class: {asset_class}
Hypothesis: {hypothesis}
Signal: {signal_definition}
Entry rules: {entry_rules}
Exit rules: {exit_rules}

## Aggregated metrics (source of truth)
Annualized: {annualized_return_pct:.1f}% | Total: {total_return_pct:.1f}% | Sharpe: {sharpe_ratio:.2f}
Max DD: {max_drawdown_pct:.1f}% | Win rate: {win_rate_pct:.1f}% | Profit factor: {profit_factor:.2f} | Vol: {volatility_pct:.1f}%
Outcome label: {outcome_label}

## Simulated trades summary (source of truth)
{simulated_trades_section}

## Draft analysis to verify
{draft_narrative}

## Instructions
1. Check every substantive claim in the draft against the strategy, metrics, and trade evidence.
2. Remove or rewrite anything that is unsupported, vague, or contradicts the numbers.
3. Produce a single polished narrative (5–10 sentences) that a risk committee could rely on.
4. In verification_notes (2–4 sentences), state what you verified and any material corrections.

Return ONLY JSON with no markdown:
{{"revised_narrative": "...", "verification_notes": "..."}}
"""


def _format_prior_results(records: List[StrategyLabRecord], *, max_records: int = 50) -> str:
    if not records:
        return "None yet — this is the first strategy."
    ordered = sorted(records, key=lambda x: x.created_at)
    if len(ordered) > max_records:
        ordered = ordered[-max_records:]
    lines = []
    for i, r in enumerate(ordered, start=1):
        label = "WINNING" if r.is_winning else "LOSING"
        hyp = r.strategy.hypothesis.replace("\n", " ").strip()
        if len(hyp) > 160:
            hyp = hyp[:157] + "..."
        analysis = (r.analysis_narrative or "").replace("\n", " ").strip()
        if len(analysis) > 420:
            analysis = analysis[:417] + "..."
        rationale = (r.strategy_rationale or "").replace("\n", " ").strip()
        if len(rationale) > 220:
            rationale = rationale[:217] + "..."
        res = r.backtest.result
        lines.append(
            f"{i}. [{label}] {r.strategy.asset_class} | {hyp}\n"
            f"   Metrics: annual {res.annualized_return_pct:.1f}%, Sharpe {res.sharpe_ratio:.2f}, "
            f"max DD {res.max_drawdown_pct:.1f}%, win rate {res.win_rate_pct:.1f}%\n"
            f"   Ideation rationale: {rationale}\n"
            f"   Post-backtest analysis: {analysis}"
        )
    return "\n\n".join(lines)


def _format_simulated_trades_summary(trades: List[TradeRecord], *, max_sample_rows: int = 14) -> str:
    """Compact evidence string from the simulated ledger for analysis + self-review."""
    if not trades:
        return "No simulated trades in ledger."
    n = len(trades)
    wins = sum(1 for t in trades if t.outcome == "win")
    losses = n - wins
    holds = [t.hold_days for t in trades]
    rets = [t.return_pct for t in trades]
    avg_hold = sum(holds) / n
    best_i = max(range(n), key=lambda i: rets[i])
    worst_i = min(range(n), key=lambda i: rets[i])
    tw = trades[best_i]
    tl = trades[worst_i]
    final_cum = trades[-1].cumulative_pnl

    lines = [
        f"Aggregate: {n} simulated trades | {wins} wins / {losses} losses "
        f"({100.0 * wins / n:.1f}% win rate on trades)",
        f"Hold days: avg {avg_hold:.1f}, min {min(holds)}, max {max(holds)}",
        f"Per-trade return %: best {rets[best_i]:.2f}% (trade #{tw.trade_num} {tw.symbol}), "
        f"worst {rets[worst_i]:.2f}% (trade #{tl.trade_num} {tl.symbol})",
        f"Sum of net P&L implied by ledger path; ending cumulative P&L ≈ {final_cum:.2f}",
        "",
        "Sample trades (chronological mix):",
    ]
    # head + tail samples
    indices: List[int] = []
    if n <= max_sample_rows:
        indices = list(range(n))
    else:
        head = max_sample_rows // 2
        tail = max_sample_rows - head
        indices = list(range(head)) + list(range(n - tail, n))

    seen = set()
    for i in indices:
        if i in seen:
            continue
        seen.add(i)
        t = trades[i]
        lines.append(
            f"  #{t.trade_num} {t.symbol} {t.entry_date}→{t.exit_date} "
            f"hold={t.hold_days}d ret={t.return_pct:.2f}% net={t.net_pnl:.2f} "
            f"cum={t.cumulative_pnl:.2f} [{t.outcome}]"
        )
    if n > len(seen):
        lines.append(f"  ... ({n - len(seen)} additional trades not shown) ...")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class StrategyIdeationAgent:
    """
    Uses an LLM to:
      1. Ideate a novel swing trading strategy informed by past results.
      2. Generate a post-backtest narrative explaining success or failure.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    def ideate_strategy(
        self,
        prior_results: Optional[List[StrategyLabRecord]] = None,
    ) -> Tuple[Dict[str, Any], str]:
        """
        Generate a new strategy spec dict and rationale.

        Returns:
            (strategy_dict, rationale) — strategy_dict matches StrategySpec fields,
            rationale is the LLM's explanation for the choice.
        """
        prior_results = prior_results or []
        prior_text = _format_prior_results(prior_results)

        prompt = _IDEATION_PROMPT.format(
            n_prior=len(prior_results),
            prior_results_text=prior_text,
        )

        data = self.llm.complete_json(
            prompt,
            temperature=0.8,
            system_prompt=_IDEATION_SYSTEM,
            think=True,
        )

        rationale = str(data.pop("rationale", "No rationale provided."))
        return data, rationale

    def analyze_result(
        self,
        record: StrategyLabRecord,
        rationale: str,
    ) -> str:
        """
        Draft a deep analysis grounded in strategy, metrics, and simulated trades,
        then self-review for consistency and accuracy.
        """
        result = record.backtest.result
        strategy = record.strategy
        trades = record.backtest.trades
        outcome_label = (
            "WINNING (>8% annualized)" if record.is_winning else "LOSING (<8% annualized)"
        )

        simulated_trades_section = _format_simulated_trades_summary(trades)
        sizing_rules = "; ".join(strategy.sizing_rules) if strategy.sizing_rules else "(none)"
        risk_limits = str(strategy.risk_limits) if strategy.risk_limits else "{}"

        common = dict(
            asset_class=strategy.asset_class,
            hypothesis=strategy.hypothesis,
            signal_definition=strategy.signal_definition,
            entry_rules="; ".join(strategy.entry_rules),
            exit_rules="; ".join(strategy.exit_rules),
            sizing_rules=f"{sizing_rules} | risk_limits: {risk_limits}",
            rationale=rationale,
            annualized_return_pct=result.annualized_return_pct,
            total_return_pct=result.total_return_pct,
            sharpe_ratio=result.sharpe_ratio,
            max_drawdown_pct=result.max_drawdown_pct,
            win_rate_pct=result.win_rate_pct,
            profit_factor=result.profit_factor,
            volatility_pct=result.volatility_pct,
            simulated_trades_section=simulated_trades_section,
        )

        if record.is_winning:
            draft_prompt = _ANALYSIS_DRAFT_WIN.format(**common)
        else:
            draft_prompt = _ANALYSIS_DRAFT_LOSE.format(**common)

        try:
            draft_data = self.llm.complete_json(
                draft_prompt,
                temperature=0.35,
                system_prompt=_ANALYSIS_DRAFT_SYSTEM,
                think=True,
            )
            draft_narrative = str(draft_data.get("draft_narrative", "")).strip()
        except Exception as exc:
            logger.warning("Draft analysis failed: %s", exc)
            draft_narrative = ""

        if not draft_narrative:
            draft_narrative = (
                f"Outcome {outcome_label}: annualized {result.annualized_return_pct:.1f}%, "
                f"Sharpe {result.sharpe_ratio:.2f}, max drawdown {result.max_drawdown_pct:.1f}%."
            )

        review_prompt = _SELF_REVIEW_PROMPT.format(
            asset_class=strategy.asset_class,
            hypothesis=strategy.hypothesis,
            signal_definition=strategy.signal_definition,
            entry_rules="; ".join(strategy.entry_rules),
            exit_rules="; ".join(strategy.exit_rules),
            annualized_return_pct=result.annualized_return_pct,
            total_return_pct=result.total_return_pct,
            sharpe_ratio=result.sharpe_ratio,
            max_drawdown_pct=result.max_drawdown_pct,
            win_rate_pct=result.win_rate_pct,
            profit_factor=result.profit_factor,
            volatility_pct=result.volatility_pct,
            outcome_label=outcome_label,
            simulated_trades_section=simulated_trades_section,
            draft_narrative=draft_narrative,
        )

        try:
            reviewed = self.llm.complete_json(
                review_prompt,
                temperature=0.15,
                system_prompt=_SELF_REVIEW_SYSTEM,
                think=True,
            )
            revised = str(reviewed.get("revised_narrative", "")).strip()
            verification = str(reviewed.get("verification_notes", "")).strip()
        except Exception as exc:
            logger.warning("Self-review failed: %s", exc)
            revised = draft_narrative
            verification = ""

        if not revised:
            revised = draft_narrative

        if verification:
            return (
                f"{revised}\n\n"
                f"[Self-review: {verification}]"
            )
        return revised
