import asyncio
import json
import os
import logging
from datetime import datetime, timedelta
from collections import deque
import numpy as np
import aiohttp
import websockets
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("BTCScan")

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PROXY_URL = os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
MONITOR_SYMBOLS = [s.strip().upper() for s in os.getenv("MONITOR_SYMBOLS", "btcusdt").split(",") if s.strip()]

# Strategy Parameters
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
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "300"))

# State management
history_returns = {symbol: deque(maxlen=HISTORY_WINDOW) for symbol in MONITOR_SYMBOLS}
history_prices = {symbol: deque(maxlen=CUMULATIVE_WINDOW) for symbol in MONITOR_SYMBOLS}
history_volumes = {symbol: deque(maxlen=HISTORY_WINDOW) for symbol in MONITOR_SYMBOLS}
history_highs = {symbol: deque(maxlen=BREAKOUT_WINDOW) for symbol in MONITOR_SYMBOLS}
history_lows = {symbol: deque(maxlen=BREAKOUT_WINDOW) for symbol in MONITOR_SYMBOLS}
history_closes = {symbol: deque(maxlen=HISTORY_WINDOW) for symbol in MONITOR_SYMBOLS}

# Last alert time tracker: {(symbol, category): datetime}
last_alert_times = {}

def calculate_rsi(prices, period=14):
    """Calculate RSI using numpy."""
    if len(prices) <= period:
        return 50
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 100
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        if delta > 0:
            up_val = delta
            down_val = 0.
        else:
            up_val = 0.
            down_val = -delta

        up = (up * (period - 1) + up_val) / period
        down = (down * (period - 1) + down_val) / period
        rs = up / down if down != 0 else 100
        rsi[i] = 100. - 100. / (1. + rs)
    return rsi[-1]

