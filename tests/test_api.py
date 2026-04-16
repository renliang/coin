"""测试 /api/* JSON 端点。"""

import pytest

from api.app import create_app
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    app = create_app()
    yield TestClient(app)


class TestDashboard:
    def test_returns_200(self, client):
        resp = client.get("/api/dashboard")
        assert resp.status_code == 200

    def test_response_shape(self, client):
        data = client.get("/api/dashboard").json()
        assert "kpi" in data
        assert "top_signals" in data
        assert "positions" in data
        assert "hit_rate_7d" in data
        assert "signal_counts" in data

    def test_kpi_fields(self, client):
        kpi = client.get("/api/dashboard").json()["kpi"]
        for key in ("today_signals", "active_positions", "today_pnl_pct", "win_rate", "total_trades"):
            assert key in kpi

    def test_hit_rate_7d_length(self, client):
        data = client.get("/api/dashboard").json()
        assert len(data["hit_rate_7d"]) == 7


class TestSignals:
    def test_returns_200(self, client):
        resp = client.get("/api/signals")
        assert resp.status_code == 200

    def test_pagination(self, client):
        data = client.get("/api/signals?page=1&per_page=5").json()
        assert "data" in data
        assert "total" in data
        assert "page" in data
        assert data["page"] == 1
        assert len(data["data"]) <= 5

    def test_mode_filter(self, client):
        data = client.get("/api/signals?mode=accumulation").json()
        for row in data["data"]:
            assert row["mode"] == "accumulation"


class TestPositions:
    def test_active_returns_200(self, client):
        resp = client.get("/api/positions")
        assert resp.status_code == 200
        assert "data" in resp.json()

    def test_closed_returns_200(self, client):
        resp = client.get("/api/positions/closed")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "total" in data


class TestPerformance:
    def test_returns_200(self, client):
        resp = client.get("/api/performance")
        assert resp.status_code == 200

    def test_response_shape(self, client):
        data = client.get("/api/performance").json()
        assert "overall" in data
        assert "by_mode" in data
        assert "by_score" in data
        assert "by_month" in data
        assert "cumulative_pnl" in data

    def test_overall_fields(self, client):
        overall = client.get("/api/performance").json()["overall"]
        for key in ("total", "wins", "win_rate", "avg_pnl_pct", "profit_factor"):
            assert key in overall


class TestCoinDetail:
    def test_returns_200(self, client):
        resp = client.get("/api/coin/BTC/USDT")
        assert resp.status_code == 200

    def test_response_shape(self, client):
        data = client.get("/api/coin/BTC/USDT").json()
        assert data["symbol"] == "BTC/USDT"
        assert "scans" in data
        assert "trades" in data


class TestScan:
    def test_status_returns_200(self, client):
        resp = client.get("/api/scan/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data


class TestSpaServing:
    def test_spa_index(self, client):
        resp = client.get("/app/")
        # SPA may not be built in test env; accept 200 or 404
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            assert "<div id=\"root\">" in resp.text

    def test_spa_subroute(self, client):
        resp = client.get("/app/signals")
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            assert "<div id=\"root\">" in resp.text
