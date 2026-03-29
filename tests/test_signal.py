from scanner.signal import SignalConfig, TradeSignal, generate_signals


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


def test_trade_params_calculation():
    """止损价 = price * 0.95，止盈价 = price * 1.08。"""
    matches = [
        {"symbol": "X/USDT", "price": 100.0, "score": 0.70, "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14},
    ]
    config = SignalConfig(min_score=0.6, stop_loss=0.05, take_profit=0.08, hold_days=3)
    signals = generate_signals(matches, config)

    assert len(signals) == 1
    s = signals[0]
    assert s.entry_price == 100.0
    assert abs(s.stop_loss_price - 95.0) < 0.01
    assert abs(s.take_profit_price - 108.0) < 0.01
    assert s.hold_days == 3


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
    """顶背离信号: 止损在上方, 止盈在下方。"""
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
    assert abs(s.stop_loss_price - 105.0) < 0.01   # 上方止损
    assert abs(s.take_profit_price - 92.0) < 0.01   # 下方止盈


def test_bullish_signal_default_direction():
    """底背离信号: 与原有做多方向一致。"""
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
    assert abs(s.stop_loss_price - 95.0) < 0.01
    assert abs(s.take_profit_price - 108.0) < 0.01


def test_legacy_match_no_signal_type():
    """旧格式(无signal_type字段)仍正常工作。"""
    matches = [
        {"symbol": "A/USDT", "price": 100.0, "score": 0.65,
         "drop_pct": 0.10, "volume_ratio": 0.3, "window_days": 14},
    ]
    signals = generate_signals(matches, SignalConfig(min_score=0.6))
    assert len(signals) == 1
    assert signals[0].signal_type == ""
