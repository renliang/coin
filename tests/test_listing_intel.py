from datetime import datetime, timezone
from unittest.mock import patch

from scanner.listing_intel import (
    ListingIntelConfig,
    compute_l2c_dd_score,
    enrich_new_listings_payload,
    fetch_binance_listing_articles,
    merge_l2a_manual,
    pick_announcement_for_base,
)


def test_pick_announcement_for_base_match():
    articles = [
        {
            "title": "Binance Will List Pepe (PEPE) in Innovation Zone",
            "code": "announce-pepe-1",
            "releaseDate": 1_704_067_200_000,
        },
    ]
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    got = pick_announcement_for_base("PEPE", articles, detected_at=dt.isoformat())
    assert got["announcement_source"] == "binance_official"
    assert got["announcement_confidence"] in ("high", "medium")
    assert got["announcement_url"] and "announceDetail" in got["announcement_url"]
    assert got["announcement_title_snippet"]
    assert got["claimed_listing_at"]


def test_pick_announcement_for_base_no_match():
    articles = [{"title": "Some unrelated post", "code": "x"}]
    got = pick_announcement_for_base("PEPE", articles, detected_at="")
    assert got["announcement_url"] is None


def test_compute_l2c_dd_score():
    row = {
        "quote_volume_24h": 2_000_000.0,
        "market_cap_usd": 10_000_000.0,
        "listing_days": 10,
        "announcement_url": "https://binance.com/x",
        "announcement_confidence": "high",
        "onchain_first_pool_ts_ms": 1,
    }
    cfg = ListingIntelConfig(trust_tier_high_min=75, trust_tier_mid_min=55)
    compute_l2c_dd_score(row, cfg)
    assert 0 <= row["dd_score"] <= 100
    assert row["trust_tier"] in ("tier_1", "tier_2", "tier_3")
    assert "volume_pts" in row["score_components"]


def test_merge_l2a_manual():
    overlay = {
        "ZZZ": {
            "base": "ZZZ",
            "announcement_title_snippet": "Manual note",
            "announcement_url": "https://example.com/a",
            "claimed_listing_at": "2026-03-01T00:00:00+00:00",
            "announcement_confidence": "high",
        },
    }
    row: dict = {"base": "ZZZ"}
    merge_l2a_manual(overlay, row)
    assert row["announcement_source"] == "manual"
    assert row["announcement_url"] == "https://example.com/a"


def test_enrich_new_listings_payload_l2c_only():
    cfg = ListingIntelConfig(
        enabled=True,
        l2a_binance_announcements=False,
        l2b_dexscreener=False,
        l2c_dd_score=True,
        manual_overlay_csv=None,
    )
    payload = {
        "meta": {"schema_version": 1, "mode": "new_listings", "result_count": 1},
        "rows": [{
            "symbol": "FOO/USDT",
            "base": "FOO",
            "listing_days": 3,
            "listing_first_ts_ms": 1_700_000_000_000,
            "price": 1.0,
            "quote_volume_24h": 1_000_000.0,
            "market_cap_usd": 0.0,
        }],
    }
    out = enrich_new_listings_payload(payload, cfg)
    assert out["meta"]["schema_version"] == 2
    assert "l2c" in out["meta"]["extends"]
    assert "dd_score" in out["rows"][0]


@patch("scanner.listing_intel.http_get_json")
def test_enrich_with_l2b(mock_get):
    mock_get.return_value = (
        {
            "pairs": [
                {
                    "chainId": "bsc",
                    "dexId": "pancakeswap",
                    "pairAddress": "0xp",
                    "pairCreatedAt": 1_700_000_000_000,
                    "baseToken": {"symbol": "FOO", "address": "0xtoken"},
                },
                {
                    "chainId": "eth",
                    "dexId": "uniswap",
                    "pairCreatedAt": 1_600_000_000_000,
                    "baseToken": {"symbol": "FOO", "address": "0xolder"},
                },
            ],
        },
        None,
    )
    cfg = ListingIntelConfig(
        enabled=True,
        l2a_binance_announcements=False,
        l2b_dexscreener=True,
        l2c_dd_score=False,
        dexscreener_delay=0,
    )
    payload = {
        "meta": {},
        "rows": [{"base": "FOO", "symbol": "FOO/USDT", "listing_first_ts_ms": 1}],
    }
    out = enrich_new_listings_payload(payload, cfg)
    r0 = out["rows"][0]
    assert r0.get("onchain_chain") == "eth"
    assert r0.get("onchain_source") == "dexscreener"
    assert out["meta"]["intel_stats"]["l2b_matched"] == 1


@patch("scanner.listing_intel.http_post_json")
def test_fetch_binance_listing_articles_parses(mock_post):
    mock_post.return_value = (
        {
            "data": {
                "articles": [
                    {"title": "Test", "code": "c1"},
                ],
            },
        },
        None,
    )
    cfg = ListingIntelConfig(l2a_max_pages=1, l2a_page_size=10, request_delay=0)
    arts, errs = fetch_binance_listing_articles(cfg)
    assert len(arts) == 1
    assert not errs


def test_enrich_disabled_returns_same():
    cfg = ListingIntelConfig(enabled=False)
    payload = {"meta": {"a": 1}, "rows": [{"x": 1}]}
    assert enrich_new_listings_payload(payload, cfg) is payload
