"""Tests for tracker.py trading DB functions (orders + positions)."""

import os
import sqlite3

import pytest

from scanner import tracker


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Use a temp DB for each test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    return db_path


class TestOrders:
    def test_save_and_retrieve_order(self):
        row_id = tracker.save_order(
            order_id="ORD001", symbol="BTC/USDT", side="buy",
            order_type="limit", price=50000.0, amount=0.1, leverage=10,
        )
        assert row_id == 1
        orders = tracker.get_open_orders()
        assert len(orders) == 1
        assert orders[0]["order_id"] == "ORD001"
        assert orders[0]["status"] == "open"

    def test_update_order_status(self):
        tracker.save_order(
            order_id="ORD002", symbol="ETH/USDT", side="buy",
            order_type="limit", price=3000.0, amount=1.0,
        )
        tracker.update_order_status("ORD002", "filled")
        orders = tracker.get_open_orders()
        assert len(orders) == 0  # no longer open

    def test_filter_by_order_type(self):
        tracker.save_order(order_id="L1", symbol="A/USDT", side="buy",
                           order_type="limit", price=1.0, amount=1.0)
        tracker.save_order(order_id="M1", symbol="B/USDT", side="buy",
                           order_type="market", price=None, amount=1.0)
        limits = tracker.get_open_orders(order_type="limit")
        assert len(limits) == 1
        assert limits[0]["order_id"] == "L1"


class TestPositions:
    def test_save_and_retrieve_position(self):
        row_id = tracker.save_position(
            symbol="BTC/USDT", side="long", entry_price=50000.0,
            size=0.1, leverage=10, score=0.85,
            tp_order_id="TP001", sl_order_id="SL001",
        )
        assert row_id == 1
        positions = tracker.get_open_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "BTC/USDT"
        assert positions[0]["status"] == "open"

    def test_close_position(self):
        tracker.save_position(
            symbol="ETH/USDT", side="long", entry_price=3000.0,
            size=1.0, leverage=5, score=0.7,
        )
        tracker.close_position("ETH/USDT")
        positions = tracker.get_open_positions()
        assert len(positions) == 0

    def test_close_only_target_symbol(self):
        tracker.save_position(symbol="A/USDT", side="long", entry_price=1.0,
                              size=1.0, leverage=5, score=0.7)
        tracker.save_position(symbol="B/USDT", side="long", entry_price=2.0,
                              size=1.0, leverage=5, score=0.8)
        tracker.close_position("A/USDT")
        positions = tracker.get_open_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "B/USDT"

    def test_close_position_with_exit_info(self):
        tracker.save_position(
            symbol="ETH/USDT", side="long", entry_price=3000.0,
            size=1.0, leverage=5, score=0.7, mode="divergence",
        )
        tracker.close_position(
            "ETH/USDT",
            exit_price=3240.0,
            pnl=240.0,
            pnl_pct=0.08,
            exit_reason="tp",
        )
        positions = tracker.get_open_positions()
        assert len(positions) == 0

        trades = tracker.get_closed_trades()
        assert len(trades) == 1
        t = trades[0]
        assert t["exit_price"] == 3240.0
        assert t["pnl"] == 240.0
        assert abs(t["pnl_pct"] - 0.08) < 0.001
        assert t["exit_reason"] == "tp"
        assert t["mode"] == "divergence"

    def test_close_position_backward_compat(self):
        """无 exit 参数时仍正常工作（兼容旧调用）。"""
        tracker.save_position(
            symbol="A/USDT", side="long", entry_price=1.0,
            size=1.0, leverage=5, score=0.7,
        )
        tracker.close_position("A/USDT")
        positions = tracker.get_open_positions()
        assert len(positions) == 0

    def test_get_order_by_id(self):
        tracker.save_order(
            order_id="TP001", symbol="BTC/USDT", side="sell",
            order_type="TAKE_PROFIT_MARKET", price=55000.0, amount=0.1,
        )
        order = tracker.get_order_by_id("TP001")
        assert order is not None
        assert order["symbol"] == "BTC/USDT"
        assert tracker.get_order_by_id("NONEXIST") is None
