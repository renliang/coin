import sqlite3

import pytest

import scanner.tracker as tracker_module


@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    """每个测试使用独立的临时数据库。"""
    db_path = str(tmp_path / "test.db")
    original = tracker_module.DB_PATH
    tracker_module.DB_PATH = db_path
    yield db_path
    tracker_module.DB_PATH = original


def _make_signal(
    symbol="X/USDT",
    price=100.0,
    score=0.75,
    entry_price=97.5,
    stop_loss_price=92.0,
    take_profit_price=106.0,
    signal_type="",
    market_cap_m=500.0,
):
    from scanner.signal import TradeSignal
    return TradeSignal(
        symbol=symbol,
        price=price,
        score=score,
        drop_pct=0.10,
        volume_ratio=1.5,
        window_days=14,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
        hold_days=3,
        signal_type=signal_type,
        market_cap_m=market_cap_m,
    )


def test_save_scan_writes_signal_columns(tmp_db):
    """save_scan 应将 entry/sl/tp/signal_type 写入 scan_results。"""
    from scanner.tracker import save_scan
    sig = _make_signal(entry_price=97.5, stop_loss_price=92.625, take_profit_price=109.5, signal_type="底背离")
    scan_id = save_scan([sig], mode="accumulation")

    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM scan_results WHERE scan_id = ?", (scan_id,)).fetchone()
    conn.close()

    assert row is not None
    assert abs(row["entry_price"] - 97.5) < 0.001
    assert abs(row["stop_loss_price"] - 92.625) < 0.001
    assert abs(row["take_profit_price"] - 109.5) < 0.001
    assert row["signal_type"] == "底背离"


def test_save_scan_returns_scan_id(tmp_db):
    """save_scan 应返回正整数 scan_id。"""
    from scanner.tracker import save_scan
    scan_id = save_scan([_make_signal()], mode="divergence")
    assert isinstance(scan_id, int)
    assert scan_id > 0


def test_query_scan_results_returns_new_columns(tmp_db):
    """query_scan_results 返回的 dict 应包含 entry_price / stop_loss_price / take_profit_price / signal_type。"""
    from scanner.tracker import save_scan, query_scan_results
    save_scan([_make_signal(entry_price=97.5, stop_loss_price=92.0, take_profit_price=106.0)], mode="accumulation")
    rows, total = query_scan_results()
    assert total == 1
    row = rows[0]
    assert "entry_price" in row
    assert "stop_loss_price" in row
    assert "take_profit_price" in row
    assert "signal_type" in row
    assert abs(row["entry_price"] - 97.5) < 0.001
