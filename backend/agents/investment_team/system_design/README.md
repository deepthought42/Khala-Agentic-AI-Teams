# Investment Team — System Design Docs

This folder documents the Investment Team's internal architecture at a level
intended for engineers extending the team. For the end-user/API facing
overview, see [`../README.md`](../README.md); for the architectural issues
backlog and review notes, see [`../ARCHITECTURE_REVIEW.md`](../ARCHITECTURE_REVIEW.md).

## Two tracks

The Investment Team mounts two logical workflows behind a single HTTP
surface at `/api/investment`:

| Track | Entry point | Requires `InvestmentProfile` (IPS)? |
|---|---|---|
| **Advisor** | `POST /advisor/sessions`, `POST /profiles`, `POST /proposals/...` | Yes |
| **Strategy Lab** | `POST /strategy-lab/run` | No |

These docs focus on the Strategy Lab track, where most of the recent
changes live.

## Pipeline shape

The per-cycle pipeline is:

```
ideating → fetching_data → analyzing → (paper_trading?) → complete
```

Paper trading is gated on the backtest's winner flag
(`annualized_return_pct > 8.0`). Losing strategies skip paper trading
entirely so they never consume paper-trade LLM budget.

See:

- [`strategy_lab_pipeline.md`](./strategy_lab_pipeline.md) — full pipeline
  with phase events, winner gate, and skip paths.
- [`paper_trading_integration.md`](./paper_trading_integration.md) —
  paper-trading step semantics, configuration, failure contract.
- [`trade_record_schema.md`](./trade_record_schema.md) — every
  `TradeRecord` field (including the new bid / fill / order_type
  execution detail).

## Key modules

| Module | Role |
|---|---|
| `api/main.py` | FastAPI endpoints, pipeline orchestration, persistence |
| `models.py` | Pydantic models (`StrategySpec`, `BacktestRecord`, `StrategyLabRecord`, `PaperTradingSession`, `TradeRecord`, …) |
| `trade_simulator.py` | `TradeSimulationEngine` shared by backtest and paper trading |
| `backtesting_agent.py` | Thin wrapper that pairs an LLM bar-evaluator with the simulation engine |
| `paper_trading_agent.py` | Paper-trading wrapper: runs the engine, compares vs backtest, computes verdict and divergence analysis |
| `strategy_ideation_agent.py` | LLM-driven strategy ideation + post-backtest narrative |
| `market_data_service.py` | Multi-provider OHLCV fetcher (Yahoo → Twelve Data → Alpha Vantage/CoinGecko) |

## Persistence

All strategy-lab artifacts are persisted via `_PersistentDict`
(JobServiceClient-backed) so they survive restarts. See
[`../README.md`](../README.md) for the list of entity types and job team
names.
