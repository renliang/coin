"""Tests for scanner/trader/sizing.py"""

from scanner.trader.sizing import (
    get_position_pct,
    calculate_position,
    calculate_leverage,
)


SCORE_SIZING = {0.6: 0.02, 0.7: 0.03, 0.8: 0.04, 0.9: 0.05}
SCORE_LEVERAGE = {0.6: 0.4, 0.7: 0.6, 0.8: 0.8, 0.9: 1.0}


class TestGetPositionPct:
    def test_exact_threshold(self):
        assert get_position_pct(0.6, SCORE_SIZING) == 0.02
        assert get_position_pct(0.7, SCORE_SIZING) == 0.03
        assert get_position_pct(0.8, SCORE_SIZING) == 0.04
        assert get_position_pct(0.9, SCORE_SIZING) == 0.05

    def test_between_thresholds(self):
        assert get_position_pct(0.65, SCORE_SIZING) == 0.02
        assert get_position_pct(0.85, SCORE_SIZING) == 0.04
        assert get_position_pct(0.99, SCORE_SIZING) == 0.05

    def test_below_min_threshold(self):
        assert get_position_pct(0.5, SCORE_SIZING) == 0.0

    def test_score_1_0(self):
        assert get_position_pct(1.0, SCORE_SIZING) == 0.05


class TestCalculatePosition:
    def test_basic_calculation(self):
        # balance=10000, price=100, score=0.8 → pct=4%, leverage=10
        # notional = 10000 * 0.04 * 10 = 4000
        # amount = 4000 / 100 = 40
        amount = calculate_position(
            balance=10000, price=100, score=0.8, leverage=10,
            score_sizing=SCORE_SIZING,
        )
        assert amount == 40.0

    def test_low_score_returns_zero(self):
        amount = calculate_position(
            balance=10000, price=100, score=0.5, leverage=10,
            score_sizing=SCORE_SIZING,
        )
        assert amount == 0.0

    def test_high_leverage(self):
        # balance=1000, price=0.01, score=0.9 → pct=5%, leverage=125
        # notional = 1000 * 0.05 * 125 = 6250
        # amount = 6250 / 0.01 = 625000
        amount = calculate_position(
            balance=1000, price=0.01, score=0.9, leverage=125,
            score_sizing=SCORE_SIZING,
        )
        assert amount == 625000.0


class TestCalculateLeverage:
    def test_basic_5pct_stop(self):
        # stop_distance=5%, safety=1.5 → safe_max=floor(1/0.075)=13
        # score=0.7 → pct=0.6 → floor(13*0.6)=7
        lev = calculate_leverage(0.05, 0.7, 1.5, 20, 125, SCORE_LEVERAGE)
        assert lev == 7

    def test_high_score_full_leverage(self):
        # stop_distance=5%, safety=1.5 → safe_max=13
        # score=0.9 → pct=1.0 → 13, capped by max_leverage=20 → 13
        lev = calculate_leverage(0.05, 0.9, 1.5, 20, 125, SCORE_LEVERAGE)
        assert lev == 13

    def test_low_score_conservative(self):
        # stop_distance=5%, safety=1.5 → safe_max=13
        # score=0.6 → pct=0.4 → floor(13*0.4)=5
        lev = calculate_leverage(0.05, 0.6, 1.5, 20, 125, SCORE_LEVERAGE)
        assert lev == 5

    def test_capped_by_max_leverage(self):
        # stop_distance=1%, safety=1.5 → safe_max=floor(1/0.015)=66
        # score=0.9 → pct=1.0 → 66, but max_leverage=20 → 20
        lev = calculate_leverage(0.01, 0.9, 1.5, 20, 125, SCORE_LEVERAGE)
        assert lev == 20

    def test_capped_by_exchange_max(self):
        # stop_distance=1%, safety=1.5 → safe_max=66
        # score=0.9 → 66, max_leverage=100, exchange_max=10 → 10
        lev = calculate_leverage(0.01, 0.9, 1.5, 100, 10, SCORE_LEVERAGE)
        assert lev == 10

    def test_wide_stop_returns_zero(self):
        # stop_distance=50%, safety=1.5 → safe_max=floor(1/0.75)=1
        # score=0.6 → pct=0.4 → floor(1*0.4)=0 → 不开仓
        lev = calculate_leverage(0.50, 0.6, 1.5, 20, 125, SCORE_LEVERAGE)
        assert lev == 0

    def test_very_wide_stop_returns_zero(self):
        # stop_distance=80%, safety=1.5 → safe_max=floor(1/1.2)=0
        lev = calculate_leverage(0.80, 0.9, 1.5, 20, 125, SCORE_LEVERAGE)
        assert lev == 0

    def test_zero_stop_distance_returns_zero(self):
        lev = calculate_leverage(0.0, 0.9, 1.5, 20, 125, SCORE_LEVERAGE)
        assert lev == 0

    def test_score_below_min_returns_zero(self):
        lev = calculate_leverage(0.05, 0.5, 1.5, 20, 125, SCORE_LEVERAGE)
        assert lev == 0

    def test_3pct_stop_high_score(self):
        # stop_distance=3%, safety=1.5 → safe_max=floor(1/0.045)=22
        # score=0.85 → pct=0.8 → floor(22*0.8)=17, capped max_leverage=20 → 17
        lev = calculate_leverage(0.03, 0.85, 1.5, 20, 125, SCORE_LEVERAGE)
        assert lev == 17

    def test_10pct_stop_mid_score(self):
        # stop_distance=10%, safety=1.5 → safe_max=floor(1/0.15)=6
        # score=0.7 → pct=0.6 → floor(6*0.6)=3
        lev = calculate_leverage(0.10, 0.7, 1.5, 20, 125, SCORE_LEVERAGE)
        assert lev == 3

    def test_defaults_without_score_leverage(self):
        # Uses DEFAULT_SCORE_LEVERAGE when None
        lev = calculate_leverage(0.05, 0.9, 1.5, 20, 125, None)
        assert lev == 13

    def test_minimum_leverage_is_1(self):
        # stop_distance=15%, safety=1.5 → safe_max=floor(1/0.225)=4
        # score=0.6 → pct=0.4 → floor(4*0.4)=1
        lev = calculate_leverage(0.15, 0.6, 1.5, 20, 125, SCORE_LEVERAGE)
        assert lev == 1
