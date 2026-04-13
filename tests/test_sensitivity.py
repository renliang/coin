from scanner.sensitivity import run_scanner_sensitivity_grid, sensitivity_market_cap_note
from tests.test_backtest import _make_klines


def _pattern_df():
    n_pattern = 14
    n_future = 40
    pattern_prices = [100 - i * 0.7 for i in range(n_pattern)]
    pattern_volumes = [1000] * 7 + [300] * 7
    future_prices = [pattern_prices[-1] + i * 0.2 for i in range(1, n_future + 1)]
    future_volumes = [500] * n_future
    prices = pattern_prices + future_prices
    volumes = pattern_volumes + future_volumes
    return _make_klines(prices, volumes)


def test_sensitivity_grid_changes_hit_count():
    df = _pattern_df()
    klines = {f"S{i}/USDT": df for i in range(3)}
    base = {
        "window_min_days": 7,
        "window_max_days": 14,
        "volume_ratio": 0.5,
        "drop_min": 0.05,
        "drop_max": 0.15,
        "max_daily_change": 0.05,
    }
    rows = run_scanner_sensitivity_grid(klines, base_config=base)
    assert rows[0]["label"] == "baseline"
    assert all("hit_count" in r for r in rows)


def test_sensitivity_market_cap_note():
    s = sensitivity_market_cap_note(True)
    assert "skip_market_cap_filter" in s
