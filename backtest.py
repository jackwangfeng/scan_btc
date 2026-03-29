import os
import json
import sqlite3
import numpy as np
import aiohttp
import asyncio
from datetime import datetime, timedelta
from collections import deque
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("BACKTEST_DB_PATH", "data/klines.db")
PROXY_URL = os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")

RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
RSI_OVERBOUGHT = float(os.getenv("RSI_OVERBOUGHT", "80"))
RSI_OVERSOLD = float(os.getenv("RSI_OVERSOLD", "20"))
MACD_FAST = int(os.getenv("MACD_FAST", "12"))
MACD_SLOW = int(os.getenv("MACD_SLOW", "26"))
MACD_SIGNAL = int(os.getenv("MACD_SIGNAL", "9"))
BB_PERIOD = int(os.getenv("BB_PERIOD", "20"))
BB_STD = float(os.getenv("BB_STD", "2.0"))
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))
VOLUME_SPIKE_MULTIPLIER = float(os.getenv("VOLUME_SPIKE_MULTIPLIER", "5.0"))

INITIAL_CAPITAL = float(os.getenv("BACKTEST_INITIAL_CAPITAL", "10000"))
FEE_RATE = float(os.getenv("BACKTEST_FEE_RATE", "0.001"))

os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else "data", exist_ok=True)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS klines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, interval, timestamp)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol_interval ON klines(symbol, interval, timestamp)")
    conn.commit()
    conn.close()


