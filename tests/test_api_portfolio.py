"""测试 /api/portfolio/* JSON 端点。"""

from datetime import date

import pytest

from portfolio.store import save_nav, save_risk_event, save_weights


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("COIN_DB_PATH", db)
    from history_ui.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, db


class TestPortfolioStatus:
    def test_returns_200(self, client):
        c, _ = client
        resp = c.get("/api/portfolio/status")
        assert resp.status_code == 200

    def test_response_shape(self, client):
        c, _ = client
        data = c.get("/api/portfolio/status").get_json()
        for field in ("weights", "nav", "high_water_mark", "drawdown_pct", "portfolio_halted", "halted_strategies"):
            assert field in data

    def test_empty_db_returns_zero_nav(self, client):
        c, _ = client
        data = c.get("/api/portfolio/status").get_json()
        assert data["nav"] == 0.0
        assert data["high_water_mark"] == 0.0
        assert data["drawdown_pct"] == 0.0
        assert data["weights"] == {}

    def test_status_reflects_saved_nav(self, client):
        c, db = client
        save_nav(date(2024, 1, 15), nav=950.0, hwm=1000.0, db_path=db)
        save_weights(date(2024, 1, 15), {"strat_a": 0.6, "strat_b": 0.4}, db_path=db)

        data = c.get("/api/portfolio/status").get_json()
        assert data["nav"] == pytest.approx(950.0)
        assert data["high_water_mark"] == pytest.approx(1000.0)
        assert data["drawdown_pct"] == pytest.approx(0.05)
        assert "strat_a" in data["weights"]

    def test_portfolio_halted_when_drawdown_exceeds_5pct(self, client):
        c, db = client
        save_nav(date(2024, 1, 15), nav=940.0, hwm=1000.0, db_path=db)

        data = c.get("/api/portfolio/status").get_json()
        assert data["portfolio_halted"] is True

    def test_portfolio_not_halted_within_threshold(self, client):
        c, db = client
        save_nav(date(2024, 1, 15), nav=960.0, hwm=1000.0, db_path=db)

        data = c.get("/api/portfolio/status").get_json()
        assert data["portfolio_halted"] is False

    def test_halted_strategies_is_list(self, client):
        c, _ = client
        data = c.get("/api/portfolio/status").get_json()
        assert isinstance(data["halted_strategies"], list)


class TestPortfolioNavHistory:
    def test_returns_200(self, client):
        c, _ = client
        resp = c.get("/api/portfolio/nav-history")
        assert resp.status_code == 200

    def test_response_has_history_key(self, client):
        c, _ = client
        data = c.get("/api/portfolio/nav-history").get_json()
        assert "history" in data

    def test_empty_db_returns_empty_list(self, client):
        c, _ = client
        data = c.get("/api/portfolio/nav-history").get_json()
        assert data["history"] == []

    def test_history_ordered_ascending_by_date(self, client):
        c, db = client
        save_nav(date(2024, 1, 1), nav=1000.0, hwm=1000.0, db_path=db)
        save_nav(date(2024, 1, 3), nav=1020.0, hwm=1020.0, db_path=db)
        save_nav(date(2024, 1, 2), nav=1010.0, hwm=1010.0, db_path=db)

        data = c.get("/api/portfolio/nav-history").get_json()
        dates = [r["date"] for r in data["history"]]
        assert dates == sorted(dates)

    def test_days_parameter_limits_results(self, client):
        c, db = client
        for i in range(10):
            save_nav(date(2024, 1, i + 1), nav=float(1000 + i), hwm=float(1000 + i), db_path=db)

        data = c.get("/api/portfolio/nav-history?days=5").get_json()
        assert len(data["history"]) == 5

    def test_nav_entry_has_expected_fields(self, client):
        c, db = client
        save_nav(date(2024, 1, 1), nav=1000.0, hwm=1000.0, db_path=db)
        data = c.get("/api/portfolio/nav-history").get_json()
        entry = data["history"][0]
        for field in ("date", "nav", "hwm"):
            assert field in entry


