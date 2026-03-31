"""
Paper Trading Agent — runs simulated live trading using LLM to interpret strategy rules against real market data.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from llm_service.interface import LLMClient

from .market_data_service import OHLCVBar
from .models import (
    BacktestRecord,
    BacktestResult,
    PaperTradingComparison,
    PaperTradingSession,
    PaperTradingStatus,
    PaperTradingVerdict,
    StrategySpec,
    TradeRecord,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_EVALUATE_SYSTEM = (
    "You are an expert quantitative trader executing a swing trading strategy. "
    "You evaluate daily price bars against the strategy's entry and exit rules to decide whether to trade. "
    "Be disciplined — only trade when the rules are clearly met by the price data."
)

_EVALUATE_PROMPT = """\
Evaluate whether the trading strategy's rules are triggered for this market data.

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

Return ONLY a JSON object with no markdown:
{{"action": "enter_long" or "enter_short" or "exit" or "hold", "confidence": 0.0 to 1.0, \
"shares": number_of_shares_or_0, "reasoning": "brief explanation"}}

For "hold", set shares to 0. For entries, calculate shares based on sizing rules and available capital.
For exits, set shares to 0 (will close full position).
"""

_DIVERGENCE_SYSTEM = (
    "You are a quantitative trading analyst specializing in strategy validation. "
    "You compare paper trading results against backtesting results to identify "
    "why live-data performance diverges from historical simulations."
)

_DIVERGENCE_PROMPT = """\
Analyze why this strategy's paper trading performance diverges from its backtest results.

## Strategy
Asset class: {asset_class}
Hypothesis: {hypothesis}
Signal: {signal_definition}
Entry rules: {entry_rules}
Exit rules: {exit_rules}

## Backtest Results (historical simulation)
Period: {bt_start} to {bt_end}
Annualized return: {bt_annual_return:.1f}%
Win rate: {bt_win_rate:.1f}%
Sharpe ratio: {bt_sharpe:.2f}
Max drawdown: {bt_max_dd:.1f}%
Profit factor: {bt_profit_factor:.2f}
Total trades: {bt_trade_count}

## Paper Trading Results (real market data)
Period: {pt_start} to {pt_end}
Annualized return: {pt_annual_return:.1f}%
Win rate: {pt_win_rate:.1f}%
Sharpe ratio: {pt_sharpe:.2f}
Max drawdown: {pt_max_dd:.1f}%
Profit factor: {pt_profit_factor:.2f}
Total trades: {pt_trade_count}

## Backtest Trade Sample (first 10 trades)
{bt_trades_text}

## Paper Trading Trades (first 20 trades)
{pt_trades_text}

## Instructions
Write a thorough analysis covering:
1. **Metric Divergence**: Which metrics diverged most and by how much
2. **Trade Pattern Analysis**: Compare entry/exit patterns between backtest and paper trading
3. **Root Cause Hypotheses**: Why paper trading underperforms (overfitting, regime change, \
lookahead bias, market microstructure, data quality differences, etc.)
4. **Actionable Improvements**: Specific changes to strategy rules, signals, or risk management \
that could improve future live-data performance

