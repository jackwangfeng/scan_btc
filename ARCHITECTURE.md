# BTC 量化监控系统架构文档

## 概述

这是一个基于币安 WebSocket 的多周期加密货币监控系统，支持多时间框架技术分析和市场情绪数据监控。

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    MultiTimeframeMonitor                      │
│  ┌─────────────┬─────────────┬─────────────┬─────────────┐   │
│  │  Timeframe  │  Timeframe  │  Timeframe  │  Timeframe  │   │
│  │    1m       │    5m       │    1h       │    1d       │   │
│  │  ┌───────┐  │  ┌───────┐  │  ┌───────┐  │  ┌───────┐  │   │
│  │  │ closes│  │  │ closes│  │  │ closes│  │  │ closes│  │   │
│  │  │ volumes│ │  │ volumes│ │  │ volumes│ │  │ volumes│ │   │
│  │  │ highs │  │  │ highs │  │  │ highs │  │  │ highs │  │   │
│  │  │ lows  │  │  │ lows  │  │  │ lows  │  │  │ lows  │  │   │
│  │  └───────┘  │  └───────┘  │  └───────┘  │  └───────┘  │   │
│  └─────────────┴─────────────┴─────────────┴─────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  策略评估引擎 (evaluate_strategies)            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ 价格波动  │ │ 成交量   │ │ 区间突破  │ │  RSI    │       │
│  │(Z-Score) │ │(Volume)  │ │(Breakout)│ │(Momentum)│       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │  MACD    │ │ 布林带   │ │   ATR    │ │ 多因子  │       │
│  │(动能)    │ │  (BB)    │ │ (止损)   │ │ 共振    │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    市场情绪数据 (Market Sentiment)            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                     │
│  │ 资金费率  │ │ 恐惧贪婪  │ │ 多空比   │                     │
│  │(Funding) │ │(F&G Index)│ │(L/S Ratio)│                    │
│  └──────────┘ └──────────┘ └──────────┘                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Telegram 告警                            │
│  - 多级别信号 (观望/关注/强烈)                                  │
│  - 冷却机制 (Cooldown)                                        │
│  - 优先级排序                                                  │
└─────────────────────────────────────────────────────────────┘
```

## 核心组件

### 1. TimeframeData (时间周期数据容器)

管理单个时间周期的所有数据队列：

| 属性 | 说明 | 默认大小 |
|------|------|---------|
| `closes` | 收盘价 | 60 (1m/5m/1h) / 30 (1d) |
| `volumes` | 成交量 | 同上 |
| `highs` | 最高价 | 60 (1m) / 48 (5m/1h) / 30 (1d) |
| `lows` | 最低价 | 同上 |
| `returns` | 收益率 | 同 closes |
| `prices` | 价格（用于累计变动计算） | 10 |

### 2. MultiTimeframeMonitor (多周期监控器)

```
MultiTimeframeMonitor
├── symbol: str
├── timeframes: Dict[str, TimeframeData]
│   ├── "1m" → TimeframeData
│   ├── "5m" → TimeframeData
│   ├── "1h" → TimeframeData
│   └── "1d" → TimeframeData
└── current_1m_kline: dict (可选)
```

### 3. 策略函数

#### 技术指标计算

| 函数 | 说明 | 依赖参数 |
|------|------|---------|
| `calculate_rsi()` | RSI 相对强弱指数 | period=14 |
| `calculate_ema()` | 指数移动平均 | period |
| `calculate_macd()` | MACD (12/26/9) | fast, slow, signal |
| `calculate_bollinger_bands()` | 布林带 | period=20, std=2.0 |
| `calculate_atr()` | ATR 平均真实波幅 | period=14 |

#### 策略评估 (evaluate_strategies)

对每个时间周期独立评估以下策略：

| 策略 | Category | 触发条件 |
|------|----------|---------|
| 突发异动 | PRICE | 涨跌幅超过 Z-Score 阈值 |
| 成交量异常 | VOLUME | 量比 >= 5x |
| 区间突破 | BREAKOUT | 突破 N 周期高低点 |
| RSI 极值 | RSI | RSI <= 20 或 >= 80 |
| 累计变动 | PRICE | 10周期累计变动 >= 0.5% |
| MACD 动能 | MACD | Histogram 转多/转空 |
| 布林带 | BB | 价格触上轨/下轨 |
| ATR 波动率 | ATR | 动态支撑/阻力参考 |
| 多因子买入 | SIGNAL | RSI<=25 + 放量 + 阳线 |
| 多因子卖出 | SIGNAL | RSI>=75 + 放量 + 阴线 |

### 4. 市场情绪 (Market Sentiment)

| 数据源 | API | 检查频率 |
|--------|-----|---------|
| 资金费率 | `fapi.binance.com/fundingRate` | 5分钟 |
| 恐惧贪婪指数 | `api.alternative.me/fng` | 5分钟 |
| 多空人数比 | `fapi.binance.com/globalLongShortAccountRatio` | 5分钟 |

### 5. 告警系统

- **冷却机制**: 每个 (symbol, timeframe, category) 独立 cooldown
- **优先级**: SIGNAL > PRICE > BREAKOUT > VOLUME > RSI > MACD > BB > ATR > MARKET
- **多级别信号**:
  - 🟢🟢 / 🔴🔴 强烈信号
  - 🟢 / 🔴 关注信号
  - 🟡 观望/谨慎信号
  - 布林带支撑/压力信号

## 数据流

```
1. 启动时预加载历史数据 (REST API)
   └─→ 填充各时间周期的 deque

