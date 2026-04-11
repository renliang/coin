import json
import os

from scanner.stats import (
    compute_stats,
    compute_stats_by_mode,
    compute_stats_by_month,
    compute_stats_by_score_tier,
    export_stats_json,
    format_stats_report,
)


def test_compute_stats_basic():
    """基本统计：3 笔交易，2 赢 1 亏。"""
    trades = [
        {"pnl_pct": 0.08, "pnl": 80.0},
        {"pnl_pct": 0.05, "pnl": 50.0},
        {"pnl_pct": -0.03, "pnl": -30.0},
    ]
    s = compute_stats(trades)
    assert s["total"] == 3
    assert s["wins"] == 2
    assert abs(s["win_rate"] - 2 / 3) < 0.01
    assert abs(s["avg_pnl_pct"] - (0.08 + 0.05 - 0.03) / 3) < 0.001
    assert abs(s["profit_factor"] - 130 / 30) < 0.01
    assert s["max_gain"] == 0.08
    assert s["max_loss"] == -0.03


def test_compute_stats_empty():
    """空列表返回零值。"""
    s = compute_stats([])
    assert s["total"] == 0
    assert s["win_rate"] == 0
    assert s["profit_factor"] == 0


def test_compute_stats_all_wins():
    """全赢时 profit_factor 用总盈利代替（除零保护）。"""
    trades = [
        {"pnl_pct": 0.05, "pnl": 50.0},
        {"pnl_pct": 0.10, "pnl": 100.0},
    ]
    s = compute_stats(trades)
    assert s["win_rate"] == 1.0
    assert s["profit_factor"] == 150.0
    assert s["max_loss"] == 0


def test_compute_stats_by_mode():
    trades = [
        {"pnl_pct": 0.08, "pnl": 80.0, "mode": "divergence"},
        {"pnl_pct": -0.03, "pnl": -30.0, "mode": "divergence"},
        {"pnl_pct": 0.05, "pnl": 50.0, "mode": "accumulation"},
    ]
    by_mode = compute_stats_by_mode(trades)
    assert "divergence" in by_mode
    assert "accumulation" in by_mode
    assert by_mode["divergence"]["total"] == 2
    assert by_mode["accumulation"]["total"] == 1
    assert by_mode["accumulation"]["win_rate"] == 1.0


def test_compute_stats_by_score_tier():
    trades = [
        {"pnl_pct": 0.10, "pnl": 100.0, "score": 0.85},
        {"pnl_pct": 0.05, "pnl": 50.0, "score": 0.75},
        {"pnl_pct": -0.02, "pnl": -20.0, "score": 0.65},
    ]
    by_score = compute_stats_by_score_tier(trades)
    assert by_score["0.8+"]["total"] == 1
    assert by_score["0.8+"]["win_rate"] == 1.0
    assert by_score["0.7-0.8"]["total"] == 1
    assert by_score["0.6-0.7"]["total"] == 1


def test_compute_stats_by_month():
    trades = [
        {"pnl_pct": 0.08, "pnl": 80.0, "closed_at": "2026-04-05 10:00:00"},
        {"pnl_pct": -0.03, "pnl": -30.0, "closed_at": "2026-04-10 10:00:00"},
        {"pnl_pct": 0.05, "pnl": 50.0, "closed_at": "2026-03-20 10:00:00"},
    ]
    by_month = compute_stats_by_month(trades)
    assert "2026-04" in by_month
    assert "2026-03" in by_month
    assert by_month["2026-04"]["total"] == 2
    assert by_month["2026-03"]["total"] == 1


def test_format_stats_report_contains_key_info():
    overall = {"total": 10, "wins": 7, "win_rate": 0.7, "avg_pnl_pct": 0.03, "profit_factor": 1.5, "max_gain": 0.1, "max_loss": -0.05}
    by_mode = {"divergence": {"total": 10, "wins": 7, "win_rate": 0.7, "avg_pnl_pct": 0.03, "profit_factor": 1.5, "max_gain": 0.1, "max_loss": -0.05}}
    by_score = {"0.8+": {"total": 5, "wins": 4, "win_rate": 0.8, "avg_pnl_pct": 0.04, "profit_factor": 2.0, "max_gain": 0.1, "max_loss": -0.02}}
    by_month = {"2026-04": {"total": 10, "wins": 7, "win_rate": 0.7, "avg_pnl_pct": 0.03, "profit_factor": 1.5, "max_gain": 0.1, "max_loss": -0.05}}

    report = format_stats_report(overall, by_mode, by_score, by_month)
    assert "70.0%" in report
    assert "divergence" in report
    assert "0.8+" in report
    assert "2026-04" in report


def test_export_stats_json(tmp_path):
    overall = {"total": 5, "wins": 3, "win_rate": 0.6, "avg_pnl_pct": 0.02, "profit_factor": 1.2, "max_gain": 0.05, "max_loss": -0.03}
    trades = [{"symbol": "BTC/USDT", "pnl_pct": 0.05}]

    path = export_stats_json(overall, {}, {}, {}, trades=trades, output_dir=str(tmp_path))
    assert os.path.exists(path)
    with open(path) as f:
        data = json.load(f)
    assert data["overall"]["total"] == 5
    assert len(data["trades"]) == 1
