import asyncio
import json
import os
import logging
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, Deque, List, Optional
import numpy as np
import aiohttp
import websockets
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("BTCScan")

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PROXY_URL = os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
MONITOR_SYMBOLS = [s.strip().upper() for s in os.getenv("MONITOR_SYMBOLS", "btcusdt").split(",") if s.strip()]
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "300"))

Z_SCORE_MULTIPLIER = float(os.getenv("Z_SCORE_MULTIPLIER", "3.0"))
MIN_VOLATILITY_THRESHOLD = float(os.getenv("MIN_VOLATILITY_THRESHOLD", "0.002"))
CUMULATIVE_THRESHOLD = float(os.getenv("CUMULATIVE_THRESHOLD", "0.005"))
CUMULATIVE_WINDOW = int(os.getenv("CUMULATIVE_WINDOW", "10"))
VOLUME_SPIKE_MULTIPLIER = float(os.getenv("VOLUME_SPIKE_MULTIPLIER", "5.0"))
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
RSI_OVERBOUGHT = float(os.getenv("RSI_OVERBOUGHT", "80"))
RSI_OVERSOLD = float(os.getenv("RSI_OVERSOLD", "20"))
BREAKOUT_WINDOW = int(os.getenv("BREAKOUT_WINDOW", "60"))
HISTORY_WINDOW = max(60, BREAKOUT_WINDOW, RSI_PERIOD + 1)

MACD_FAST = int(os.getenv("MACD_FAST", "12"))
MACD_SLOW = int(os.getenv("MACD_SLOW", "26"))
MACD_SIGNAL = int(os.getenv("MACD_SIGNAL", "9"))
BB_PERIOD = int(os.getenv("BB_PERIOD", "20"))
BB_STD = float(os.getenv("BB_STD", "2.0"))
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))

MULTI_RSI_CONFIRM = os.getenv("MULTI_RSI_CONFIRM", "true").lower() == "true"

ENABLE_1M = os.getenv("ENABLE_1M", "true").lower() == "true"
ENABLE_5M = os.getenv("ENABLE_5M", "true").lower() == "true"
ENABLE_1H = os.getenv("ENABLE_1H", "true").lower() == "true"
ENABLE_1D = os.getenv("ENABLE_1D", "true").lower() == "true"

TIMEFRAMES = []
if ENABLE_1M: TIMEFRAMES.append("1m")
if ENABLE_5M: TIMEFRAMES.append("5m")
if ENABLE_1H: TIMEFRAMES.append("1h")
if ENABLE_1D: TIMEFRAMES.append("1d")

TIMEFRAME_CONFIG = {
    "1m": {"history": 60, "breakout": 60},
    "5m": {"history": 60, "breakout": 48},
    "1h": {"history": 60, "breakout": 48},
    "1d": {"history": 30, "breakout": 30},
}

last_alert_times: Dict[str, datetime] = {}


class TimeframeData:
    def __init__(self, symbol: str, tf: str):
        self.symbol = symbol
        self.tf = tf
        config = TIMEFRAME_CONFIG.get(tf, {"history": 60, "breakout": 60})
        self.closes: Deque[float] = deque(maxlen=config["history"])
        self.volumes: Deque[float] = deque(maxlen=config["history"])
        self.highs: Deque[float] = deque(maxlen=config["breakout"])
        self.lows: Deque[float] = deque(maxlen=config["breakout"])
        self.returns: Deque[float] = deque(maxlen=config["history"])
        self.prices: Deque[float] = deque(maxlen=CUMULATIVE_WINDOW)
        self.last_alert_times: Dict[str, datetime] = {}

    def reset(self):
        config = TIMEFRAME_CONFIG.get(self.tf, {"history": 60, "breakout": 60})
        self.closes.clear()
        self.volumes.clear()
        self.highs.clear()
        self.lows.clear()
        self.returns.clear()
        self.prices.clear()
        self.last_alert_times.clear()


