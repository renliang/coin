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


def test_query_scan_results_mode_filter(tmp_db):
    """mode 筛选应只返回对应模式的记录。"""
    from scanner.tracker import save_scan, query_scan_results
    save_scan([_make_signal("A/USDT")], mode="accumulation")
    save_scan([_make_signal("B/USDT")], mode="divergence")

    rows, total = query_scan_results(mode="accumulation")
    assert total == 1
    assert rows[0]["symbol"] == "A/USDT"


def test_get_today_scans_returns_latest_scan(tmp_db):
    """get_today_scans 应返回今天该模式最新一次扫描的信号列表。"""
    from scanner.tracker import save_scan, get_today_scans
    save_scan([_make_signal("A/USDT"), _make_signal("B/USDT")], mode="accumulation")
    save_scan([_make_signal("C/USDT")], mode="accumulation")  # 第二次扫描

    rows = get_today_scans("accumulation")
    # 应返回最新一次扫描（scan_id 最大），即只有 C/USDT
    assert len(rows) == 1
    assert rows[0]["symbol"] == "C/USDT"


def test_get_today_scans_empty_for_other_mode(tmp_db):
    """get_today_scans 对没有扫描记录的模式返回空列表。"""
    from scanner.tracker import save_scan, get_today_scans
    save_scan([_make_signal("A/USDT")], mode="accumulation")

    rows = get_today_scans("divergence")
    assert rows == []


def test_get_today_scans_includes_signal_columns(tmp_db):
    """get_today_scans 返回的 dict 包含 entry_price / stop_loss_price / take_profit_price。"""
    from scanner.tracker import save_scan, get_today_scans
    save_scan([_make_signal(entry_price=97.5, stop_loss_price=92.0, take_profit_price=109.0)], mode="divergence")

    rows = get_today_scans("divergence")
    assert len(rows) == 1
    assert abs(rows[0]["entry_price"] - 97.5) < 0.001
    assert abs(rows[0]["stop_loss_price"] - 92.0) < 0.001
    assert abs(rows[0]["take_profit_price"] - 109.0) < 0.001