async def send_telegram_alert(message: str):
    """Send alert via Telegram Bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram token or chat ID not set!")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, proxy=PROXY_URL) as response:
                if response.status != 200:
                    data = await response.json()
                    logger.error(f"Failed to send Telegram message: {data}")
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")

async def handle_triggered_signals(symbol, signals, price, now):
    """Merge signals and check cooldown before sending."""
    valid_signals = []
    for sig in signals:
        category = sig['category']
        last_time = last_alert_times.get((symbol, category))
        
        # Check cooldown
        if not last_time or (now - last_time).total_seconds() >= ALERT_COOLDOWN:
            valid_signals.append(sig)
            last_alert_times[(symbol, category)] = now
    
    if not valid_signals:
        return

    # Sort signals by priority: SIGNAL > PRICE > BREAKOUT > VOLUME > RSI
    priority_map = {"SIGNAL": 0, "PRICE": 1, "BREAKOUT": 2, "VOLUME": 3, "RSI": 4}
    valid_signals.sort(key=lambda x: priority_map.get(x['category'], 9))

    # Format Message
    emoji_header = "🚨" if any(s['category'] == 'SIGNAL' for s in valid_signals) else "⚠️"
    msg = f"{emoji_header} *【{symbol} 异动聚合提醒】*\n\n"
    msg += f"当前价格: `{price}`\n"
    msg += f"时间: `{now.strftime('%H:%M:%S')}`\n\n"
    
    for i, sig in enumerate(valid_signals):
        msg += f"{i+1}. *{sig['title']}*\n"
        msg += f"   - {sig['desc']}\n"
    
    msg += f"\n_#GlobalCooldown: {ALERT_COOLDOWN}s_"
    await send_telegram_alert(msg)

async def monitor_prices():
    """Connect to Binance WebSocket and monitor multiple strategies."""
    streams = "/".join([f"{symbol.lower()}@kline_1m" for symbol in MONITOR_SYMBOLS])
    base_url = "wss://stream.binance.com:9443/stream"
    url = f"{base_url}?streams={streams}"

    logger.info(f"Connecting to: {url} with 5 active strategies.")
    print(f"\n--- 正在启动 [全方位量化监控] ({', '.join(MONITOR_SYMBOLS)}) ---")
    print(f"--- 冷却时间: {ALERT_COOLDOWN}s | 包含: 价格波动、区间突破、成交量异动、RSI、多因子信号 ---\n")

    while True:
        try:
            async with websockets.connect(url) as ws:
                logger.info("WebSocket connected.")
                while True:
                    message = await ws.recv()
                    data = json.loads(message)
                    if "data" not in data: continue
                        
                    kline_data = data["data"]["k"]
                    symbol = data["data"]["s"].upper()
                    
                    open_price = float(kline_data["o"])
                    current_price = float(kline_data["c"])
                    high_price = float(kline_data["h"])
                    low_price = float(kline_data["l"])
                    volume = float(kline_data["v"])
                    is_closed = kline_data["x"]
                    
                    current_return = (current_price - open_price) / open_price
                    now = datetime.now()
                    
                    triggered_signals = []

                    # --- 1. Adaptive Z-Score (Real-time) ---
                    if len(history_returns[symbol]) >= 10:
                        past_magnitudes = [abs(r) for r in history_returns[symbol]]
                        avg_vol = np.mean(past_magnitudes)
                        std_vol = np.std(past_magnitudes)
                        threshold = max(MIN_VOLATILITY_THRESHOLD, avg_vol + Z_SCORE_MULTIPLIER * std_vol)
                        
                        if abs(current_return) >= threshold:
                            direction = "🚀 爆拉" if current_return > 0 else "📉 砸盘"
                            triggered_signals.append({
                                "category": "PRICE",
                                "title": f"突发异动 ({direction})",
                                "desc": f"涨跌幅: `{current_return*100:+.2f}%` (阈值: {threshold*100:.2f}%)"
                            })

                    # --- 2. Volume Spike (Real-time) ---
                    if len(history_volumes[symbol]) >= 10:
                        avg_volume = np.mean(history_volumes[symbol])
                        if volume >= avg_volume * VOLUME_SPIKE_MULTIPLIER:
                            triggered_signals.append({
                                "category": "VOLUME",
                                "title": "成交量异常剧增",
                                "desc": f"当前: `{volume:.1f}` | 量比: `{volume/avg_volume:.1f}x` (阈值: {VOLUME_SPIKE_MULTIPLIER}x)"
                            })

                    # --- 3. Price Breakout (Real-time) ---
                    if len(history_highs[symbol]) == BREAKOUT_WINDOW:
                        period_high = max(history_highs[symbol])
                        period_low = min(history_lows[symbol])
                        if current_price > period_high:
                            triggered_signals.append({
                                "category": "BREAKOUT",
                                "title": "区间向上突破",
                                "desc": f"突破 {BREAKOUT_WINDOW}m 高点: `{period_high}`"
                            })
                        elif current_price < period_low:
                            triggered_signals.append({
                                "category": "BREAKOUT",
                                "title": "区间向下砸穿",
                                "desc": f"跌破 {BREAKOUT_WINDOW}m 低点: `{period_low}`"
                            })

                    # --- On Candle Close ---
                    if is_closed:
                        history_returns[symbol].append(current_return)
                        history_prices[symbol].append(current_price)
                        history_volumes[symbol].append(volume)
                        history_highs[symbol].append(high_price)
                        history_lows[symbol].append(low_price)
                        history_closes[symbol].append(current_price)

                        # --- 4. RSI Momentum ---
                        if len(history_closes[symbol]) >= RSI_PERIOD + 1:
                            rsi = calculate_rsi(list(history_closes[symbol]), RSI_PERIOD)
                            if rsi >= RSI_OVERBOUGHT or rsi <= RSI_OVERSOLD:
                                state = "🔴 超买 (Overbought)" if rsi >= RSI_OVERBOUGHT else "🟢 超卖 (Oversold)"
                                triggered_signals.append({
                                    "category": "RSI",
                                    "title": "RSI 极值提醒",
                                    "desc": f"当前 RSI: `{rsi:.2f}` ({state})"
                                })

                        # --- 5. Cumulative Change (10 mins) ---
                        if len(history_prices[symbol]) == CUMULATIVE_WINDOW:
                            price_10m_ago = history_prices[symbol][0]
                            cumulative_change = (current_price - price_10m_ago) / price_10m_ago
                            if abs(cumulative_change) >= CUMULATIVE_THRESHOLD:
                                direction = "🚀 累计拉升" if cumulative_change > 0 else "📉 累计下跌"
                                triggered_signals.append({
                                    "category": "PRICE", # Map to PRICE to share cooldown with adaptive
                                    "title": f"10分钟累计变动 ({direction})",
                                    "desc": f"变动幅度: `{cumulative_change*100:+.2f}%` (阈值: {CUMULATIVE_THRESHOLD*100:.2f}%)"
                                })

                        # --- 6. Combined Buy/Sell Signal ---
                        if len(history_closes[symbol]) >= RSI_PERIOD + 1:
                            rsi = calculate_rsi(list(history_closes[symbol]), RSI_PERIOD)
                            avg_vol = np.mean(list(history_volumes[symbol])[:-1]) if len(history_volumes[symbol]) > 1 else volume
                            is_vol_spike = volume >= avg_vol * 1.5
                            is_green = current_price > open_price
                            is_red = current_price < open_price
                            
                            if rsi <= (RSI_OVERSOLD + 5) and is_vol_spike and is_green:
                                triggered_signals.append({
                                    "category": "SIGNAL",
                                    "title": "🟢 多因子买入共振",
                                    "desc": f"策略: 超卖反弹 + 放量阳线 | RSI: `{rsi:.2f}` | 量比: `{volume/avg_vol:.1f}x`"
                                })
                            elif rsi >= (RSI_OVERBOUGHT - 5) and is_vol_spike and is_red:
                                triggered_signals.append({
                                    "category": "SIGNAL",
                                    "title": "🔴 多因子卖出共振",
                                    "desc": f"策略: 超买回落 + 放量阴线 | RSI: `{rsi:.2f}` | 量比: `{volume/avg_vol:.1f}x`"
                                })

                    # Process and Send Alerts
                    if triggered_signals:
                        await handle_triggered_signals(symbol, triggered_signals, current_price, now)

                    # Status Update
                    if symbol == MONITOR_SYMBOLS[0]:
                        rsi_val = calculate_rsi(list(history_closes[symbol]), RSI_PERIOD) if len(history_closes[symbol]) > RSI_PERIOD else 0
                        vol_ratio = volume / np.mean(history_volumes[symbol]) if len(history_volumes[symbol]) > 0 else 1
                        print(f"\r[监控中] {symbol}: {current_price:<10} | RSI: {rsi_val:>5.2f} | 波动: {abs(current_return)*100:>5.3f}% | 量比: {vol_ratio:>4.1f}x", end="", flush=True)

        except websockets.ConnectionClosed:
            logger.error("WebSocket connection closed, retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error: {e}, retrying in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_bot_token_here":
        print("--- [注意] 未设置 Telegram 凭证，脚本将仅以测试模式运行 ---")
    asyncio.run(monitor_prices())
