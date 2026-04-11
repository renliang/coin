from scanner.stats import compute_stats


def test_compute_stats_basic():
    """基本统计：3 笔交易，2 赢 1 亏。"""
    trades = [
        {"pnl_pct": 0.08, "pnl": 80.0},
        {"pnl_pct": 0.05, "pnl": 50.0},
        {"pnl_pct": -0.03, "pnl": -30.0},
    ]
    s = compute_stats(trades)
    assert s["total"] == 3
    assert s["wins"] == 2
    assert abs(s["win_rate"] - 2 / 3) < 0.01
    assert abs(s["avg_pnl_pct"] - (0.08 + 0.05 - 0.03) / 3) < 0.001
    assert abs(s["profit_factor"] - 130 / 30) < 0.01
    assert s["max_gain"] == 0.08
    assert s["max_loss"] == -0.03


def test_compute_stats_empty():
    """空列表返回零值。"""
    s = compute_stats([])
    assert s["total"] == 0
    assert s["win_rate"] == 0
    assert s["profit_factor"] == 0


def test_compute_stats_all_wins():
    """全赢时 profit_factor 用总盈利代替（除零保护）。"""
    trades = [
        {"pnl_pct": 0.05, "pnl": 50.0},
        {"pnl_pct": 0.10, "pnl": 100.0},
    ]
    s = compute_stats(trades)
    assert s["win_rate"] == 1.0
    assert s["profit_factor"] == 150.0
    assert s["max_loss"] == 0
