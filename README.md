# BTC 多币种波动监控工具 (Telegram 预警)

这是一个基于 Python 的后台工具，通过币安 WebSocket 实时监控多个交易对的 1 分钟价格波动。当波动率超过设定阈值（默认 0.5%）时，自动通过 Telegram Bot 发送预警。

## 功能特性
- **多币种监控**: 支持同时监控多个交易对（如 BTC/USDT, ETH/USDT 等）。
- **实时性**: 使用币安 WebSocket `kline_1m` 流，秒级感知价格变动。
- **智能预警**: 自动计算当前价格相对于本分钟开盘价的波动率。
- **防轰炸**: 同一币种在同一分钟内仅会触发一次报警。
- **无界面**: 纯后台运行，适合部署在服务器上。

## 快速开始

### 1. 安装依赖
确保你已安装 Python 3.8+，然后安装所需库：
```bash
pip install -r requirements.txt
```

### 2. 配置环境
将 `.env.example` 重命名为 `.env`，并填入你的 Telegram 信息：
- `TELEGRAM_BOT_TOKEN`: 你的 Bot Token（从 @BotFather 获取）。
- `TELEGRAM_CHAT_ID`: 接收消息的 Chat ID（可以从 @userinfobot 获取）。
- `MONITOR_SYMBOLS`: 要监控的币种，多个用逗号分隔，例如 `btcusdt,ethusdt,solusdt`。
- `VOLATILITY_THRESHOLD`: 触发报警的波动率（默认 0.005，即 0.5%）。

### 3. 启动程序
```bash
python monitor.py
```

## 预警消息示例
> **🚨 BTCUSDT 剧烈波动预警**
> 
> 变动方向: 🚀 涨
> 当前价格: `69500.50`
> 1分钟波动率: `+0.52%`
> 基准(开盘价): `69145.20`
> 时间: `14:25:30`
# scan_btc
