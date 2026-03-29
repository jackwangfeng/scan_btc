import asyncio
import os
import aiohttp
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# Proxy configuration: check PROXY_URL from .env or standard env variables
PROXY_URL = os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")

async def test_telegram():
    """Send a test message to verify Telegram configuration."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_bot_token_here":
        print("❌ 错误: 未设置 TELEGRAM_BOT_TOKEN。请检查 .env 文件。")
        return
    
    if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "your_chat_id_here":
        print("❌ 错误: 未设置 TELEGRAM_CHAT_ID。请检查 .env 文件。")
        return

    print(f"--- 正在向 Chat ID {TELEGRAM_CHAT_ID} 发送测试消息... ---")
    if PROXY_URL:
        print(f"--- 使用代理: {PROXY_URL} ---")
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": "🔔 *BTC 监控工具测试消息*\n\n如果您收到这条消息，说明 Telegram 通道配置成功！🚀",
        "parse_mode": "Markdown"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, proxy=PROXY_URL) as response:
                result = await response.json()
                if response.status == 200:
                    print("✅ 发送成功！请检查您的 Telegram。")
                else:
                    print(f"❌ 发送失败。错误代码: {response.status}")
                    print(f"原因: {result.get('description', '未知错误')}")
    except Exception as e:
        print(f"❌ 发生异常: {e}")

if __name__ == "__main__":
    asyncio.run(test_telegram())
