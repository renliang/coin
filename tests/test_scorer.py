from scanner.detector import DetectionResult
from scanner.scorer import score_result, rank_results


class TestScoring:
    def test_perfect_pattern_high_score(self):
        result = DetectionResult(
            volume_pass=True, trend_pass=True, drop_pass=True, slow_pass=True,
            matched=True,
            volume_ratio=0.3,
            drop_pct=0.10,
            r_squared=0.95,
            max_daily_pct=0.01,
            window_days=14,
        )
        score = score_result(result, drop_min=0.05, drop_max=0.15, max_daily_change=0.05)
        assert score > 0.7

    def test_weak_pattern_low_score(self):
        result = DetectionResult(
            volume_pass=True, trend_pass=True, drop_pass=True, slow_pass=True,
            matched=True,
            volume_ratio=0.48,
            drop_pct=0.14,
            r_squared=0.3,
            max_daily_pct=0.045,
            window_days=7,
        )
        score = score_result(result, drop_min=0.05, drop_max=0.15, max_daily_change=0.05)
        assert score < 0.5

    def test_unmatched_scores_zero(self):
        result = DetectionResult(
            volume_pass=False, trend_pass=True, drop_pass=True, slow_pass=True,
            matched=False,
            volume_ratio=0.8, drop_pct=0.10, r_squared=0.9,
            max_daily_pct=0.02, window_days=14,
        )
        score = score_result(result, drop_min=0.05, drop_max=0.15, max_daily_change=0.05)
        assert score == 0.0


class TestRanking:
    def test_rank_by_score_descending(self):
        items = [
            {"symbol": "AAA/USDT", "score": 0.5},
            {"symbol": "BBB/USDT", "score": 0.9},
            {"symbol": "CCC/USDT", "score": 0.7},
        ]
        ranked = rank_results(items, top_n=3)
        assert [r["symbol"] for r in ranked] == ["BBB/USDT", "CCC/USDT", "AAA/USDT"]

    def test_rank_top_n(self):
        items = [
            {"symbol": "A", "score": 0.9},
            {"symbol": "B", "score": 0.8},
            {"symbol": "C", "score": 0.7},
        ]
        ranked = rank_results(items, top_n=2)
        assert len(ranked) == 2
