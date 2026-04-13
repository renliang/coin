from datetime import datetime, timezone

from scanner.new_coin import (
    NewCoinConfig,
    build_new_listings_payload,
    is_leverage_like_base,
    listing_age_days,
    should_exclude_base,
)


def test_is_leverage_like_base():
    assert is_leverage_like_base("BTCUP") is True
    assert is_leverage_like_base("ETHDOWN") is True
    assert is_leverage_like_base("BTC") is False
    assert is_leverage_like_base("PEPE") is False


def test_should_exclude_stable():
    cfg = NewCoinConfig(exclude_stable_bases=True)
    assert should_exclude_base("DAI", cfg) is True
    assert should_exclude_base("BTC", cfg) is False


def test_listing_age_days():
    now = 1_700_000_000_000
    first = now - 10 * 86400 * 1000
    assert listing_age_days(first, now) == 10


def test_new_coin_config_from_mapping_min_avg_key():
    cfg = NewCoinConfig.from_mapping({"min_avg_volume_7d": 12345})
    assert cfg.min_avg_volume_7d_quote == 12345


def test_build_new_listings_payload():
    rows = [{"symbol": "FOO/USDT", "base": "FOO"}]
    fixed = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
    p = build_new_listings_payload(rows, collected_at=fixed)
    assert p["meta"]["schema_version"] == 1
    assert p["meta"]["mode"] == "new_listings"
    assert p["meta"]["result_count"] == 1
    assert p["meta"]["collected_at"] == fixed.isoformat()
    assert p["rows"] == rows
