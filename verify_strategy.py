import asyncio
import os
import json
import logging
import numpy as np
import aiohttp
from collections import deque
from datetime import datetime
from dotenv import load_dotenv

# Set up logging for the test
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("StrategyTest")

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PROXY_URL = os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")

# Strategy Config (Match monitor.py)
HISTORY_WINDOW = 30
Z_SCORE_MULTIPLIER = 3.0
MIN_VOLATILITY_THRESHOLD = 0.002 # 0.2%
CUMULATIVE_THRESHOLD = 0.005 # 0.5%
CUMULATIVE_WINDOW = 10

async def send_telegram_alert(message: str):
    """Send alert via Telegram Bot with proxy support."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("\n⚠️ Telegram credentials not set, skipping message send.")
        print(f"Message that would have been sent:\n{message}\n")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, proxy=PROXY_URL) as response:
                if response.status == 200:
                    print("✅ Telegram 测试消息已发出！")
                else:
                    data = await response.json()
                    print(f"❌ Telegram 发送失败: {data.get('description')}")
    except Exception as e:
        print(f"❌ Telegram 发送异常: {e}")

def calculate_threshold(returns_history):
    """Core logic to calculate adaptive threshold."""
    if len(returns_history) < 10:
        return None, 0
    
    past_magnitudes = [abs(r) for r in returns_history]
    avg_vol = np.mean(past_magnitudes)
    std_vol = np.std(past_magnitudes)
    
    threshold = max(MIN_VOLATILITY_THRESHOLD, avg_vol + Z_SCORE_MULTIPLIER * std_vol)
    return threshold, avg_vol

async def run_simulation():
    print("--- 综合策略验证 (自适应 + 10分钟累计) ---\n")
    
    # --- 场景 1：自适应策略验证 ---
    print("步骤 1: 验证自适应策略 (1分钟突发波动)...")
    flat_returns = deque(maxlen=HISTORY_WINDOW)
    for _ in range(30):
        flat_returns.append(np.random.uniform(-0.0005, 0.0005))
    
    threshold, avg_vol = calculate_threshold(flat_returns)
    current_return = 0.006 # 0.6%
    symbol = "TEST_BTC"
    
    if abs(current_return) >= threshold:
        print(f"🔥 [OK] 检测到 1m 突发异动! 波动 {current_return*100:.2f}% > 阈值 {threshold*100:.4f}%")
        alert_msg = (
            f"*🧪 [测试] {symbol} 突发异动*\n"
            f"当前 1m 波动: `{current_return*100:+.2f}%` (超标)\n"
            f"动态阈值: `{threshold*100:.4f}%`"
        )
        await send_telegram_alert(alert_msg)

    # --- 场景 2：10分钟累计策略验证 ---
    print("\n步骤 2: 验证 10 分钟累计策略 (慢牛/慢熊)...")
    # 模拟过去 10 分钟价格
    base_price = 60000
    # 历史价格：从 10 分钟前到 1 分钟前
    # 价格平稳在 60000
    history_prices = deque([base_price] * 10, maxlen=10)
    
    # 当前价格缓慢上涨到 60400 (涨幅 0.67%)
    current_price = 60400
    price_10m_ago = history_prices[0]
    cumulative_change = (current_price - price_10m_ago) / price_10m_ago
    
    if abs(cumulative_change) >= CUMULATIVE_THRESHOLD:
        print(f"🔥 [OK] 检测到 10m 累计异动! 涨幅 {cumulative_change*100:.2f}% >= {CUMULATIVE_THRESHOLD*100:.2f}%")
        alert_msg = (
            f"*🧪 [测试] {symbol} 10分钟累积异动*\n"
            f"当前价格: `{current_price}`\n"
            f"累计涨跌: `{cumulative_change*100:+.2f}%` (超标)\n"
            f"10分钟前价格: `{price_10m_ago}`"
        )
        await send_telegram_alert(alert_msg)
    else:
        print(f"❌ 未触发报警，当前涨幅 {cumulative_change*100:.2f}%")

    print("\n--- 验证结束 ---")

if __name__ == "__main__":
    asyncio.run(run_simulation())
