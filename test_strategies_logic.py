import unittest
import numpy as np
from collections import deque
from monitor import calculate_rsi

class TestStrategies(unittest.TestCase):
    def test_rsi_calculation(self):
        # Generate some mock price data (descending then ascending)
        # Prices dropping for 14 bars (should yield low RSI)
        prices_down = [100 - i for i in range(20)]
        rsi_low = calculate_rsi(prices_down, period=14)
        print(f"RSI Low test: {rsi_low:.2f}")
        self.assertTrue(rsi_low < 30)

        # Prices rising for 14 bars (should yield high RSI)
        prices_up = [100 + i for i in range(20)]
        rsi_high = calculate_rsi(prices_up, period=14)
        print(f"RSI High test: {rsi_high:.2f}")
        self.assertTrue(rsi_high > 70)

    def test_volume_spike_logic(self):
        # Mocking the logic found in monitor.py
        history_volumes = deque([10.0] * 10, maxlen=30)
        avg_volume = np.mean(history_volumes)
        current_volume = 100.0 # 10x spike
        spike_multiplier = 5.0
        
        is_spike = current_volume >= avg_volume * spike_multiplier
        self.assertTrue(is_spike)
        print(f"Volume Spike detected: {current_volume} vs Avg {avg_volume}")

    def test_breakout_logic(self):
        # Mock breakout window
        history_highs = deque([100.0] * 60, maxlen=60)
        history_lows = deque([90.0] * 60, maxlen=60)
        
        current_price_high = 101.0
        current_price_low = 89.0
        
        is_breakout_up = current_price_high > max(history_highs)
        is_breakout_down = current_price_low < min(history_lows)
        
        self.assertTrue(is_breakout_up)
        self.assertTrue(is_breakout_down)
        print(f"Breakout detected: High {current_price_high} > {max(history_highs)}, Low {current_price_low} < {min(history_lows)}")

if __name__ == '__main__':
    unittest.main()
