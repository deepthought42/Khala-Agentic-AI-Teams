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
        """Route to best data source for the asset class (recent N days)."""
        end_dt = date.today()
        start_dt = end_dt - timedelta(days=days)
        return self.fetch_ohlcv_range(symbol, asset_class, start_dt.isoformat(), end_dt.isoformat())

    def fetch_ohlcv_range(
        self, symbol: str, asset_class: str, start_date: str, end_date: str
    ) -> List[OHLCVBar]:
        """Fetch OHLCV data for an explicit date range. Routes by asset class."""
        asset = asset_class.lower()
        if asset == "crypto":
            return self._fetch_crypto(symbol, start_date, end_date)
        return self._fetch_stock(symbol, start_date, end_date)

    def _fetch_stock(self, symbol: str, start_date: str, end_date: str) -> List[OHLCVBar]:
        """Fetch stock/ETF OHLCV data via yfinance for an arbitrary date range."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed — falling back to empty data for %s", symbol)
            return []

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start_date, end=end_date, interval="1d")
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

    def _fetch_crypto(self, symbol: str, start_date: str, end_date: str) -> List[OHLCVBar]:
        """Fetch crypto OHLCV data via CoinGecko free API for an arbitrary date range.

        Uses the ``/coins/{id}/market_chart/range`` endpoint with Unix timestamps
        so that historical windows (e.g. 2021-2024) work correctly, unlike the
        ``/ohlc`` endpoint which only returns the most recent N days.
        """
        coin_id = _COINGECKO_IDS.get(symbol.upper())
        if not coin_id:
            logger.warning("Unknown crypto symbol %s — no CoinGecko mapping", symbol)
            return []

        try:
            start_dt = date.fromisoformat(start_date)
            end_dt = date.fromisoformat(end_date)
        except ValueError:
            logger.error("Invalid date range for crypto fetch: %s - %s", start_date, end_date)
            return []

        # Convert to Unix timestamps (start of day UTC)
        import calendar
        from datetime import datetime, timezone

        start_ts = int(
            calendar.timegm(
                datetime(
                    start_dt.year, start_dt.month, start_dt.day, tzinfo=timezone.utc
                ).timetuple()
            )
        )
        end_ts = int(
            calendar.timegm(
                datetime(
                    end_dt.year, end_dt.month, end_dt.day, 23, 59, 59, tzinfo=timezone.utc
                ).timetuple()
            )
        )

        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range"
        params = {"vs_currency": "usd", "from": str(start_ts), "to": str(end_ts)}

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                raw = resp.json()
        except Exception as exc:
            logger.error("CoinGecko fetch failed for %s: %s", symbol, exc)
            return []

        if not isinstance(raw, dict) or "prices" not in raw:
            logger.warning("Unexpected CoinGecko response for %s", symbol)
            return []

        # market_chart/range returns {prices: [[ts, price], ...], ...}
        # Group by date to build daily OHLCV bars from the price points
        daily: Dict[str, List[float]] = {}
        for ts_ms, price in raw.get("prices", []):
            bar_date = date.fromtimestamp(ts_ms / 1000).isoformat()
            daily.setdefault(bar_date, []).append(float(price))

        bars: List[OHLCVBar] = []
        for bar_date in sorted(daily):
            prices = daily[bar_date]
            bars.append(
                OHLCVBar(
                    date=bar_date,
                    open=round(prices[0], 4),
                    high=round(max(prices), 4),
                    low=round(min(prices), 4),
                    close=round(prices[-1], 4),
                    volume=0.0,  # market_chart/range doesn't provide volume per bar
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
        """Fetch OHLCV data for multiple symbols (recent N days)."""
        result: Dict[str, List[OHLCVBar]] = {}
        for sym in symbols:
            bars = self.fetch_ohlcv(sym, asset_class, days)
            if bars:
                result[sym] = bars
        return result

    def fetch_multi_symbol_range(
        self, symbols: List[str], asset_class: str, start_date: str, end_date: str
    ) -> Dict[str, List[OHLCVBar]]:
        """Fetch OHLCV data for multiple symbols over an explicit date range."""
        result: Dict[str, List[OHLCVBar]] = {}
        for sym in symbols:
            bars = self.fetch_ohlcv_range(sym, asset_class, start_date, end_date)
            if bars:
                result[sym] = bars
        return result
