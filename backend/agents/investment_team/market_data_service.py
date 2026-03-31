"""Market data service — fetches real OHLCV price data from free public APIs."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, List

import httpx
from pydantic import BaseModel

from .models import StrategySpec

logger = logging.getLogger(__name__)

# Symbol mapping: internal symbol -> CoinGecko API id
_COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "MATIC": "matic-network",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "ADA": "cardano",
    "DOT": "polkadot",
}

_STOCK_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "JPM", "AMD", "SPY"]
_CRYPTO_SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP", "MATIC", "AVAX", "LINK", "ADA", "DOT"]
_OTHER_SYMBOLS = ["GLD", "USO", "TLT", "QQQ", "IWM", "EEM", "GDX", "XLE", "XLF"]


class OHLCVBar(BaseModel):
    """A single OHLCV price bar."""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketDataService:
    """Fetches real market data from public sources.

    - Stocks/ETFs: Yahoo Finance via yfinance
    - Crypto: CoinGecko free API (no key required)
    """

    def __init__(self, http_timeout: float = 30.0) -> None:
        self._timeout = http_timeout

    def fetch_ohlcv(self, symbol: str, asset_class: str, days: int = 365) -> List[OHLCVBar]:
        """Route to best data source for the asset class."""
        asset = asset_class.lower()
        if asset == "crypto":
            return self._fetch_crypto(symbol, days)
        return self._fetch_stock(symbol, days)

    def _fetch_stock(self, symbol: str, days: int) -> List[OHLCVBar]:
        """Fetch stock/ETF OHLCV data via yfinance."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed — falling back to empty data for %s", symbol)
            return []

        end_dt = date.today()
        start_dt = end_dt - timedelta(days=days)

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start_dt.isoformat(), end=end_dt.isoformat(), interval="1d")
        except Exception as exc:
            logger.error("yfinance fetch failed for %s: %s", symbol, exc)
            return []

        if df is None or df.empty:
            logger.warning("No data returned from yfinance for %s", symbol)
            return []

        bars: List[OHLCVBar] = []
        for idx, row in df.iterrows():
            bar_date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            bars.append(
                OHLCVBar(
                    date=bar_date,
                    open=round(float(row["Open"]), 4),
                    high=round(float(row["High"]), 4),
                    low=round(float(row["Low"]), 4),
                    close=round(float(row["Close"]), 4),
                    volume=float(row.get("Volume", 0)),
                )
            )
        return bars

    def _fetch_crypto(self, symbol: str, days: int) -> List[OHLCVBar]:
        """Fetch crypto OHLCV data via CoinGecko free API."""
        coin_id = _COINGECKO_IDS.get(symbol.upper())
        if not coin_id:
            logger.warning("Unknown crypto symbol %s — no CoinGecko mapping", symbol)
            return []

        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
        params = {"vs_currency": "usd", "days": str(min(days, 365))}

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                raw = resp.json()
        except Exception as exc:
            logger.error("CoinGecko fetch failed for %s: %s", symbol, exc)
            return []

        if not isinstance(raw, list):
            logger.warning("Unexpected CoinGecko response for %s", symbol)
            return []

        bars: List[OHLCVBar] = []
        for entry in raw:
            if len(entry) < 5:
                continue
            ts_ms, o, h, l_, c = entry[0], entry[1], entry[2], entry[3], entry[4]
            bar_date = date.fromtimestamp(ts_ms / 1000).isoformat()
            bars.append(
                OHLCVBar(
                    date=bar_date,
                    open=round(float(o), 4),
                    high=round(float(h), 4),
                    low=round(float(l_), 4),
                    close=round(float(c), 4),
                    volume=0.0,  # CoinGecko OHLC endpoint doesn't include volume
                )
            )
        return bars

    def get_symbols_for_strategy(self, strategy: StrategySpec) -> List[str]:
        """Return relevant symbols based on the strategy's asset class."""
        asset = strategy.asset_class.lower()
        if asset == "crypto":
            return list(_CRYPTO_SYMBOLS)
        if asset in ("stocks", "equities"):
            return list(_STOCK_SYMBOLS)
        return list(_OTHER_SYMBOLS)

    def fetch_multi_symbol(
        self, symbols: List[str], asset_class: str, days: int = 365
    ) -> Dict[str, List[OHLCVBar]]:
        """Fetch OHLCV data for multiple symbols."""
        result: Dict[str, List[OHLCVBar]] = {}
        for sym in symbols:
            bars = self.fetch_ohlcv(sym, asset_class, days)
            if bars:
                result[sym] = bars
        return result
