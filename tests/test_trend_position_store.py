"""趋势跟踪持仓状态 DAO 测试。"""
from __future__ import annotations

import pytest

import scanner.trend_position_store as store


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """每个测试独立 DB。"""
    db_path = str(tmp_path / "trend.db")
    monkeypatch.setattr(store, "DB_PATH", db_path)
    store.init_schema()
    yield db_path


def test_open_and_get_position():
    pos = store.open_position(
        symbol="X/USDT",
        entry_price=100.0,
        units=0.5,
        atr_at_open=5.0,
        opened_at="2026-04-23",
    )
    assert pos.symbol == "X/USDT"
    assert pos.levels == 1
    assert pos.entries[0].price == 100.0
    assert pos.entries[0].units == 0.5
    assert pos.trailing_high == 100.0

    got = store.get_position("X/USDT")
    assert got is not None
    assert got.symbol == "X/USDT"


def test_get_position_returns_none_when_missing():
    assert store.get_position("GHOST/USDT") is None


def test_add_pyramid_appends_entry():
    store.open_position("X/USDT", 100.0, 0.5, 5.0, "2026-04-23")
    store.add_pyramid("X/USDT", price=110.0, units=0.45, date="2026-04-30")
    p = store.get_position("X/USDT")
    assert p.levels == 2
    assert p.entries[-1].price == 110.0
    assert p.entries[-1].units == 0.45
    # avg_price = (100*0.5 + 110*0.45) / (0.5+0.45) ≈ 104.74
    assert 104 < p.avg_price < 105.5


def test_update_trailing_high_only_raises():
    store.open_position("X/USDT", 100.0, 0.5, 5.0, "2026-04-23")
    store.update_trailing_high("X/USDT", 105.0)
    assert store.get_position("X/USDT").trailing_high == 105.0
    # 不应下调
    store.update_trailing_high("X/USDT", 90.0)
    assert store.get_position("X/USDT").trailing_high == 105.0


def test_close_position_removes_from_open_list():
    store.open_position("X/USDT", 100.0, 0.5, 5.0, "2026-04-23")
    store.open_position("Y/USDT", 50.0, 2.0, 2.0, "2026-04-23")
    store.close_position("X/USDT", close_price=95.0, reason="chandelier",
                          closed_at="2026-04-28")
    openset = {p.symbol for p in store.get_open_positions()}
    assert openset == {"Y/USDT"}
    x = store.get_position("X/USDT")
    assert x.status == "closed"
    assert x.close_price == 95.0
    assert x.close_reason == "chandelier"
    # PnL = (95 - 100)/100 = -5%
    assert x.realized_pnl_pct == pytest.approx(-0.05)


def test_get_open_positions_empty():
    assert store.get_open_positions() == []


def test_position_avg_price_and_levels():
    store.open_position("X/USDT", 100.0, 1.0, 5.0, "2026-04-23")
    store.add_pyramid("X/USDT", 110.0, 1.0, "2026-04-24")
    store.add_pyramid("X/USDT", 125.0, 1.0, "2026-04-25")
    p = store.get_position("X/USDT")
    assert p.levels == 3
    # avg = (100 + 110 + 125) / 3
    assert p.avg_price == pytest.approx((100 + 110 + 125) / 3)
    assert p.total_units == pytest.approx(3.0)


def test_close_position_pnl_with_pyramid():
    store.open_position("X/USDT", 100.0, 1.0, 5.0, "2026-04-23")
    store.add_pyramid("X/USDT", 120.0, 1.0, "2026-04-25")
    # 平仓 @ 130: total_pnl = (130-100)*1 + (130-120)*1 = 30 + 10 = 40
    # 总成本 = 100*1 + 120*1 = 220
    # PnL% = 40/220 ≈ 18.2%
    store.close_position("X/USDT", close_price=130.0, reason="chandelier",
                          closed_at="2026-05-01")
    p = store.get_position("X/USDT")
    assert p.realized_pnl_pct == pytest.approx(40.0 / 220.0, rel=1e-6)


def test_cannot_open_duplicate_open_position():
    store.open_position("X/USDT", 100.0, 0.5, 5.0, "2026-04-23")
    with pytest.raises(ValueError):
        store.open_position("X/USDT", 105.0, 0.5, 5.0, "2026-04-24")