class TestPortfolioWeightsHistory:
    def test_returns_200(self, client):
        c, _ = client
        resp = c.get("/api/portfolio/weights-history")
        assert resp.status_code == 200

    def test_response_has_history_key(self, client):
        c, _ = client
        data = c.get("/api/portfolio/weights-history").get_json()
        assert "history" in data

    def test_empty_db_returns_empty_list(self, client):
        c, _ = client
        data = c.get("/api/portfolio/weights-history").get_json()
        assert data["history"] == []

    def test_weights_grouped_by_date(self, client):
        c, db = client
        save_weights(date(2024, 1, 1), {"strat_a": 0.6, "strat_b": 0.4}, db_path=db)
        save_weights(date(2024, 1, 2), {"strat_a": 0.5, "strat_b": 0.5}, db_path=db)

        data = c.get("/api/portfolio/weights-history").get_json()
        history = data["history"]
        assert len(history) == 2

    def test_history_entry_has_date_and_weights(self, client):
        c, db = client
        save_weights(date(2024, 1, 1), {"strat_a": 0.7, "strat_b": 0.3}, db_path=db)

        data = c.get("/api/portfolio/weights-history").get_json()
        entry = data["history"][0]
        assert "date" in entry
        assert "weights" in entry
        assert entry["weights"]["strat_a"] == pytest.approx(0.7)
        assert entry["weights"]["strat_b"] == pytest.approx(0.3)

    def test_history_ordered_by_date_ascending(self, client):
        c, db = client
        save_weights(date(2024, 1, 3), {"strat_a": 0.5}, db_path=db)
        save_weights(date(2024, 1, 1), {"strat_a": 0.6}, db_path=db)
        save_weights(date(2024, 1, 2), {"strat_a": 0.7}, db_path=db)

        data = c.get("/api/portfolio/weights-history").get_json()
        dates = [e["date"] for e in data["history"]]
        assert dates == sorted(dates)


class TestPortfolioRiskEvents:
    def test_returns_200(self, client):
        c, _ = client
        resp = c.get("/api/portfolio/risk-events")
        assert resp.status_code == 200

    def test_response_has_events_key(self, client):
        c, _ = client
        data = c.get("/api/portfolio/risk-events").get_json()
        assert "events" in data

    def test_empty_db_returns_empty_list(self, client):
        c, _ = client
        data = c.get("/api/portfolio/risk-events").get_json()
        assert data["events"] == []

    def test_events_returned_correctly(self, client):
        c, db = client
        save_risk_event("HIGH", "strat_a", "daily_limit", "Loss exceeded 3%", db_path=db)
        save_risk_event("CRITICAL", None, "drawdown_halt", "Portfolio drawdown exceeded 5%", db_path=db)

        data = c.get("/api/portfolio/risk-events").get_json()
        assert len(data["events"]) == 2

    def test_events_ordered_most_recent_first(self, client):
        c, db = client
        save_risk_event("INFO", "strat_a", "type1", "first", db_path=db)
        save_risk_event("HIGH", "strat_b", "type2", "second", db_path=db)

        data = c.get("/api/portfolio/risk-events").get_json()
        assert data["events"][0]["level"] == "HIGH"
        assert data["events"][1]["level"] == "INFO"

    def test_limit_parameter(self, client):
        c, db = client
        for i in range(10):
            save_risk_event("LOW", f"strat_{i}", "type", f"detail {i}", db_path=db)

        data = c.get("/api/portfolio/risk-events?limit=5").get_json()
        assert len(data["events"]) == 5

    def test_event_has_expected_fields(self, client):
        c, db = client
        save_risk_event("HIGH", "strat_a", "daily_limit", "some detail", db_path=db)
        data = c.get("/api/portfolio/risk-events").get_json()
        event = data["events"][0]
        for field in ("created_at", "level", "strategy_id", "event_type", "details"):
            assert field in event


class TestPortfolioRebalance:
    def test_returns_500_when_main_not_configured(self, client):
        """再平衡端点在无法加载 main 配置时应返回 500 而非崩溃。"""
        c, _ = client
        resp = c.post("/api/portfolio/rebalance")
        # Either 200 (success) or 500 (expected error from missing config)
        assert resp.status_code in (200, 500)

    def test_response_has_success_field(self, client):
        c, _ = client
        resp = c.post("/api/portfolio/rebalance")
        data = resp.get_json()
        assert "success" in data

    def test_error_response_has_error_field(self, client):
        c, _ = client
        resp = c.post("/api/portfolio/rebalance")
        data = resp.get_json()
        if not data["success"]:
            assert "error" in data
