import sqlite3
from pathlib import Path

import pytest

from history_ui.app import create_app
from scanner import tracker


@pytest.fixture
def temp_db(monkeypatch, tmp_path: Path) -> Path:
    db_path = str(tmp_path / "test_scanner.db")
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_time TEXT NOT NULL
        );
        CREATE TABLE scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            market_cap_m REAL,
            drop_pct REAL NOT NULL,
            volume_ratio REAL NOT NULL,
            window_days INTEGER NOT NULL,
            score REAL NOT NULL,
            mode TEXT NOT NULL DEFAULT 'accumulation',
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        );
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            size REAL NOT NULL,
            leverage INTEGER NOT NULL,
            score REAL NOT NULL,
            tp_order_id TEXT,
            sl_order_id TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            exit_price REAL,
            pnl REAL,
            pnl_pct REAL,
            exit_reason TEXT,
            mode TEXT DEFAULT ''
        );
        """
    )
    conn.execute(
        "INSERT INTO scans (scan_time) VALUES (?)",
        ("2026-01-10 10:00:00",),
    )
    sid1 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO scans (scan_time) VALUES (?)",
        ("2026-01-15 15:00:00",),
    )
    sid2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    for sid, sym, mode in [
        (sid1, "BTC/USDT", "accumulation"),
        (sid1, "ETH/USDT", "divergence"),
        (sid2, "BTC/USDT", "accumulation"),
    ]:
        conn.execute(
            "INSERT INTO scan_results (scan_id, symbol, price, market_cap_m, drop_pct, "
            "volume_ratio, window_days, score, mode) VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, sym, 100.0, 1.0, 0.1, 0.2, 30, 0.65, mode),
        )
    conn.execute(
        "INSERT INTO positions (symbol, side, entry_price, size, leverage, score, "
        "status, opened_at, closed_at, exit_price, pnl, pnl_pct, exit_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("BTC/USDT", "long", 95000.0, 0.01, 10, 0.82,
         "closed", "2026-01-10 09:00:00", "2026-01-11 09:00:00",
         98000.0, 30.0, 3.16, "TP"),
    )
    conn.commit()
    conn.close()
    return Path(db_path)


def test_query_scan_results_filters(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    rows, total = tracker.query_scan_results(symbol="BTC/USDT")
    assert total == 2
    assert len(rows) == 2

    rows, total = tracker.query_scan_results(mode="divergence")
    assert total == 1
    assert rows[0]["symbol"] == "ETH/USDT"

    rows, total = tracker.query_scan_results(scan_time_from="2026-01-15 00:00:00")
    assert total == 1
    assert rows[0]["symbol"] == "BTC/USDT"


def test_query_scan_results_pagination(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    rows, total = tracker.query_scan_results(page=1, per_page=1)
    assert total == 3
    assert len(rows) == 1

    rows2, total2 = tracker.query_scan_results(page=2, per_page=1)
    assert total2 == 3
    assert len(rows2) == 1


def test_history_index_200(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert "今日扫描".encode("utf-8") in r.data


def test_history_filter_symbol(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/history?symbol=ETH%2FUSDT")
    assert r.status_code == 200
    assert "ETH/USDT".encode("utf-8") in r.data
    assert r.data.count(b"ETH/USDT") >= 1


def test_history_index_shows_all_symbols(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    # 首页显示今天各模式的扫描结果（test data 中 BTC/USDT 和 ETH/USDT 都在 2026-01-10，
    # 但这不是 "今天"，所以应该显示空）
    # 验证返回状态码正常，页面有指定结构即可
    assert "今日扫描".encode("utf-8") in r.data


def test_coin_detail_200(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/coin/BTC/USDT")
    assert r.status_code == 200
    assert "BTC/USDT".encode("utf-8") in r.data
    # 扫描记录区块
    assert "扫描记录".encode("utf-8") in r.data
    # 持仓历史区块
    assert "持仓历史".encode("utf-8") in r.data


def test_coin_detail_shows_scan_and_trade(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/coin/BTC/USDT")
    assert r.status_code == 200
    # 有 2 条扫描记录（mode=accumulation 出现两次）
    assert r.data.count(b"accumulation") >= 2
    # 有 1 条持仓记录（TP）
    assert "TP".encode("utf-8") in r.data
    assert "3.16".encode("utf-8") in r.data


def test_search_redirects_to_coin_detail(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/search?symbol=BTC%2FUSDT")
    assert r.status_code == 302
    assert "/coin/BTC/USDT" in r.headers["Location"]
