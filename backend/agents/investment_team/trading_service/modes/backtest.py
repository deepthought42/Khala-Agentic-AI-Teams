"""Backtest mode — replays historical bars through the Trading Service.

This is the only public entrypoint for running a Strategy-Lab-generated
script against historical data. Callers provide pre-fetched market data
(kept compatible with the existing ``MarketDataService``) and the
:class:`StrategySpec` whose ``strategy_code`` defines a subclass of
``Strategy``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

from ...market_data_service import OHLCVBar
from ...models import BacktestConfig, BacktestResult, StrategySpec, TradeRecord
from ...trade_simulator import compute_metrics
from ..data_stream.historical_replay import HistoricalReplayStream
from ..service import TradingService, TradingServiceResult

logger = logging.getLogger(__name__)


@dataclass
class BacktestRunResult:
    result: BacktestResult
    trades: List[TradeRecord]
    service_result: TradingServiceResult


def run_backtest(
    *,
    strategy: StrategySpec,
    config: BacktestConfig,
    market_data: Dict[str, List[OHLCVBar]],
    timeframe: str = "1d",
) -> BacktestRunResult:
    """Run a backtest for ``strategy`` against ``market_data``.

    Raises ``ValueError`` if the strategy has no ``strategy_code`` —
    the LLM-per-bar fallback is intentionally gone.
    """
    if not strategy.strategy_code:
        raise ValueError(
            "StrategySpec.strategy_code is required; the LLM-per-bar backtest "
            "path has been removed. Regenerate the strategy via the Strategy "
            "Lab ideation agent."
        )

    stream = HistoricalReplayStream(market_data, timeframe=timeframe)
    service = TradingService(
        strategy_code=strategy.strategy_code,
        config=config,
        risk_limits=strategy.risk_limits,
    )
    service_result = service.run(stream)

    if service_result.error and not service_result.trades:
        logger.warning(
            "backtest for %s ended with error (%s) and no trades",
            strategy.strategy_id,
            service_result.error[:200],
        )

    metrics = compute_metrics(
        service_result.trades,
        config.initial_capital,
        config.start_date,
        config.end_date,
    )
    return BacktestRunResult(
        result=metrics,
        trades=service_result.trades,
        service_result=service_result,
    )