class MultiTimeframeMonitor:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.timeframes: Dict[str, TimeframeData] = {
            tf: TimeframeData(symbol, tf) for tf in TIMEFRAMES
        }
        self.current_1m_kline: Optional[dict] = None

    def reset_all(self):
        for tf_data in self.timeframes.values():
            tf_data.reset()


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


def calculate_atr(highs: Deque, lows: Deque, closes: Deque, period: int = 14) -> Optional[float]:
    if len(highs) < period or len(lows) < period or len(closes) < period:
        return None
    high_arr = np.array(list(highs)[-period:])
    low_arr = np.array(list(lows)[-period:])
    close_arr = np.array(list(closes)[-period:])
    tr = np.maximum(high_arr - low_arr,
                    np.maximum(np.abs(high_arr - np.roll(close_arr, 1)),
                               np.abs(low_arr - np.roll(close_arr, 1))))
    tr[0] = high_arr[0] - low_arr[0]
    return float(np.mean(tr))


def evaluate_strategies(symbol: str, tf: str, tf_data: TimeframeData,
                        current_price: float, open_price: float,
                        high_price: float, low_price: float,
                        volume: float, is_closed: bool, now: datetime) -> List[dict]:
    signals = []
    timeframe_suffix = f"[{tf}]"

    if len(tf_data.closes) < 10:
        return signals

    current_return = (current_price - open_price) / open_price

    if is_closed:
        tf_data.closes.append(current_price)
        tf_data.volumes.append(volume)
        tf_data.highs.append(high_price)
        tf_data.lows.append(low_price)
        tf_data.returns.append(current_return)
        tf_data.prices.append(current_price)

    closes = np.array(list(tf_data.closes))

    avg_vol = float(np.mean(tf_data.volumes)) if len(tf_data.volumes) > 0 else volume
    past_magnitudes = [abs(r) for r in tf_data.returns]
    avg_magnitude = np.mean(past_magnitudes) if past_magnitudes else MIN_VOLATILITY_THRESHOLD
    std_magnitude = np.std(past_magnitudes) if len(past_magnitudes) > 1 else 0
    threshold = max(MIN_VOLATILITY_THRESHOLD, avg_magnitude + Z_SCORE_MULTIPLIER * std_magnitude)

    if abs(current_return) >= threshold:
        direction = "🚀 爆拉" if current_return > 0 else "📉 砸盘"
        signals.append({
            "category": "PRICE",
            "title": f"突发异动 ({direction})",
            "desc": f"涨跌幅: `{current_return*100:+.2f}%` (阈值: {threshold*100:.2f}%)"
        })

    if len(tf_data.volumes) >= 10 and volume >= avg_vol * VOLUME_SPIKE_MULTIPLIER:
        signals.append({
            "category": "VOLUME",
            "title": "成交量异常剧增",
            "desc": f"当前: `{volume:.1f}` | 量比: `{volume/avg_vol:.1f}x`"
        })

    breakout_window = TIMEFRAME_CONFIG.get(tf, {}).get("breakout", 60)
    if len(tf_data.highs) == breakout_window:
        period_high = max(tf_data.highs)
        period_low = min(tf_data.lows)
        if current_price > period_high:
            signals.append({
                "category": "BREAKOUT",
                "title": "区间向上突破",
                "desc": f"突破 {breakout_window}{tf} 高点: `{period_high}`"
            })
        elif current_price < period_low:
            signals.append({
                "category": "BREAKOUT",
                "title": "区间向下砸穿",
                "desc": f"跌破 {breakout_window}{tf} 低点: `{period_low}`"
            })

    if is_closed and len(closes) >= RSI_PERIOD + 1:
        rsi = calculate_rsi(closes, RSI_PERIOD)

        if rsi >= RSI_OVERBOUGHT or rsi <= RSI_OVERSOLD:
            state = "🔴 超买" if rsi >= RSI_OVERBOUGHT else "🟢 超卖"
            signals.append({
                "category": "RSI",
                "title": f"RSI 极值提醒 {timeframe_suffix}",
                "desc": f"RSI: `{rsi:.2f}` ({state})"
            })

        if len(tf_data.prices) == CUMULATIVE_WINDOW:
            price_old = tf_data.prices[0]
            cumulative = (current_price - price_old) / price_old
            if abs(cumulative) >= CUMULATIVE_THRESHOLD:
                direction = "🚀 累计拉升" if cumulative > 0 else "📉 累计下跌"
                signals.append({
                    "category": "PRICE",
                    "title": f"{tf}累计变动 ({direction})",
                    "desc": f"变动: `{cumulative*100:+.2f}%`"
                })

    if is_closed and len(closes) >= MACD_SLOW + 1:
        macd, sig, hist = calculate_macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
        if macd is not None:
            if hist > 0 and hist > sig * 0.1:
                signals.append({
                    "category": "MACD",
                    "title": f"📈 MACD 动能转多 {timeframe_suffix}",
                    "desc": f"MACD: `{macd:.2f}` | Signal: `{sig:.2f}` | Hist: `{hist:.2f}`"
                })
            elif hist < 0 and abs(hist) > abs(sig) * 0.1:
                signals.append({
                    "category": "MACD",
                    "title": f"📉 MACD 动能转空 {timeframe_suffix}",
                    "desc": f"MACD: `{macd:.2f}` | Signal: `{sig:.2f}` | Hist: `{hist:.2f}`"
                })

    if is_closed and len(closes) >= BB_PERIOD:
        bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(closes, BB_PERIOD, BB_STD)
        if bb_upper is not None:
            bb_width = (bb_upper - bb_lower) / bb_middle * 100
            if current_price >= bb_upper:
                signals.append({
                    "category": "BB",
                    "title": f"🔴 布林带上轨突破 {timeframe_suffix}",
                    "desc": f"上轨: `{bb_upper:.2f}` | 带宽: `{bb_width:.2f}%`"
                })
            elif current_price <= bb_lower:
                signals.append({
                    "category": "BB",
                    "title": f"🟢 布林带下轨支撑 {timeframe_suffix}",
                    "desc": f"下轨: `{bb_lower:.2f}` | 带宽: `{bb_width:.2f}%`"
                })

    if len(tf_data.highs) >= ATR_PERIOD and len(tf_data.lows) >= ATR_PERIOD:
        atr = calculate_atr(tf_data.highs, tf_data.lows, tf_data.closes, ATR_PERIOD)
        if atr is not None:
            support = current_price - atr * 1.5
            resistance = current_price + atr * 1.5
            signals.append({
                "category": "ATR",
                "title": f"📊 ATR 波动率参考 {timeframe_suffix}",
                "desc": f"ATR: `{atr:.2f}` | 支撑: `{support:.2f}` | 阻力: `{resistance:.2f}`"
            })

    if is_closed and len(closes) >= RSI_PERIOD + 1:
        rsi = calculate_rsi(closes, RSI_PERIOD)
        avg_vol_past = float(np.mean(list(tf_data.volumes)[:-1])) if len(tf_data.volumes) > 1 else avg_vol
        is_vol_spike = volume >= avg_vol_past * 1.5
        is_green = current_price > open_price
        is_red = current_price < open_price

        if len(closes) >= BB_PERIOD:
            bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(closes, BB_PERIOD, BB_STD)
        else:
            bb_upper, bb_middle, bb_lower = None, None, None

        if rsi <= RSI_OVERSOLD and is_vol_spike and is_green:
            signals.append({
                "category": "SIGNAL",
                "title": f"🟢🟢 强烈买入信号 {timeframe_suffix}",
                "desc": f"RSI超卖+放量阳线 | RSI: `{rsi:.1f}` | 量比: `{volume/avg_vol_past:.1f}x`"
            })
        elif rsi <= RSI_OVERSOLD and is_vol_spike:
            signals.append({
                "category": "SIGNAL",
                "title": f"🟢 买入关注 {timeframe_suffix}",
                "desc": f"RSI超卖+放量 | RSI: `{rsi:.1f}` | 量比: `{volume/avg_vol_past:.1f}x`"
            })
        elif rsi <= RSI_OVERSOLD + 5:
            signals.append({
                "category": "SIGNAL",
                "title": f"🟡 观望提醒 {timeframe_suffix}",
                "desc": f"RSI接近超卖 | RSI: `{rsi:.1f}`"
            })
        elif bb_lower and current_price <= bb_lower and rsi <= 45:
            signals.append({
                "category": "SIGNAL",
                "title": f"🟢 布林下轨支撑 {timeframe_suffix}",
                "desc": f"价格触布林下轨 | 下轨: `{bb_lower:.1f}` | RSI: `{rsi:.1f}`"
            })

        if rsi >= RSI_OVERBOUGHT and is_vol_spike and is_red:
            signals.append({
                "category": "SIGNAL",
                "title": f"🔴🔴 强烈卖出信号 {timeframe_suffix}",
                "desc": f"RSI超买+放量阴线 | RSI: `{rsi:.1f}` | 量比: `{volume/avg_vol_past:.1f}x`"
            })
        elif rsi >= RSI_OVERBOUGHT and is_vol_spike:
            signals.append({
                "category": "SIGNAL",
                "title": f"🔴 卖出关注 {timeframe_suffix}",
                "desc": f"RSI超买+放量 | RSI: `{rsi:.1f}` | 量比: `{volume/avg_vol_past:.1f}x`"
            })
        elif rsi >= RSI_OVERBOUGHT - 5:
            signals.append({
                "category": "SIGNAL",
                "title": f"🟡 谨慎提醒 {timeframe_suffix}",
                "desc": f"RSI接近超买 | RSI: `{rsi:.1f}`"
            })
        elif bb_upper and current_price >= bb_upper and rsi >= 55:
            signals.append({
                "category": "SIGNAL",
                "title": f"🔴 布林上轨压力 {timeframe_suffix}",
                "desc": f"价格触布林上轨 | 上轨: `{bb_upper:.1f}` | RSI: `{rsi:.1f}`"
            })

    return signals


