"""Tests for portfolio SQLite store."""
from datetime import date

import pytest

from portfolio.store import (
    query_latest_weights,
    query_nav_history,
    query_risk_events,
    save_nav,
    save_risk_event,
    save_weights,
)


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "test_portfolio.db")


class TestNavStore:
    def test_save_and_query_nav(self, db):
        d = date(2024, 1, 15)
        save_nav(d, nav=1050.0, hwm=1100.0, db_path=db)
        history = query_nav_history(limit=10, db_path=db)
        assert len(history) == 1
        assert history[0]["date"] == "2024-01-15"
        assert history[0]["nav"] == 1050.0
        assert history[0]["hwm"] == 1100.0

    def test_insert_or_replace(self, db):
        d = date(2024, 1, 15)
        save_nav(d, nav=1000.0, hwm=1000.0, db_path=db)
        save_nav(d, nav=1050.0, hwm=1050.0, db_path=db)
        history = query_nav_history(db_path=db)
        assert len(history) == 1
        assert history[0]["nav"] == 1050.0

    def test_query_ordered_desc(self, db):
        save_nav(date(2024, 1, 1), nav=1000.0, hwm=1000.0, db_path=db)
        save_nav(date(2024, 1, 3), nav=1020.0, hwm=1020.0, db_path=db)
        save_nav(date(2024, 1, 2), nav=1010.0, hwm=1010.0, db_path=db)
        history = query_nav_history(db_path=db)
        assert history[0]["date"] == "2024-01-03"
        assert history[1]["date"] == "2024-01-02"
        assert history[2]["date"] == "2024-01-01"

    def test_query_limit(self, db):
        for i in range(5):
            save_nav(date(2024, 1, i + 1), nav=float(1000 + i), hwm=float(1000 + i), db_path=db)
        history = query_nav_history(limit=3, db_path=db)
        assert len(history) == 3

    def test_empty_history(self, db):
        history = query_nav_history(db_path=db)
        assert history == []


class TestWeightsStore:
    def test_save_and_query_weights(self, db):
        d = date(2024, 1, 15)
        weights = {"strat_a": 0.6, "strat_b": 0.4}
        save_weights(d, weights, db_path=db)
        result = query_latest_weights(db_path=db)
        assert result == weights

    def test_save_replaces_same_date(self, db):
        d = date(2024, 1, 15)
        save_weights(d, {"strat_a": 0.5, "strat_b": 0.5}, db_path=db)
        save_weights(d, {"strat_a": 0.7, "strat_b": 0.3}, db_path=db)
        result = query_latest_weights(db_path=db)
        assert abs(result["strat_a"] - 0.7) < 1e-9
        assert abs(result["strat_b"] - 0.3) < 1e-9

    def test_query_latest_returns_most_recent_date(self, db):
        save_weights(date(2024, 1, 1), {"strat_a": 0.5, "strat_b": 0.5}, db_path=db)
        save_weights(date(2024, 1, 3), {"strat_x": 0.8, "strat_y": 0.2}, db_path=db)
        save_weights(date(2024, 1, 2), {"strat_a": 0.4, "strat_b": 0.6}, db_path=db)
        result = query_latest_weights(db_path=db)
        assert "strat_x" in result
        assert "strat_y" in result

    def test_empty_weights(self, db):
        result = query_latest_weights(db_path=db)
        assert result == {}


class TestRiskEventsStore:
    def test_save_and_query_risk_event(self, db):
        save_risk_event(
            level="HIGH",
            strategy_id="strat_a",
            event_type="daily_limit",
            details="Loss exceeded 3%",
            db_path=db,
        )
        events = query_risk_events(db_path=db)
        assert len(events) == 1
        assert events[0]["level"] == "HIGH"
        assert events[0]["strategy_id"] == "strat_a"
        assert events[0]["event_type"] == "daily_limit"
        assert events[0]["details"] == "Loss exceeded 3%"

    def test_multiple_events_ordered_desc(self, db):
        save_risk_event("INFO", "strat_a", "type1", "detail1", db_path=db)
        save_risk_event("CRITICAL", "strat_b", "type2", "detail2", db_path=db)
        events = query_risk_events(db_path=db)
        assert events[0]["level"] == "CRITICAL"
        assert events[1]["level"] == "INFO"

    def test_risk_event_limit(self, db):
        for i in range(10):
            save_risk_event("LOW", f"strat_{i}", "type", "detail", db_path=db)
        events = query_risk_events(limit=5, db_path=db)
        assert len(events) == 5

    def test_risk_event_no_strategy(self, db):
        save_risk_event(
            level="CRITICAL",
            strategy_id=None,
            event_type="drawdown_halt",
            details="Portfolio drawdown exceeded 5%",
            db_path=db,
        )
        events = query_risk_events(db_path=db)
        assert len(events) == 1
        assert events[0]["strategy_id"] is None

    def test_empty_risk_events(self, db):
        events = query_risk_events(db_path=db)
        assert events == []
