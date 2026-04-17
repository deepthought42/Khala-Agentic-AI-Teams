"""Unified streaming Trading Service.

Replaces the prior three trade-decision paths (LLM-per-bar ``BacktestingAgent``,
batch-sandbox backtest, and daily-bar paper trading) with a single event-driven
engine that feeds a stream of bars/ticks to a Strategy-Lab-generated Python
script. The strategy submits orders; the engine decides fills.

Only the Strategy-Lab-generated Python script is allowed to produce trades.

See ``CLAUDE.md`` and ``backend/agents/investment_team/system_design/`` for
architectural context.
"""

from .service import TradingService, TradingServiceResult

__all__ = ["TradingService", "TradingServiceResult"]
