"""Tests for scanner/optimize/feedback.py — signal_outcomes table + backfill."""

import sqlite3
from datetime import date, timedelta

import pytest

from scanner.optimize.feedback import (
    backfill_return,
    ensure_outcomes_table,
    get_labeled_outcomes,
    get_pending_outcomes,
    record_signal_outcome,
)


def _db(tmp_path):
    return str(tmp_path / "test.db")


def test_create_table(tmp_path):
    db = _db(tmp_path)
    ensure_outcomes_table(db)
    conn = sqlite3.connect(db)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='signal_outcomes'"
    )
    assert cur.fetchone() is not None, "signal_outcomes table should exist"
    conn.close()


def test_record_and_query(tmp_path):
    db = _db(tmp_path)
    ensure_outcomes_table(db)

    # signal_date 4 days ago so it passes the 3d threshold
    signal_date = (date.today() - timedelta(days=4)).isoformat()
    row_id = record_signal_outcome(
        db,
        scan_result_id=1,
        symbol="BTC/USDT",
        signal_date=signal_date,
        signal_price=30000.0,
        features_json='{"rsi": 45}',
        btc_price=30000.0,
    )
    assert row_id is not None

    pending = get_pending_outcomes(db)
    assert len(pending) == 1
    assert pending[0]["symbol"] == "BTC/USDT"
    assert pending[0]["signal_price"] == 30000.0


def test_backfill_return(tmp_path):
    db = _db(tmp_path)
    ensure_outcomes_table(db)

    signal_date = (date.today() - timedelta(days=10)).isoformat()
    row_id = record_signal_outcome(
        db,
        scan_result_id=2,
        symbol="ETH/USDT",
        signal_date=signal_date,
        signal_price=2000.0,
        features_json=None,
        btc_price=None,
    )
    assert row_id is not None

    backfill_return(db, row_id, "return_7d", 0.05)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT return_7d, collected_at FROM signal_outcomes WHERE id=?", (row_id,)
    ).fetchone()
    conn.close()

    assert abs(row["return_7d"] - 0.05) < 1e-9
    assert row["collected_at"] is not None


def test_get_labeled_outcomes(tmp_path):
    db = _db(tmp_path)
    ensure_outcomes_table(db)

    signal_date = (date.today() - timedelta(days=8)).isoformat()
    row_id = record_signal_outcome(
        db,
        scan_result_id=3,
        symbol="SOL/USDT",
        signal_date=signal_date,
        signal_price=100.0,
        features_json=None,
        btc_price=29000.0,
    )

    # Before backfilling return_7d, labeled should be empty
    assert get_labeled_outcomes(db) == []

    backfill_return(db, row_id, "return_7d", -0.02)

    labeled = get_labeled_outcomes(db)
    assert len(labeled) == 1
    assert labeled[0]["symbol"] == "SOL/USDT"


def test_no_duplicate_record(tmp_path):
    db = _db(tmp_path)
    ensure_outcomes_table(db)

    kwargs = dict(
        db_path=db,
        scan_result_id=5,
        symbol="ADA/USDT",
        signal_date="2026-01-01",
        signal_price=0.5,
        features_json=None,
        btc_price=None,
    )

    first_id = record_signal_outcome(**kwargs)
    second_id = record_signal_outcome(**kwargs)

    assert first_id is not None
    assert second_id is None  # duplicate ignored

    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0]
    conn.close()
    assert count == 1
