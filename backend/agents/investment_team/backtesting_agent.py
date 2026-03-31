"""
Backtesting Agent — runs historical backtests using real market data and LLM-driven trade decisions.

Fetches real OHLCV data for the backtest period, walks through bars chronologically,
uses the LLM to interpret the strategy's entry/exit rules, and simulates trade execution
with realistic slippage and transaction costs.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from llm_service.interface import LLMClient

from .market_data_service import OHLCVBar
from .models import (
    BacktestConfig,
    BacktestResult,
    StrategySpec,
    TradeRecord,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_EVALUATE_SYSTEM = (
    "You are an expert quantitative trader backtesting a swing trading strategy against historical data. "
    "You evaluate daily price bars against the strategy's entry and exit rules to decide whether to trade. "
    "Be disciplined — only trade when the rules are clearly met by the price data. "
    "Remember: this is a backtest, so you must only use information available on the current bar's date."
)

_EVALUATE_PROMPT = """\
Evaluate whether the trading strategy's rules are triggered for this historical market data.

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
Do NOT use any future information — only data up to and including the current bar.

Return ONLY a JSON object with no markdown:
{{"action": "enter_long" or "enter_short" or "exit" or "hold", "confidence": 0.0 to 1.0, \
"shares": number_of_shares_or_0, "reasoning": "brief explanation"}}

For "hold", set shares to 0. For entries, calculate shares based on sizing rules and available capital.
For exits, set shares to 0 (will close full position).
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


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class BacktestingAgent:
    """
    Runs backtests against real historical market data by walking through OHLCV bars
    chronologically and using the LLM to interpret strategy entry/exit rules.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    def run_backtest(
        self,
        strategy: StrategySpec,
        config: BacktestConfig,
        market_data: Dict[str, List[OHLCVBar]],
    ) -> tuple[BacktestResult, List[TradeRecord]]:
        """
        Walk through historical market data bar-by-bar, making LLM-driven trade decisions.

        Returns (BacktestResult, trade_ledger).
        """
        capital = config.initial_capital
        cost_pct = config.transaction_cost_bps / 10_000.0
        slippage_bps = config.slippage_bps

        # Build a unified timeline: merge all symbols' bars sorted by date
        timeline: List[tuple[str, str, OHLCVBar]] = []
        for symbol, bars in market_data.items():
            for bar in bars:
                timeline.append((bar.date, symbol, bar))
        timeline.sort(key=lambda x: x[0])

        # Per-symbol bar history for context lookups
        symbol_history: Dict[str, List[OHLCVBar]] = {sym: [] for sym in market_data}

        open_positions: Dict[str, Dict[str, Any]] = {}
        trades: List[TradeRecord] = []
        trade_num = 0
        cumulative_pnl = 0.0

        for bar_date, symbol, bar in timeline:
            symbol_history[symbol].append(bar)
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
                continue

            action = decision.get("action", "hold")

            if action in ("enter_long", "enter_short") and not has_position:
                shares = float(decision.get("shares", 0))
                if shares <= 0:
                    position_pct = 0.06
                    shares = round(capital * position_pct / bar.close, 4 if bar.close < 10 else 2)

                if shares > 0 and capital >= shares * bar.close:
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

        # Force-close any remaining positions on the last available bar
        for symbol, pos in list(open_positions.items()):
            if symbol in symbol_history and symbol_history[symbol]:
                last_bar = symbol_history[symbol][-1]
                trade_num += 1
                exit_price = round(
                    last_bar.close * (1.0 - slippage_bps / 10_000.0),
                    4 if last_bar.close < 10 else 2,
                )
                gross_pnl = round(pos["shares"] * (exit_price - pos["entry_price"]), 2)
                if pos["side"] == "short":
                    gross_pnl = -gross_pnl
                tx_cost = round(pos["position_value"] * cost_pct * 2, 2)
                net_pnl = round(gross_pnl - tx_cost, 2)
                cumulative_pnl = round(cumulative_pnl + net_pnl, 2)
                return_pct = round((exit_price - pos["entry_price"]) / pos["entry_price"] * 100, 3)
                if pos["side"] == "short":
                    return_pct = -return_pct
                hold_days = self._date_diff_days(pos["entry_date"], last_bar.date)

                trades.append(
                    TradeRecord(
                        trade_num=trade_num,
                        entry_date=pos["entry_date"],
                        exit_date=last_bar.date,
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

        result = self._compute_metrics(
            trades, config.initial_capital, config.start_date, config.end_date
        )
        return result, trades

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
    def _compute_metrics(
        trades: List[TradeRecord],
        initial_capital: float,
        start_date: str,
        end_date: str,
    ) -> BacktestResult:
        """Compute aggregate performance metrics from completed backtest trades."""
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

        # Annualize based on the backtest period
        total_days = BacktestingAgent._date_diff_days(start_date, end_date)
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

        # Volatility of per-trade returns
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
    def _date_diff_days(d1: str, d2: str) -> int:
        """Compute days between two ISO date strings."""
        try:
            from datetime import date as date_cls

            dt1 = date_cls.fromisoformat(d1[:10])
            dt2 = date_cls.fromisoformat(d2[:10])
            return max(1, abs((dt2 - dt1).days))
        except (ValueError, TypeError):
            return 1
