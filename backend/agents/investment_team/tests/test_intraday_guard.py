"""Phase 5 (partial) regression tests.

Covers:

* ``BacktestConfig.intraday_mode`` field (default False).
* ``check_intraday_data_source`` — raises ``IntradayDataError`` when an
  intraday run used CoinGecko bars; silent no-op otherwise.
* ``MarketDataService.fetch_multi_symbol_range(..., intraday_mode=True)``
  — end-to-end: records provider_used per symbol and fails when a CoinGecko
  fallback is the winning provider.
"""

from __future__ import annotations

from typing import List

import pytest

from investment_team.execution.intraday_guard import (
    IntradayDataError,
    check_intraday_data_source,
)
from investment_team.market_data_service import MarketDataService, OHLCVBar
from investment_team.models import BacktestConfig

# ---------------------------------------------------------------------------
# BacktestConfig flag
# ---------------------------------------------------------------------------


def test_backtest_config_defaults_intraday_mode_to_false() -> None:
    cfg = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31")
    assert cfg.intraday_mode is False


def test_backtest_config_accepts_intraday_mode() -> None:
    cfg = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31", intraday_mode=True)
    assert cfg.intraday_mode is True


# ---------------------------------------------------------------------------
# check_intraday_data_source
# ---------------------------------------------------------------------------


def test_guard_is_noop_when_intraday_mode_is_false() -> None:
    # Even with a banned provider the guard must not fire when intraday is off.
    check_intraday_data_source(intraday_mode=False, provider_used={"BTC-USD": "coingecko"})


def test_guard_passes_when_provider_is_safe() -> None:
    check_intraday_data_source(
        intraday_mode=True, provider_used={"AAPL": "yahoo", "MSFT": "twelve_data"}
    )


def test_guard_raises_when_coingecko_is_the_source() -> None:
    with pytest.raises(IntradayDataError) as excinfo:
        check_intraday_data_source(
            intraday_mode=True,
            provider_used={"BTC-USD": "coingecko", "ETH-USD": "yahoo"},
        )
    assert excinfo.value.symbol == "BTC-USD"
    assert excinfo.value.provider == "coingecko"
    assert "intraday" in str(excinfo.value).lower()


def test_guard_ignores_empty_provider_map() -> None:
    # Nothing to inspect → no error.
    check_intraday_data_source(intraday_mode=True, provider_used={})


# ---------------------------------------------------------------------------
# MarketDataService integration
# ---------------------------------------------------------------------------


def _bars(n: int, price: float = 100.0) -> List[OHLCVBar]:
    return [
        OHLCVBar(
            date=f"2024-01-{i + 1:02d}",
            open=price,
            high=price + 1,
            low=price - 1,
            close=price,
            volume=1_000_000.0,
        )
        for i in range(n)
    ]


def test_market_data_service_records_provider_used(monkeypatch) -> None:
    """fetch_ohlcv_range must tag each symbol with the winning provider."""
    service = MarketDataService()

    # Force the yahoo provider to fail (return empty) and coingecko to
    # succeed — simulates a crypto symbol that only CoinGecko covered.
    def _fail(self, symbol, ac, start, end, max_retries=3):
        return []

    def _succeed(self, symbol, ac, start, end):
        return _bars(5)

    monkeypatch.setattr(MarketDataService, "_fetch_yahoo", _fail)
    monkeypatch.setattr(MarketDataService, "_fetch_twelve_data", _fail)
    monkeypatch.setattr(MarketDataService, "_fetch_coingecko", _succeed)

    bars = service.fetch_ohlcv_range("BTC-USD", "crypto", "2024-01-01", "2024-01-05")
    assert len(bars) == 5
    assert service.provider_used["BTC-USD"] == "coingecko"


def test_fetch_multi_symbol_range_intraday_mode_hard_fails_on_coingecko(monkeypatch) -> None:
    """Full integration: intraday_mode=True + CoinGecko fallback → IntradayDataError."""
    service = MarketDataService()

    def _fail(self, symbol, ac, start, end, max_retries=3):
        return []

    def _succeed(self, symbol, ac, start, end):
        return _bars(5)

    monkeypatch.setattr(MarketDataService, "_fetch_yahoo", _fail)
    monkeypatch.setattr(MarketDataService, "_fetch_twelve_data", _fail)
    monkeypatch.setattr(MarketDataService, "_fetch_coingecko", _succeed)

    with pytest.raises(IntradayDataError):
        service.fetch_multi_symbol_range(
            ["BTC-USD"], "crypto", "2024-01-01", "2024-01-05", intraday_mode=True
        )


def test_fetch_multi_symbol_range_daily_mode_allows_coingecko(monkeypatch) -> None:
    """Without intraday_mode, CoinGecko is fine — no error, data returned."""
    service = MarketDataService()

    def _fail(self, symbol, ac, start, end, max_retries=3):
        return []

    def _succeed(self, symbol, ac, start, end):
        return _bars(5)

    monkeypatch.setattr(MarketDataService, "_fetch_yahoo", _fail)
    monkeypatch.setattr(MarketDataService, "_fetch_twelve_data", _fail)
    monkeypatch.setattr(MarketDataService, "_fetch_coingecko", _succeed)

    result = service.fetch_multi_symbol_range(["BTC-USD"], "crypto", "2024-01-01", "2024-01-05")
    assert "BTC-USD" in result
    assert service.provider_used["BTC-USD"] == "coingecko"