def save_klines_to_db(symbol: str, interval: str, klines: List[Dict]):
    if not klines:
        return 0
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    count = 0
    for k in klines:
        cursor.execute("""
            INSERT OR REPLACE INTO klines (symbol, interval, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, interval, k["timestamp"], k["open"], k["high"], k["low"], k["close"], k["volume"]))
        count += 1
    conn.commit()
    conn.close()
    return count


def load_klines_from_db(symbol: str, interval: str, days: int = 90) -> Optional[List[Dict]]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT timestamp, open, high, low, close, volume
        FROM klines
        WHERE symbol = ? AND interval = ? AND timestamp >= ?
        ORDER BY timestamp ASC
    """, (symbol, interval, int((datetime.now() - timedelta(days=days)).timestamp() * 1000)))
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        return None
    return [
        {"timestamp": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
        for r in rows
    ]


def get_latest_timestamp(symbol: str, interval: str) -> Optional[int]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MAX(timestamp) FROM klines WHERE symbol = ? AND interval = ?
    """, (symbol, interval))
    result = cursor.fetchone()[0]
    conn.close()
    return result


def calculate_rsi(prices: np.ndarray, period: int = 14) -> float:
    if len(prices) <= period:
        return 50.0
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 100
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)
    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        up_val, down_val = (delta, 0.) if delta > 0 else (0., -delta)
        up = (up * (period - 1) + up_val) / period
        down = (down * (period - 1) + down_val) / period
        rs = up / down if down != 0 else 100
        rsi[i] = 100. - 100. / (1. + rs)
    return float(rsi[-1])


def calculate_ema(prices: np.ndarray, period: int) -> Optional[np.ndarray]:
    if len(prices) < period:
        return None
    ema = np.zeros_like(prices, dtype=float)
    ema[:period] = prices[:period]
    multiplier = 2 / (period + 1)
    for i in range(period, len(prices)):
        ema[i] = (prices[i] - ema[i-1]) * multiplier + ema[i-1]
    return ema


def calculate_macd(prices: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    if len(prices) < slow:
        return None, None, None
    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)
    if ema_fast is None or ema_slow is None:
        return None, None, None
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return float(macd_line[-1]), float(signal_line[-1]), float(histogram[-1])


def calculate_bollinger_bands(prices: np.ndarray, period: int = 20, std_dev: float = 2.0):
    if len(prices) < period:
        return None, None, None
    recent = prices[-period:]
    sma = float(np.mean(recent))
    std = float(np.std(recent))
    return sma + std_dev * std, sma, sma - std_dev * std


def calculate_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> Optional[float]:
    if len(highs) < period or len(lows) < period or len(closes) < period:
        return None
    tr = np.maximum(highs - lows,
                    np.maximum(np.abs(highs - np.roll(closes, 1)),
                               np.abs(lows - np.roll(closes, 1))))
    tr[0] = highs[0] - lows[0]
    return float(np.mean(tr))


async def fetch_klines_from_api(symbol: str, interval: str, days: int = 90) -> Optional[List[Dict]]:
    limit = min(days * 24 * 60, 1500) if interval == "1m" else min(days * 24, 1000)
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=PROXY_URL, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    data = await response.json()
                    klines = []
                    for k in data:
                        klines.append({
                            "timestamp": k[0],
                            "open": float(k[1]),
                            "high": float(k[2]),
                            "low": float(k[3]),
                            "close": float(k[4]),
                            "volume": float(k[5]),
                        })
                    return klines
    except Exception as e:
        print(f"API error: {e}")
    return None


class Backtester:
    def __init__(self, symbol: str, interval: str, days: int = 90):
        self.symbol = symbol
        self.interval = interval
        self.days = days
        self.klines: List[Dict] = []
        self.trades: List[Dict] = []
        self.position = 0
        self.capital = INITIAL_CAPITAL
        self.initial_capital = INITIAL_CAPITAL
        self.closes = deque(maxlen=500)
        self.volumes = deque(maxlen=500)
        self.highs = deque(maxlen=500)
        self.lows = deque(maxlen=500)

    def load_data(self) -> bool:
        print(f"📥 加载 {self.symbol} {self.interval} 近 {self.days} 天数据...")
        self.klines = load_klines_from_db(self.symbol, self.interval, self.days)
        if self.klines:
            print(f"✅ 从数据库加载 {len(self.klines)} 根K线")
            return True
        print("⚠️ 数据库无数据，尝试从 API 获取...")
        return False

    async def fetch_and_save_data(self):
        klines = await fetch_klines_from_api(self.symbol, self.interval, self.days)
        if klines:
            count = save_klines_to_db(self.symbol, self.interval, klines)
            print(f"✅ 从 API 获取 {len(klines)} 根K线，已存入数据库")
            self.klines = klines
            return True
        print("❌ 无法获取数据")
        return False

    def generate_signals(self) -> List[Dict]:
        if not self.klines:
            return []
        signals = []
        for i, k in enumerate(self.klines):
            self.closes.append(k["close"])
            self.volumes.append(k["volume"])
            self.highs.append(k["high"])
            self.lows.append(k["low"])
            if i < 60:
                continue
            closes_arr = np.array(list(self.closes))
            highs_arr = np.array(list(self.highs))
            lows_arr = np.array(list(self.lows))
            volumes_arr = np.array(list(self.volumes))
            rsi = calculate_rsi(closes_arr, RSI_PERIOD)
            macd, macd_sig, macd_hist = calculate_macd(closes_arr, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
            bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(closes_arr, BB_PERIOD, BB_STD)
            avg_vol = np.mean(volumes_arr[:-1]) if len(volumes_arr) > 1 else volumes_arr[-1]
            vol_ratio = k["volume"] / avg_vol if avg_vol > 0 else 1
            is_green = k["close"] > k["open"]
            current_price = k["close"]
            signal_type = None
            reason = ""

            macd_ok_for_buy = True
            macd_ok_for_sell = True
            stop_loss_triggered = False
            if self.position > 0 and position_entry_price > 0:
                loss_pct = (current_price - position_entry_price) / position_entry_price
                if loss_pct <= -0.03:
                    stop_loss_triggered = True

            if stop_loss_triggered:
                signal_type = "SELL"
                reason = "止损(-3%)"
            elif bb_lower and current_price <= bb_lower and rsi <= 45:
                signal_type = "BUY"
                reason = f"布林下轨+RSI({rsi:.1f})"
            elif bb_upper and current_price >= bb_upper and rsi >= 55:
                signal_type = "SELL"
                reason = f"布林上轨+RSI({rsi:.1f})"
            elif rsi <= RSI_OVERSOLD and vol_ratio >= 1.5 and is_green:
                signal_type = "BUY"
                reason = f"RSI超卖({rsi:.1f})+放量({vol_ratio:.1f}x)+阳线"
            elif rsi >= RSI_OVERBOUGHT and vol_ratio >= 1.5 and not is_green:
                signal_type = "SELL"
                reason = f"RSI超买({rsi:.1f})+放量({vol_ratio:.1f}x)+阴线"

            if signal_type:
                signals.append({
                    "time": datetime.fromtimestamp(k["timestamp"] / 1000),
                    "price": current_price,
                    "type": signal_type,
                    "reason": reason,
                    "rsi": rsi,
                    "macd_hist": macd_hist,
                })
        return signals

    def run(self, signals: List[Dict]) -> Dict:
        if not signals:
            return self._empty_result()
        self.trades = []
        self.position = 0
        self.capital = self.initial_capital
        position_entry_price = 0
        position_entry_cost = 0

        for sig in signals:
            if sig["type"] == "BUY" and self.position == 0:
                shares = self.capital / (sig["price"] * (1 + FEE_RATE))
                cost = shares * sig["price"] * (1 + FEE_RATE)
                self.position = shares
                position_entry_price = sig["price"]
                position_entry_cost = cost
                self.capital -= cost
                self.trades.append({
                    "action": "BUY",
                    "time": sig["time"],
                    "price": sig["price"],
                    "shares": shares,
                    "cost": cost,
                    "reason": sig["reason"],
                })
            elif sig["type"] == "SELL" and self.position > 0:
                proceeds = self.position * sig["price"] * (1 - FEE_RATE)
                net_pnl = proceeds - position_entry_cost
                self.capital += proceeds
                self.trades.append({
                    "action": "SELL",
                    "time": sig["time"],
                    "price": sig["price"],
                    "shares": self.position,
                    "proceeds": proceeds,
                    "cost": position_entry_cost,
                    "pnl": net_pnl,
                    "reason": sig["reason"],
                })
                self.position = 0

            elif sig["type"] == "BUY" and self.position > 0:
                loss_pct = (sig["price"] - position_entry_price) / position_entry_price
                if loss_pct <= -0.03:
                    proceeds = self.position * sig["price"] * (1 - FEE_RATE)
                    net_pnl = proceeds - position_entry_cost
                    self.capital += proceeds
                    self.trades.append({
                        "action": "SELL",
                        "time": sig["time"],
                        "price": sig["price"],
                        "shares": self.position,
                        "proceeds": proceeds,
                        "cost": position_entry_cost,
                        "pnl": net_pnl,
                        "reason": "止损(-3%)",
                    })
                    self.position = 0

        if self.position > 0 and self.klines:
            final_price = self.klines[-1]["close"]
            proceeds = self.position * final_price * (1 - FEE_RATE)
            net_pnl = proceeds - position_entry_cost
            self.trades.append({
                "action": "SELL",
                "time": datetime.fromtimestamp(self.klines[-1]["timestamp"] / 1000),
                "price": final_price,
                "shares": self.position,
                "proceeds": proceeds,
                "cost": position_entry_cost,
                "pnl": net_pnl,
                "reason": "回测结束，平仓",
            })
            self.capital += proceeds
            self.position = 0

        return self.calculate_metrics()

    def _empty_result(self) -> Dict:
        return {
            "symbol": self.symbol, "interval": self.interval, "days": self.days,
            "total_return": 0, "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
            "win_rate": 0, "profit_factor": 0, "max_drawdown": 0, "sharpe_ratio": 0,
            "initial_capital": self.initial_capital, "final_capital": self.initial_capital,
            "trades": [], "equity_curve": [],
        }

    def calculate_metrics(self) -> Dict:
        if not self.trades:
            return self._empty_result()
        equity_curve = []
        equity = self.initial_capital
        peak = equity
        max_dd = 0
        wins, losses = 0, 0
        total_win, total_loss = 0, 0
        returns = []

        for trade in self.trades:
            if trade["action"] == "BUY":
                equity -= trade.get("cost", 0)
            else:
                equity += trade["proceeds"]
                net_pnl = trade.get("pnl", 0)
                returns.append(net_pnl / self.initial_capital)
                if net_pnl > 0:
                    wins += 1
                    total_win += net_pnl
                else:
                    losses += 1
                    total_loss += abs(net_pnl)
            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
            equity_curve.append({"time": trade["time"], "equity": equity, "drawdown": dd * 100})

        total_return = (equity - self.initial_capital) / self.initial_capital * 100
        win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
        profit_factor = total_win / total_loss if total_loss > 0 else 0
        avg_return = np.mean(returns) if returns else 0
        std_return = np.std(returns) if len(returns) > 1 else 0
        sharpe = (avg_return / std_return * np.sqrt(252)) if std_return > 0 else 0

        return {
            "symbol": self.symbol, "interval": self.interval, "days": self.days,
            "total_return": total_return, "total_trades": wins + losses,
            "winning_trades": wins, "losing_trades": losses,
            "win_rate": win_rate, "profit_factor": profit_factor,
            "max_drawdown": max_dd * 100, "sharpe_ratio": sharpe,
            "initial_capital": self.initial_capital, "final_capital": equity,
            "trades": self.trades, "equity_curve": equity_curve,
        }

    def print_report(self, results: Dict):
        print("\n" + "=" * 60)
        print(f"📊 回测报告: {results['symbol']} ({results['interval']})")
        print("=" * 60)
        print(f"回测周期: {results['days']} 天")
        print(f"总交易次数: {results['total_trades']}")
        print(f"盈利交易: {results['winning_trades']} | 亏损交易: {results['losing_trades']}")
        print(f"胜率: {results['win_rate']:.1f}%")
        print(f"盈亏比: {results['profit_factor']:.2f}")
        print(f"最大回撤: {results['max_drawdown']:.2f}%")
        print(f"夏普比率: {results['sharpe_ratio']:.2f}")
        print("-" * 60)
        print(f"初始资金: ${results['initial_capital']:,.2f}")
        print(f"最终资金: ${results['final_capital']:,.2f}")
        print(f"总收益率: {results['total_return']:+.2f}%")
        print("=" * 60)

        if results['trades']:
            print("\n📋 最近10笔交易:")
            for t in results['trades'][-10:]:
                action = "买入" if t['action'] == 'BUY' else "卖出"
                pnl_str = f" | 盈亏: {t.get('pnl', 0):+.2f}" if 'pnl' in t else ""
                print(f"  {t['time'].strftime('%Y-%m-%d %H:%M')} | {action} | ${t['price']:,.2f} | {t['reason']}{pnl_str}")


async def run_backtest(symbol: str = "BTCUSDT", interval: str = "1h", days: int = 90):
    init_db()
    bt = Backtester(symbol, interval, days)

    if not bt.load_data():
        if not await bt.fetch_and_save_data():
            return None

    signals = bt.generate_signals()
    print(f"📊 生成 {len(signals)} 个交易信号")

    results = bt.run(signals)
    bt.print_report(results)
    return results


if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    interval = sys.argv[2] if len(sys.argv) > 2 else "1h"
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 90

    asyncio.run(run_backtest(symbol, interval, days))
