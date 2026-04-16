"""Smoke tests for FastAPI scanner endpoints."""

import pytest
from fastapi.testclient import TestClient

from api.app import create_app


@pytest.fixture()
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


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
        for key in (
            "today_signals",
            "active_positions",
            "today_pnl_pct",
            "win_rate",
            "total_trades",
        ):
            assert key in kpi

    def test_hit_rate_7d_length(self, client):
        data = client.get("/api/dashboard").json()
        assert len(data["hit_rate_7d"]) == 7


class TestSignals:
    def test_returns_200(self, client):
        resp = client.get("/api/signals")
        assert resp.status_code == 200

    def test_pagination_keys(self, client):
        data = client.get("/api/signals?page=1&per_page=5").json()
        assert "data" in data
        assert "total" in data
        assert "page" in data
        assert data["page"] == 1


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


class TestScanStatus:
    def test_returns_200(self, client):
        resp = client.get("/api/scan/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data


class TestConfig:
    def test_returns_200(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