2. WebSocket 接收实时 K线
   └─→ 更新对应 TimeframeData

3. K线收盘时评估策略
   └─→ 生成信号列表

4. 检查 cooldown
   └─→ 通过则发送 Telegram 告警

5. 每5分钟检查市场情绪
   └─→ 获取 Funding/F&G/L/S
   └─→ 触发阈值则发送告警
```

## 配置参数

### 时间周期开关

```bash
ENABLE_1M=true      # 1分钟
ENABLE_5M=true      # 5分钟
ENABLE_1H=true      # 1小时
ENABLE_1D=true      # 1天
```

### 技术指标参数

```bash
RSI_PERIOD=14
RSI_OVERBOUGHT=80
RSI_OVERSOLD=20

MACD_FAST=12
MACD_SLOW=26
MACD_SIGNAL=9

BB_PERIOD=20
BB_STD=2.0

ATR_PERIOD=14
```

### 信号参数

```bash
Z_SCORE_MULTIPLIER=3.0
MIN_VOLATILITY_THRESHOLD=0.002
VOLUME_SPIKE_MULTIPLIER=5.0
CUMULATIVE_THRESHOLD=0.005
CUMULATIVE_WINDOW=10
ALERT_COOLDOWN=300
```

### 市场情绪参数

```bash
ENABLE_FUNDING_RATE=true
ENABLE_FEAR_GREED=true
ENABLE_LONG_SHORT=true
FUNDING_RATE_THRESHOLD=0.01
FEAR_GREED_BUY_THRESHOLD=25
FEAR_GREED_SELL_THRESHOLD=75
LONG_SHORT_THRESHOLD=2.0
```

## WebSocket 数据源

```
wss://stream.binance.com:9443/stream?streams=
  {symbol1}@kline_{tf1}/
  {symbol1}@kline_{tf2}/
  {symbol2}@kline_{tf1}/...
```

## 文件结构

```
scan_btc/
├── monitor.py          # 主程序
├── .env                # 本地配置 (已 gitignore)
├── .env.example        # 配置模板
├── requirements.txt    # 依赖
├── start.sh            # 启动脚本
├── stop.sh             # 停止脚本
└── status.sh           # 状态脚本
```

## 依赖

```
aiohttp>=3.8.0
websockets>=10.0
numpy>=1.21.0
python-dotenv>=0.19.0
```

## 使用方式

```bash
# 安装依赖
pip install -r requirements.txt

# 复制配置
cp .env.example .env
# 编辑 .env 填入 Telegram token

# 启动 (需要先加载代理)
source /usr/local/proxy1.sh
./start.sh
```

## 扩展方向

1. **更多时间周期**: 15m, 4h, 1w
2. **更多市场情绪数据**: 交易所净流量、大户转账、交易所余额
3. **策略组合**: 多周期共振、多指标组合
4. **回测模块**: 基于历史数据的策略验证
5. **Web UI**: 可视化监控面板
