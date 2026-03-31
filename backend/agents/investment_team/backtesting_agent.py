"""
Backtesting Agent — runs historical backtests using real market data and LLM-driven trade decisions.

Delegates the bar-walking simulation to :class:`TradeSimulationEngine` and provides
the LLM evaluation callback with backtest-specific prompt context.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from llm_service.interface import LLMClient

from .market_data_service import OHLCVBar
from .models import (
    BacktestConfig,
    BacktestResult,
    StrategySpec,
    TradeRecord,
)
from .trade_simulator import (
    OpenPosition,
    TradeSimulationEngine,
    compute_metrics,
    format_bars_table,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_EVALUATE_SYSTEM = (
    "You are an expert quantitative trader backtesting a swing trading strategy against historical data. "
    "You evaluate daily price bars against the strategy's entry and exit rules to decide whether to trade. "
    "Be disciplined — only trade when the rules are clearly met by the price data. "
    "Remember: this is a backtest, so you must only use information available on the current bar's date."
)

_EVALUATE_PROMPT = """\
Evaluate whether the trading strategy's rules are triggered for this historical market data.

## Strategy
Asset class: {asset_class}
Hypothesis: {hypothesis}
Signal: {signal_definition}
Entry rules: {entry_rules}
Exit rules: {exit_rules}
Sizing rules: {sizing_rules}
Risk limits: {risk_limits}

## Current Position
{position_status}

## Available Capital
${capital:,.2f}

## Current Bar ({symbol}, {current_date})
Open: {open}  High: {high}  Low: {low}  Close: {close}  Volume: {volume}

## Recent Price History ({symbol}, last {n_bars} bars)
{recent_bars_text}

## Instructions
Based on the strategy rules and market data above, decide your action.
If you have NO open position, evaluate ENTRY rules. If you HAVE an open position, evaluate EXIT rules.
Be conservative — only enter when signals are clearly met, and respect risk limits.
Do NOT use any future information — only data up to and including the current bar.

Return ONLY a JSON object with no markdown:
{{"action": "enter_long" or "enter_short" or "exit" or "hold", "confidence": 0.0 to 1.0, \
"shares": number_of_shares_or_0, "reasoning": "brief explanation"}}

For "hold", set shares to 0. For entries, calculate shares based on sizing rules and available capital.
For exits, set shares to 0 (will close full position).
"""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class BacktestingAgent:
    """
    Runs backtests against real historical market data by walking through OHLCV bars
    chronologically and using the LLM to interpret strategy entry/exit rules.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    def run_backtest(
        self,
        strategy: StrategySpec,
        config: BacktestConfig,
        market_data: Dict[str, List[OHLCVBar]],
    ) -> tuple[BacktestResult, List[TradeRecord]]:
        """
        Walk through historical market data bar-by-bar, making LLM-driven trade decisions.

        Returns (BacktestResult, trade_ledger).
        """
        engine = TradeSimulationEngine(
            initial_capital=config.initial_capital,
            transaction_cost_bps=config.transaction_cost_bps,
            slippage_bps=config.slippage_bps,
        )

        def evaluate(
            symbol: str,
            bar: OHLCVBar,
            recent: List[OHLCVBar],
            position: Optional[OpenPosition],
            capital: float,
        ) -> Dict[str, Any]:
            return self._evaluate_bar(strategy, symbol, bar, recent, position, capital)

        sim = engine.run(market_data, evaluate)

        result = compute_metrics(
            sim.trades, config.initial_capital, config.start_date, config.end_date
        )
        return result, sim.trades

    def _evaluate_bar(
        self,
        strategy: StrategySpec,
        symbol: str,
        current_bar: OHLCVBar,
        recent_bars: List[OHLCVBar],
        open_position: Optional[OpenPosition],
        capital: float,
    ) -> Dict[str, Any]:
        """Ask LLM to evaluate whether entry/exit rules are met for this bar."""
        if open_position:
            pos_status = (
                f"OPEN {open_position.side.upper()} position in {symbol}: "
                f"{open_position.shares} shares @ ${open_position.entry_price:.2f} "
                f"(entered {open_position.entry_date})"
            )
        else:
            pos_status = "No open position — looking for entry signals."

        prompt = _EVALUATE_PROMPT.format(
            asset_class=strategy.asset_class,
            hypothesis=strategy.hypothesis,
            signal_definition=strategy.signal_definition,
            entry_rules="; ".join(strategy.entry_rules),
            exit_rules="; ".join(strategy.exit_rules),
            sizing_rules="; ".join(strategy.sizing_rules),
            risk_limits=strategy.risk_limits,
            position_status=pos_status,
            capital=capital,
            symbol=symbol,
            current_date=current_bar.date,
            open=current_bar.open,
            high=current_bar.high,
            low=current_bar.low,
            close=current_bar.close,
            volume=current_bar.volume,
            n_bars=len(recent_bars),
            recent_bars_text=format_bars_table(recent_bars),
        )

        data = self.llm.complete_json(
            prompt,
            temperature=0.2,
            system_prompt=_EVALUATE_SYSTEM,
            think=True,
        )

        return {
            "action": str(data.get("action", "hold")),
            "confidence": float(data.get("confidence", 0.0)),
            "shares": float(data.get("shares", 0)),
            "reasoning": str(data.get("reasoning", "")),
        }
