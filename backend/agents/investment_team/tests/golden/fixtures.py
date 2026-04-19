"""Deterministic synthetic OHLCV fixtures for golden-dataset tests.

The goal is to exercise the engine without hitting network data providers, and
to make metric snapshots reproducible byte-for-byte across CI runs.  Two price
regimes are composed:

* A sinusoidal trend ``A * sin(2 * pi * i / period)`` around a base price,
  which generates repeatable crossover signals for SMA-style strategies.
* A seeded additive noise term and a deterministic jump schedule, which keeps
  volatility non-trivial without introducing RNG state that depends on the
  Python or NumPy version.

The fixtures deliberately stay small (one year of daily bars for two symbols
is enough to produce a handful of round-trip trades through the subprocess
harness) so the test suite finishes in a few seconds on CI.  Larger
configurations are available via the ``n_days`` / ``symbols`` parameters for
ad-hoc runs.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Dict, List

from investment_team.market_data_service import OHLCVBar

DEFAULT_START = date(2024, 1, 1)
DEFAULT_DAYS = 252  # ~ one trading-day year of weekday bars

# Deterministic per-symbol parameters.  Kept in a module constant so the same
# fixtures can be reproduced by unrelated callers (e.g. a future ``execution``
# stress test) without importing this module's generator.
SYMBOL_PARAMS: Dict[str, Dict[str, float]] = {
    "AAA": {"base": 100.0, "amplitude": 8.0, "period": 40.0, "drift": 0.02},
    "BBB": {"base": 50.0, "amplitude": 3.0, "period": 25.0, "drift": -0.01},
}


def _weekday_dates(start: date, n: int) -> List[date]:
    out: List[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _pseudo_noise(i: int, seed: int) -> float:
    """Lightweight deterministic noise in [-1, 1).

    A purpose-built linear-congruential mapping from ``(i, seed)`` to a float.
    We avoid ``random.Random`` / NumPy so the fixture bytes are portable
    across Python minor versions.
    """
    x = (i * 1103515245 + seed * 12345 + 1) & 0x7FFFFFFF
    return (x / 0x7FFFFFFF) * 2.0 - 1.0


def _jump(i: int, period: int) -> float:
    """Periodic price jump: ``+2%`` every ``period`` bars, ``-2%`` at the midpoint."""
    if i % period == 0 and i > 0:
        return 1.02
    if i % period == period // 2 and i > 0:
        return 0.98
    return 1.0


def generate_ohlcv(
    symbol: str,
    *,
    n_days: int = DEFAULT_DAYS,
    start: date = DEFAULT_START,
    seed: int = 42,
) -> List[OHLCVBar]:
    """Return ``n_days`` of deterministic daily ``OHLCVBar``s for ``symbol``.

    Unknown symbols are synthesized using a stable hash of the symbol name as
    the parameter seed so callers can extend the fixture pool without editing
    this module.
    """
    params = SYMBOL_PARAMS.get(
        symbol,
        {
            "base": 100.0 + (hash(symbol) & 0xFF) * 0.5,
            "amplitude": 5.0,
            "period": 30.0 + (hash(symbol) & 0x7),
            "drift": 0.0,
        },
    )
    base = float(params["base"])
    amp = float(params["amplitude"])
    period = float(params["period"])
    drift = float(params["drift"])

    dates = _weekday_dates(start, n_days)
    bars: List[OHLCVBar] = []
    for i, d in enumerate(dates):
        trend = base * (1.0 + drift * (i / n_days))
        cycle = amp * math.sin(2.0 * math.pi * i / period)
        noise = amp * 0.15 * _pseudo_noise(i, seed)
        close = trend + cycle + noise
        close *= _jump(i, int(period))
        # Construct a realistic-looking OHLC envelope around the close.
        hi_lo_spread = amp * 0.12 + abs(noise) * 0.3
        open_ = close - 0.4 * cycle * 0.1 + 0.2 * _pseudo_noise(i + 1, seed)
        high = max(open_, close) + hi_lo_spread * (0.5 + 0.5 * _pseudo_noise(i + 2, seed) ** 2)
        low = min(open_, close) - hi_lo_spread * (0.5 + 0.5 * _pseudo_noise(i + 3, seed) ** 2)
        volume = 1_000_000.0 + 50_000.0 * _pseudo_noise(i + 4, seed)
        bars.append(
            OHLCVBar(
                date=d.isoformat(),
                open=round(float(open_), 4),
                high=round(float(high), 4),
                low=round(float(low), 4),
                close=round(float(close), 4),
                volume=round(float(max(0.0, volume)), 4),
            )
        )
    return bars


def golden_market_data(
    symbols: List[str] | None = None,
    *,
    n_days: int = DEFAULT_DAYS,
) -> Dict[str, List[OHLCVBar]]:
    """Return a ``{symbol: [OHLCVBar]}`` dict suitable for ``run_backtest``."""
    if symbols is None:
        symbols = list(SYMBOL_PARAMS.keys())
    return {s: generate_ohlcv(s, n_days=n_days) for s in symbols}
