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
    assert "扫描历史".encode("utf-8") in r.data


def test_history_filter_symbol(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/?symbol=ETH%2FUSDT")
    assert r.status_code == 200
    assert "ETH/USDT".encode("utf-8") in r.data
    assert r.data.count(b"ETH/USDT") >= 1


def test_history_page2(temp_db, monkeypatch):
    monkeypatch.setattr(tracker, "DB_PATH", str(temp_db))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.get("/?per_page=1&page=2")
    assert r.status_code == 200
    assert "第 2 / 3 页".encode("utf-8") in r.data
