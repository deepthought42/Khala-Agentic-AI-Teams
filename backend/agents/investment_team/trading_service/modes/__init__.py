"""Entrypoints that wire a data stream into the TradingService for a given mode."""

from .backtest import BacktestRunResult, run_backtest

__all__ = ["BacktestRunResult", "run_backtest"]