async def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured, skipping alert")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, proxy=PROXY_URL, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    data = await response.json()
                    logger.error(f"Telegram error: {data}")
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


def check_cooldown(symbol: str, tf: str, category: str, now: datetime) -> bool:
    key = f"{symbol}_{tf}_{category}"
    last_time = last_alert_times.get(key)
    if last_time and (now - last_time).total_seconds() < ALERT_COOLDOWN:
        return False
    last_alert_times[key] = now
    return True


async def handle_signals(symbol: str, signals: List[dict], price: float, now: datetime):
    if not signals:
        return
    valid = [s for s in signals if check_cooldown(symbol, s.get("tf", "1m"), s["category"], now)]
    if not valid:
        return
    priority_map = {"SIGNAL": 0, "PRICE": 1, "BREAKOUT": 2, "VOLUME": 3, "RSI": 4, "MACD": 5, "BB": 6, "ATR": 7}
    valid.sort(key=lambda x: priority_map.get(x["category"], 9))
    emoji = "🚨" if any(s["category"] == "SIGNAL" for s in valid) else "⚠️"
    msg = f"{emoji} *【{symbol} 多周期异动提醒】*\n\n"
    msg += f"当前价格: `{price}` | 时间: `{now.strftime('%H:%M:%S')}`\n\n"
    for i, sig in enumerate(valid):
        msg += f"{i+1}. *{sig['title']}*\n   - {sig['desc']}\n"
    msg += f"\n_冷却: {ALERT_COOLDOWN}s_"
    await send_telegram_alert(msg)


