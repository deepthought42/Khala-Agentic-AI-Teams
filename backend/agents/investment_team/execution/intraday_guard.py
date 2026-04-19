"""Intraday data-source safety check (Phase 5 — partial).

CoinGecko's ``/market_chart`` endpoint returns OHLCV that's reconstructed
from hourly price snapshots rather than sourced from real trade ticks.  The
series is acceptable for daily backtests but is *not* reliable as an
intraday signal source — using it can silently distort paper-trading
verdicts.

``check_intraday_data_source`` is the gate the orchestrator / paper-trade
path calls after fetching market data but before handing it to the
strategy.  It raises :class:`IntradayDataError` when ``intraday_mode`` is
true and any symbol's OHLCV came from CoinGecko; callers surface the error
to the user instead of producing misleading results.
"""

from __future__ import annotations

from typing import Mapping

# Providers whose OHLCV is not trustworthy at intraday granularity.
_UNSAFE_INTRADAY_PROVIDERS = frozenset({"coingecko"})


class IntradayDataError(RuntimeError):
    """Raised when an intraday run falls back to an unreliable OHLCV source.

    Carries the offending ``symbol`` and ``provider`` name so the caller
    can surface both in an error message without reconstructing them.
    """

    def __init__(self, *, symbol: str, provider: str) -> None:
        super().__init__(
            f"intraday_mode is set but OHLCV for {symbol!r} came from "
            f"{provider!r}, whose series is reconstructed from periodic "
            "price snapshots and is not safe for intraday signals."
        )
        self.symbol = symbol
        self.provider = provider


def check_intraday_data_source(
    *,
    intraday_mode: bool,
    provider_used: Mapping[str, str],
) -> None:
    """Raise :class:`IntradayDataError` when an intraday run used a banned provider.

    ``provider_used`` maps each symbol to the provider name that supplied
    its bars (as recorded by ``MarketDataService.provider_used``).  Silent
    no-op when ``intraday_mode`` is false — callers are free to pass the
    flag through unconditionally.
    """
    if not intraday_mode:
        return
    for symbol, provider in provider_used.items():
        if provider in _UNSAFE_INTRADAY_PROVIDERS:
            raise IntradayDataError(symbol=symbol, provider=provider)


__all__ = ["IntradayDataError", "check_intraday_data_source"]
