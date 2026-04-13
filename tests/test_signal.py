import pandas as pd

from scanner.signal import SignalConfig, TradeSignal, generate_signals, calculate_atr


def test_filter_by_min_score():
    """低于 min_score 的结果被过滤。"""
    matches = [
        {"symbol": "A/USDT", "price": 100.0, "score": 0.65, "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14},
        {"symbol": "B/USDT", "price": 50.0, "score": 0.45, "drop_pct": 0.08, "volume_ratio": 0.4, "window_days": 10},
        {"symbol": "C/USDT", "price": 200.0, "score": 0.70, "drop_pct": 0.12, "volume_ratio": 0.2, "window_days": 12},
    ]
    signals = generate_signals(matches, SignalConfig(min_score=0.6))
    assert len(signals) == 2
    assert signals[0].symbol == "A/USDT"
    assert signals[1].symbol == "C/USDT"


def test_trade_params_fixed_fallback():
    """无ATR时回退到固定百分比: score=0.70 → 2.5%回撤, SL=entry*0.95, TP=entry*1.08。"""
    matches = [
        {"symbol": "X/USDT", "price": 100.0, "score": 0.70, "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14},
    ]
    config = SignalConfig(min_score=0.6, stop_loss=0.05, take_profit=0.08, hold_days=3)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert s.price == 100.0
    assert abs(s.entry_price - 97.5) < 0.01
    assert abs(s.stop_loss_price - 92.625) < 0.01
    assert abs(s.take_profit_price - 105.3) < 0.01
    assert s.hold_days == 3


def test_trade_params_with_atr():
    """有ATR时: entry=97.5, SL=entry-2*ATR=97.5-2*2=93.5, TP=entry+3*ATR=97.5+3*2=103.5。"""
    matches = [
        {"symbol": "X/USDT", "price": 100.0, "score": 0.70, "drop_pct": 0.10,
         "volume_ratio": 0.3, "window_days": 14, "atr": 2.0},
    ]
    config = SignalConfig(min_score=0.6, atr_sl_multiplier=2.0, atr_tp_multiplier=3.0, hold_days=3)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert abs(s.entry_price - 97.5) < 0.01
    assert abs(s.stop_loss_price - 93.5) < 0.01   # 97.5 - 2*2.0
    assert abs(s.take_profit_price - 103.5) < 0.01  # 97.5 + 3*2.0


def test_bearish_signal_with_atr():
    """顶背离+ATR: entry=102.5, SL=entry+2*ATR=106.5, TP=entry-3*ATR=96.5。"""
    matches = [
        {
            "symbol": "X/USDT", "price": 100.0, "score": 0.70, "atr": 2.0,
            "drop_pct": 0.0, "volume_ratio": 0.0, "window_days": 0,
            "signal_type": "顶背离", "mode": "divergence",
        },
    ]
    config = SignalConfig(min_score=0.6, atr_sl_multiplier=2.0, atr_tp_multiplier=3.0, hold_days=3)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert s.signal_type == "顶背离"
    assert abs(s.entry_price - 102.5) < 0.01
    assert abs(s.stop_loss_price - 106.5) < 0.01   # 102.5 + 2*2.0
    assert abs(s.take_profit_price - 96.5) < 0.01   # 102.5 - 3*2.0


def test_all_filtered_out():
    """全部低于门槛时返回空列表。"""
    matches = [
        {"symbol": "A/USDT", "price": 100.0, "score": 0.30, "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14},
    ]
    signals = generate_signals(matches, SignalConfig(min_score=0.6))
    assert signals == []


def test_empty_input():
    """空输入返回空列表。"""
    signals = generate_signals([], SignalConfig())
    assert signals == []


def test_bearish_signal_reverses_sl_tp():
    """顶背离信号(无ATR): score=0.70, SL/TP用固定百分比。"""
    matches = [
        {
            "symbol": "X/USDT", "price": 100.0, "score": 0.70,
            "drop_pct": 0.0, "volume_ratio": 0.0, "window_days": 0,
            "signal_type": "顶背离", "mode": "divergence",
        },
    ]
    config = SignalConfig(min_score=0.6, stop_loss=0.05, take_profit=0.08, hold_days=3)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert s.signal_type == "顶背离"
    assert abs(s.entry_price - 102.5) < 0.01
    assert abs(s.stop_loss_price - 107.625) < 0.01
    assert abs(s.take_profit_price - 94.3) < 0.01


def test_bullish_signal_default_direction():
    """底背离信号(无ATR): score=0.70, SL/TP用固定百分比。"""
    matches = [
        {
            "symbol": "Y/USDT", "price": 100.0, "score": 0.70,
            "drop_pct": 0.0, "volume_ratio": 0.0, "window_days": 0,
            "signal_type": "底背离", "mode": "divergence",
        },
    ]
    config = SignalConfig(min_score=0.6, stop_loss=0.05, take_profit=0.08, hold_days=3)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert s.signal_type == "底背离"
    assert abs(s.entry_price - 97.5) < 0.01
    assert abs(s.stop_loss_price - 92.625) < 0.01
    assert abs(s.take_profit_price - 105.3) < 0.01


def test_legacy_match_no_signal_type():
    """旧格式(无signal_type字段)仍正常工作。"""
    matches = [
        {"symbol": "A/USDT", "price": 100.0, "score": 0.65,
         "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14},
    ]
    signals = generate_signals(matches, SignalConfig(min_score=0.6))
    assert len(signals) == 1
    assert signals[0].signal_type == ""


def test_calculate_atr():
    """ATR 计算: 简单场景下 ATR = 平均 True Range。"""
    data = {
        "open": [10.0] * 20,
        "high": [12.0] * 20,
        "low": [9.0] * 20,
        "close": [11.0] * 20,
        "volume": [1000] * 20,
    }
    df = pd.DataFrame(data)
    atr = calculate_atr(df, period=14)
    # high-low=3, prev_close=11, |high-prev|=1, |low-prev|=2 → TR=3 for all rows
    assert abs(atr - 3.0) < 0.01


def test_sl_capped_when_atr_exceeds_limit():
    """ATR 止损超出 max_stop_loss 时，止损被截断且 sl_capped=True。"""
    # price=100, score=0.70 → entry=97.5, ATR=10 → raw_sl=97.5-2*10=77.5 (距离20.5%) > 5%
    # capped: sl = 97.5 * (1 - 0.05) = 92.625
    matches = [
        {"symbol": "X/USDT", "price": 100.0, "score": 0.70, "atr": 10.0,
         "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14},
    ]
    config = SignalConfig(min_score=0.6, atr_sl_multiplier=2.0, atr_tp_multiplier=3.0,
                          max_stop_loss=0.05)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert s.sl_capped is True
    assert abs(s.stop_loss_price - 92.625) < 0.01   # 97.5 * 0.95


def test_sl_not_capped_when_within_limit():
    """ATR 止损在 max_stop_loss 以内时，止损不截断且 sl_capped=False。"""
    # price=100, score=0.70 → entry=97.5, ATR=2 → raw_sl=93.5 (距离4.1%) < 5%
    matches = [
        {"symbol": "X/USDT", "price": 100.0, "score": 0.70, "atr": 2.0,
         "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14},
    ]
    config = SignalConfig(min_score=0.6, atr_sl_multiplier=2.0, atr_tp_multiplier=3.0,
                          max_stop_loss=0.05)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert s.sl_capped is False
    assert abs(s.stop_loss_price - 93.5) < 0.01   # 97.5 - 2*2.0，未截断


def test_bearish_sl_capped():
    """顶背离 ATR 止损超出 max_stop_loss 时截断，sl_capped=True。"""
    # price=100, score=0.70 → entry=102.5, ATR=10 → raw_sl=122.5 (距离19.5%) > 5%
    # capped: sl = 102.5 * (1 + 0.05) = 107.625
    matches = [
        {"symbol": "X/USDT", "price": 100.0, "score": 0.70, "atr": 10.0,
         "drop_pct": 0.0, "volume_ratio": 0.0, "window_days": 0,
         "signal_type": "顶背离", "mode": "divergence"},
    ]
    config = SignalConfig(min_score=0.6, atr_sl_multiplier=2.0, atr_tp_multiplier=3.0,
                          max_stop_loss=0.05)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert s.sl_capped is True
    assert abs(s.stop_loss_price - 107.625) < 0.01   # 102.5 * 1.05