Return ONLY a JSON object with no markdown:
{{"analysis": "your full analysis here"}}
"""


def _format_bars_table(bars: List[OHLCVBar]) -> str:
    """Format a list of OHLCV bars as a compact text table."""
    if not bars:
        return "No data available."
    lines = ["Date       | Open     | High     | Low      | Close    | Volume"]
    for b in bars:
        lines.append(
            f"{b.date} | {b.open:<8.2f} | {b.high:<8.2f} | {b.low:<8.2f} | {b.close:<8.2f} | {b.volume:.0f}"
        )
    return "\n".join(lines)


def _format_trades_table(trades: List[TradeRecord]) -> str:
    """Format trade records as a compact text table."""
    if not trades:
        return "No trades."
    lines = [
        "# | Symbol | Side | Entry Date | Exit Date  | Entry$   | Exit$    | Return%  | Outcome"
    ]
    for t in trades:
        lines.append(
            f"{t.trade_num} | {t.symbol} | {t.side} | {t.entry_date} | {t.exit_date} | "
            f"{t.entry_price:<8.2f} | {t.exit_price:<8.2f} | {t.return_pct:+.2f}% | {t.outcome}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class PaperTradingAgent:
    """
    Runs paper trading sessions by walking through real market data bar-by-bar,
    using the LLM to interpret strategy entry/exit rules, and simulating trade execution.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    def run_session(
        self,
        strategy: StrategySpec,
        backtest_record: BacktestRecord,
        market_data: Dict[str, List[OHLCVBar]],
        initial_capital: float = 100_000.0,
        transaction_cost_bps: float = 5.0,
        slippage_bps: float = 2.0,
        min_trades: int = 50,
    ) -> PaperTradingSession:
        """Walk through market data bar-by-bar, making LLM-driven trade decisions."""
        session_id = f"pt-{uuid.uuid4().hex[:8]}"
        now = datetime.now(tz=timezone.utc).isoformat()

        # Determine data period
        all_dates: List[str] = []
        for bars in market_data.values():
            all_dates.extend(b.date for b in bars)
        all_dates.sort()
        data_start = all_dates[0] if all_dates else ""
        data_end = all_dates[-1] if all_dates else ""

        # Determine data source from asset class
        asset = strategy.asset_class.lower()
        data_source = "coingecko" if asset == "crypto" else "yahoo_finance"

        session = PaperTradingSession(
            session_id=session_id,
            lab_record_id="",  # set by caller
            strategy=strategy,
            status=PaperTradingStatus.RUNNING,
            initial_capital=initial_capital,
            current_capital=initial_capital,
            symbols_traded=list(market_data.keys()),
            data_source=data_source,
            data_period_start=data_start,
            data_period_end=data_end,
            started_at=now,
        )

        # Build a unified timeline: merge all symbols' bars sorted by date
        timeline: List[tuple[str, str, OHLCVBar]] = []  # (date, symbol, bar)
        for symbol, bars in market_data.items():
            for bar in bars:
                timeline.append((bar.date, symbol, bar))
        timeline.sort(key=lambda x: x[0])

        # Build per-symbol bar history for context lookups
        symbol_history: Dict[str, List[OHLCVBar]] = {sym: [] for sym in market_data}

        capital = initial_capital
        open_positions: Dict[str, Dict[str, Any]] = {}  # symbol -> position info
        trades: List[TradeRecord] = []
        decisions: List[Dict[str, Any]] = []
        cost_pct = (transaction_cost_bps + slippage_bps) / 10_000.0
        trade_num = 0
        cumulative_pnl = 0.0

        for bar_date, symbol, bar in timeline:
            symbol_history[symbol].append(bar)

            # Provide last 20 bars as context
            recent = symbol_history[symbol][-20:]
            has_position = symbol in open_positions

            # Ask LLM to evaluate this bar
            try:
                decision = self._evaluate_bar(
                    strategy=strategy,
                    symbol=symbol,
                    current_bar=bar,
                    recent_bars=recent,
                    open_position=open_positions.get(symbol),
                    capital=capital,
                )
            except Exception as exc:
                logger.warning("LLM evaluation failed for %s on %s: %s", symbol, bar_date, exc)
                decision = {
                    "action": "hold",
                    "confidence": 0.0,
                    "shares": 0,
                    "reasoning": f"LLM error: {exc}",
                }

            decisions.append({"date": bar_date, "symbol": symbol, **decision})
            action = decision.get("action", "hold")

            if action in ("enter_long", "enter_short") and not has_position:
                shares = float(decision.get("shares", 0))
                if shares <= 0:
                    # Default position sizing: 5-8% of capital
                    position_pct = 0.06
                    shares = round(capital * position_pct / bar.close, 4 if bar.close < 10 else 2)

                if shares > 0 and capital >= shares * bar.close:
                    # Apply slippage to entry: buy at slightly higher price
                    slippage_mult = 1.0 + slippage_bps / 10_000.0
                    entry_price = round(bar.close * slippage_mult, 4 if bar.close < 10 else 2)
                    position_value = round(entry_price * shares, 2)
                    capital -= position_value

                    open_positions[symbol] = {
                        "side": "long" if action == "enter_long" else "short",
                        "entry_date": bar_date,
                        "entry_price": entry_price,
                        "shares": shares,
                        "position_value": position_value,
                    }

            elif action == "exit" and has_position:
                pos = open_positions.pop(symbol)
                trade_num += 1

                # Apply slippage to exit: sell at slightly lower price
                slippage_mult = 1.0 - slippage_bps / 10_000.0
                exit_price = round(bar.close * slippage_mult, 4 if bar.close < 10 else 2)

                gross_pnl = round(pos["shares"] * (exit_price - pos["entry_price"]), 2)
                if pos["side"] == "short":
                    gross_pnl = -gross_pnl

                tx_cost = round(pos["position_value"] * cost_pct * 2, 2)
                net_pnl = round(gross_pnl - tx_cost, 2)
                cumulative_pnl = round(cumulative_pnl + net_pnl, 2)
                return_pct = round((exit_price - pos["entry_price"]) / pos["entry_price"] * 100, 3)
                if pos["side"] == "short":
                    return_pct = -return_pct

                hold_days = self._date_diff_days(pos["entry_date"], bar_date)

                capital += round(pos["shares"] * exit_price, 2)

                trades.append(
                    TradeRecord(
                        trade_num=trade_num,
                        entry_date=pos["entry_date"],
                        exit_date=bar_date,
                        symbol=symbol,
                        side=pos["side"],
                        entry_price=pos["entry_price"],
                        exit_price=exit_price,
                        shares=pos["shares"],
                        position_value=pos["position_value"],
                        gross_pnl=gross_pnl,
                        net_pnl=net_pnl,
                        return_pct=return_pct,
                        hold_days=hold_days,
                        outcome="win" if net_pnl > 0 else "loss",
                        cumulative_pnl=cumulative_pnl,
                    )
                )

            if len(trades) >= min_trades:
                break

        # Compute session metrics
        session.trades = trades
        session.trade_decisions = decisions
        session.current_capital = capital
        session.completed_at = datetime.now(tz=timezone.utc).isoformat()

        if trades:
            session.result = self._compute_session_metrics(trades, initial_capital)
            session.comparison = self.compare_performance(session.result, backtest_record.result)

            if session.comparison.overall_aligned:
                session.verdict = PaperTradingVerdict.READY_FOR_LIVE
            else:
                session.verdict = PaperTradingVerdict.NOT_PERFORMANT
                try:
                    session.divergence_analysis = self.analyze_divergence(session, backtest_record)
                except Exception as exc:
                    logger.warning("Divergence analysis failed: %s", exc)
                    session.divergence_analysis = (
                        f"Paper trading did not align with backtest expectations. "
                        f"Paper win rate: {session.result.win_rate_pct:.1f}% vs "
                        f"backtest: {backtest_record.result.win_rate_pct:.1f}%. "
                        f"Automated analysis unavailable."
                    )

        session.status = PaperTradingStatus.COMPLETED
        return session

    def _evaluate_bar(
        self,
        strategy: StrategySpec,
        symbol: str,
        current_bar: OHLCVBar,
        recent_bars: List[OHLCVBar],
        open_position: Optional[Dict[str, Any]],
        capital: float,
    ) -> Dict[str, Any]:
        """Ask LLM to evaluate whether entry/exit rules are met for this bar."""
        if open_position:
            pos_status = (
                f"OPEN {open_position['side'].upper()} position in {symbol}: "
                f"{open_position['shares']} shares @ ${open_position['entry_price']:.2f} "
                f"(entered {open_position['entry_date']})"
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
            recent_bars_text=_format_bars_table(recent_bars),
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

    @staticmethod
    def _compute_session_metrics(
        trades: List[TradeRecord], initial_capital: float
    ) -> BacktestResult:
        """Compute aggregate performance metrics from completed paper trades."""
        if not trades:
            return BacktestResult(
                total_return_pct=0.0,
                annualized_return_pct=0.0,
                volatility_pct=0.0,
                sharpe_ratio=0.0,
                max_drawdown_pct=0.0,
                win_rate_pct=0.0,
                profit_factor=0.0,
            )

        wins = [t for t in trades if t.outcome == "win"]
        losses = [t for t in trades if t.outcome == "loss"]

        total_pnl = sum(t.net_pnl for t in trades)
        total_return_pct = round(total_pnl / initial_capital * 100, 2)

        # Estimate annualized return from total days spanned
        first_date = trades[0].entry_date
        last_date = trades[-1].exit_date
        total_days = PaperTradingAgent._date_diff_days(first_date, last_date)
        years = max(total_days / 365.25, 0.01)
        annualized_return = round(total_return_pct / years, 2)

        # Win rate
        win_rate = round(len(wins) / len(trades) * 100, 2) if trades else 0.0

        # Profit factor
        gross_wins = sum(t.gross_pnl for t in wins) if wins else 0.0
        gross_losses = abs(sum(t.gross_pnl for t in losses)) if losses else 0.0
        profit_factor = (
            round(gross_wins / gross_losses, 2)
            if gross_losses > 0
            else round(max(gross_wins, 0.0), 2)
        )

        # Volatility of returns
        returns = [t.return_pct for t in trades]
        if len(returns) > 1:
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
            daily_vol = math.sqrt(variance)
            annualized_vol = round(
                daily_vol * math.sqrt(252 / max(years * 252 / len(trades), 1)), 2
            )
        else:
            annualized_vol = 0.0

        # Sharpe ratio
        sharpe = round(annualized_return / annualized_vol, 2) if annualized_vol > 0 else 0.0

        # Max drawdown
        peak = initial_capital
        max_dd = 0.0
        equity = initial_capital
        for t in trades:
            equity += t.net_pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        return BacktestResult(
            total_return_pct=total_return_pct,
            annualized_return_pct=annualized_return,
            volatility_pct=annualized_vol,
            sharpe_ratio=sharpe,
            max_drawdown_pct=round(max_dd, 2),
            win_rate_pct=win_rate,
            profit_factor=profit_factor,
        )

    @staticmethod
    def compare_performance(
        paper_result: BacktestResult,
        backtest_result: BacktestResult,
    ) -> PaperTradingComparison:
        """Compare paper trading metrics against backtest expectations with tolerances."""
        # Win rate: within ±10 percentage points
        win_rate_aligned = abs(paper_result.win_rate_pct - backtest_result.win_rate_pct) <= 10.0

        # Annualized return: within ±40% relative (or ±3pp absolute for small values)
        bt_ret = backtest_result.annualized_return_pct
        pt_ret = paper_result.annualized_return_pct
        if abs(bt_ret) > 5.0:
            return_aligned = abs(pt_ret - bt_ret) / abs(bt_ret) <= 0.40
        else:
            return_aligned = abs(pt_ret - bt_ret) <= 3.0

        # Sharpe: within ±0.3
        sharpe_aligned = abs(paper_result.sharpe_ratio - backtest_result.sharpe_ratio) <= 0.3

        # Max drawdown: paper drawdown no more than 1.5x backtest drawdown
        if backtest_result.max_drawdown_pct > 0:
            drawdown_aligned = (
                paper_result.max_drawdown_pct <= backtest_result.max_drawdown_pct * 1.5
            )
        else:
            drawdown_aligned = paper_result.max_drawdown_pct <= 5.0

        overall = win_rate_aligned and return_aligned and sharpe_aligned and drawdown_aligned

        return PaperTradingComparison(
            backtest_win_rate_pct=backtest_result.win_rate_pct,
            paper_win_rate_pct=paper_result.win_rate_pct,
            backtest_annualized_return_pct=backtest_result.annualized_return_pct,
            paper_annualized_return_pct=paper_result.annualized_return_pct,
            backtest_sharpe_ratio=backtest_result.sharpe_ratio,
            paper_sharpe_ratio=paper_result.sharpe_ratio,
            backtest_max_drawdown_pct=backtest_result.max_drawdown_pct,
            paper_max_drawdown_pct=paper_result.max_drawdown_pct,
            backtest_profit_factor=backtest_result.profit_factor,
            paper_profit_factor=paper_result.profit_factor,
            win_rate_aligned=win_rate_aligned,
            return_aligned=return_aligned,
            sharpe_aligned=sharpe_aligned,
            drawdown_aligned=drawdown_aligned,
            overall_aligned=overall,
        )

    def analyze_divergence(
        self,
        session: PaperTradingSession,
        backtest_record: BacktestRecord,
    ) -> str:
        """LLM-driven analysis of why paper trading diverges from backtest results."""
        strategy = session.strategy
        bt = backtest_record.result
        pt = session.result

        if pt is None:
            return "No paper trading results available for analysis."

        bt_trades_sample = backtest_record.trades[:10]
        pt_trades_sample = session.trades[:20]

        prompt = _DIVERGENCE_PROMPT.format(
            asset_class=strategy.asset_class,
            hypothesis=strategy.hypothesis,
            signal_definition=strategy.signal_definition,
            entry_rules="; ".join(strategy.entry_rules),
            exit_rules="; ".join(strategy.exit_rules),
            bt_start=backtest_record.config.start_date,
            bt_end=backtest_record.config.end_date,
            bt_annual_return=bt.annualized_return_pct,
            bt_win_rate=bt.win_rate_pct,
            bt_sharpe=bt.sharpe_ratio,
            bt_max_dd=bt.max_drawdown_pct,
            bt_profit_factor=bt.profit_factor,
            bt_trade_count=len(backtest_record.trades),
            pt_start=session.data_period_start,
            pt_end=session.data_period_end,
            pt_annual_return=pt.annualized_return_pct,
            pt_win_rate=pt.win_rate_pct,
            pt_sharpe=pt.sharpe_ratio,
            pt_max_dd=pt.max_drawdown_pct,
            pt_profit_factor=pt.profit_factor,
            pt_trade_count=len(session.trades),
            bt_trades_text=_format_trades_table(bt_trades_sample),
            pt_trades_text=_format_trades_table(pt_trades_sample),
        )

        data = self.llm.complete_json(
            prompt,
            temperature=0.3,
            system_prompt=_DIVERGENCE_SYSTEM,
            think=True,
        )
        return str(data.get("analysis", "Divergence analysis not available."))

    @staticmethod
    def _date_diff_days(d1: str, d2: str) -> int:
        """Compute days between two ISO date strings."""
        try:
            from datetime import date as date_cls

            dt1 = date_cls.fromisoformat(d1[:10])
            dt2 = date_cls.fromisoformat(d2[:10])
            return max(1, abs((dt2 - dt1).days))
        except (ValueError, TypeError):
            return 1