async def fetch_klines(symbol: str, interval: str, limit: int = 60) -> Optional[List[dict]]:
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=PROXY_URL, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                logger.error(f"Failed to fetch {interval} klines: {response.status}")
    except Exception as e:
        logger.error(f"Error fetching klines: {e}")
    return None


async def preload_historical_data(symbol: str, tf: str, tf_data: TimeframeData, limit: int = 60):
    klines = await fetch_klines(symbol, tf, limit)
    if klines:
        for k in klines:
            close = float(k[4])
            volume = float(k[5])
            high = float(k[2])
            low = float(k[3])
            open_price = float(k[1])
            tf_data.closes.append(close)
            tf_data.volumes.append(volume)
            tf_data.highs.append(high)
            tf_data.lows.append(low)
            tf_data.returns.append((close - open_price) / open_price if open_price else 0)
        logger.info(f"Preloaded {len(klines)} {tf} klines for {symbol}")
    else:
        logger.warning(f"Could not preload {tf} data for {symbol}, will accumulate from scratch")


async def monitor_prices():
    if not TIMEFRAMES:
        logger.error("No timeframes enabled!")
        return

    streams = "/".join([f"{sym.lower()}@kline_{tf}" for sym in MONITOR_SYMBOLS for tf in TIMEFRAMES])
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"

    logger.info(f"Connecting to {len(MONITOR_SYMBOLS)} symbols x {len(TIMEFRAMES)} timeframes")
    print(f"\n--- 启动多周期量化监控 ---")
    print(f"--- 监控币种: {', '.join(MONITOR_SYMBOLS)} ---")
    print(f"--- 周期: {', '.join(TIMEFRAMES)} | 冷却: {ALERT_COOLDOWN}s ---\n")

    monitors: Dict[str, MultiTimeframeMonitor] = {
        sym: MultiTimeframeMonitor(sym) for sym in MONITOR_SYMBOLS
    }

    logger.info("Preloading historical data...")
    for sym in MONITOR_SYMBOLS:
        for tf in TIMEFRAMES:
            config = TIMEFRAME_CONFIG.get(tf, {"history": 60})
            await preload_historical_data(sym, tf, monitors[sym].timeframes[tf], config["history"])
    logger.info("Historical data preloaded, connecting to WebSocket...")

    while True:
        try:
            async with websockets.connect(url, ping_timeout=30) as ws:
                logger.info("WebSocket connected")
                while True:
                    message = await ws.recv()
                    data = json.loads(message)
                    if "data" not in data:
                        continue

                    kline = data["data"]["k"]
                    symbol = kline["s"].upper()
                    tf = kline["i"]

                    if symbol not in monitors:
                        continue

                    monitor = monitors[symbol]
                    if tf not in monitor.timeframes:
                        continue

                    tf_data = monitor.timeframes[tf]
                    current_price = float(kline["c"])
                    open_price = float(kline["o"])
                    high_price = float(kline["h"])
                    low_price = float(kline["l"])
                    volume = float(kline["v"])
                    is_closed = kline["x"]
                    now = datetime.now()

                    signals = evaluate_strategies(
                        symbol, tf, tf_data,
                        current_price, open_price,
                        high_price, low_price,
                        volume, is_closed, now
                    )

                    if signals:
                        await handle_signals(symbol, signals, current_price, now)

                    if symbol == MONITOR_SYMBOLS[0] and tf == "1m":
                        closes = np.array(list(tf_data.closes))
                        rsi = calculate_rsi(closes, RSI_PERIOD) if len(closes) > RSI_PERIOD else 0
                        vol_ratio = volume / np.mean(tf_data.volumes) if tf_data.volumes else 1
                        print(f"\r[监控] {symbol} | Price: {current_price:<10} | RSI: {rsi:>5.2f} | 量比: {vol_ratio:>4.1f}x", end="", flush=True)

        except websockets.ConnectionClosed:
            logger.error("WebSocket closed, retrying...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Error: {e}, retrying...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_bot_token_here":
        print("--- [注意] 未配置 Telegram，仅本地监控模式 ---")
    asyncio.run(monitor_prices())
