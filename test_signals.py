import numpy as np
from collections import deque
from monitor import calculate_rsi
import asyncio

# 模拟参数
RSI_PERIOD = 14
RSI_OVERSOLD = 20
RSI_OVERBOUGHT = 80

def test_combined_logic():
    print("--- 开始测试多因子组合信号逻辑 ---\n")
    
    # 场景 1: 模拟强力买入 (超卖 + 放量 + 阳线)
    # 构造一段下跌行情使 RSI 降低
    prices = [100, 98, 96, 94, 92, 90, 88, 86, 84, 82, 80, 78, 76, 74, 72] # 15个点
    volumes = [10, 12, 11, 13, 15, 14, 16, 18, 20, 22, 25, 28, 30, 35, 40] 
    
    # 当前 1m K 线数据 (收阳，放量)
    open_price = 71
    current_price = 73 
    volume = 100 # 显著放大
    
    history_closes = deque(prices, maxlen=30)
    history_closes.append(current_price)
    
    history_volumes = deque(volumes, maxlen=30)
    avg_vol = np.mean(list(history_volumes))
    
    rsi = calculate_rsi(list(history_closes), RSI_PERIOD)
    is_vol_spike = volume >= avg_vol * 1.5
    is_green = current_price > open_price
    
    print(f"[买入场景测试]")
    print(f"RSI: {rsi:.2f} (阈值 <= {RSI_OVERSOLD+5})")
    print(f"量比: {volume/avg_vol:.1f}x (阈值 >= 1.5x)")
    print(f"是否阳线: {is_green}")
    
    if rsi <= (RSI_OVERSOLD + 5) and is_vol_spike and is_green:
        print("✅ 测试结果: 触发【强力买入】信号！")
    else:
        print("❌ 测试结果: 未能触发买入信号")

    print("\n" + "-"*30 + "\n")

    # 场景 2: 模拟强力卖出 (超买 + 放量 + 阴线)
    # 构造一段上涨行情使 RSI 升高
    prices_up = [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 120, 122, 124, 126, 128]
    volumes_up = [10, 11, 10, 12, 13, 12, 14, 15, 14, 16, 17, 18, 20, 22, 25]
    
    # 当前 1m K 线数据 (收阴，放量)
    open_price_up = 132
    current_price_up = 130
    volume_up = 80 # 显著放大
    
    history_closes_up = deque(prices_up, maxlen=30)
    history_closes_up.append(current_price_up)
    
    history_volumes_up = deque(volumes_up, maxlen=30)
    avg_vol_up = np.mean(list(history_volumes_up))
    
    rsi_up = calculate_rsi(list(history_closes_up), RSI_PERIOD)
    is_vol_spike_up = volume_up >= avg_vol_up * 1.5
    is_red = current_price_up < open_price_up
    
    print(f"[卖出场景测试]")
    print(f"RSI: {rsi_up:.2f} (阈值 >= {RSI_OVERBOUGHT-5})")
    print(f"量比: {volume_up/avg_vol_up:.1f}x (阈值 >= 1.5x)")
    print(f"是否阴线: {is_red}")
    
    if rsi_up >= (RSI_OVERBOUGHT - 5) and is_vol_spike_up and is_red:
        print("✅ 测试结果: 触发【强力卖出】信号！")
    else:
        print("❌ 测试结果: 未能触发卖出信号")

if __name__ == "__main__":
    test_combined_logic()
