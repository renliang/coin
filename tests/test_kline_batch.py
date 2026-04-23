"""并发化 fetch_klines_batch 的测试。"""
import time

import pandas as pd
import pytest

from scanner import kline as kline_module


def _df(n: int = 30) -> pd.DataFrame:
    """构造 n 行的合法 K 线 DataFrame。"""
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
            "open": [1.0] * n,
            "high": [1.0] * n,
            "low": [1.0] * n,
            "close": [1.0] * n,
            "volume": [1.0] * n,
        }
    )


@pytest.fixture
def stub_fetch(monkeypatch):
    """monkeypatch fetch_klines, 返回一个可控的 stub。"""
    calls: list[tuple[str, int]] = []

    def fake_fetch(symbol: str, days: int = 30, use_futures: bool = True):
        calls.append((symbol, days))
        if symbol.startswith("BAD"):
            return None
        if symbol.startswith("SHORT"):
            return _df(3)  # <7 行, 应被丢弃
        return _df(days)

    monkeypatch.setattr(kline_module, "fetch_klines", fake_fetch)
    return calls


def test_returns_mapping_of_valid_symbols(stub_fetch):
    symbols = ["A/USDT", "B/USDT", "BAD1/USDT", "SHORT/USDT", "C/USDT"]
    out = kline_module.fetch_klines_batch(symbols, days=30)
    assert set(out.keys()) == {"A/USDT", "B/USDT", "C/USDT"}
    for df in out.values():
        assert len(df) == 30


def test_passes_through_days(stub_fetch):
    kline_module.fetch_klines_batch(["A/USDT"], days=90)
    assert stub_fetch == [("A/USDT", 90)]


def test_accepts_legacy_delay_kwarg(stub_fetch):
    """调用方签名兼容: 旧的 delay=0.5 入参不能破坏。"""
    out = kline_module.fetch_klines_batch(["A/USDT"], days=30, delay=0.5)
    assert "A/USDT" in out


def test_concurrent_faster_than_serial(monkeypatch):
    """并发路径下 N 个慢请求的总耗时应远小于 N * 单次耗时。"""

    def slow_fetch(symbol: str, days: int = 30, use_futures: bool = True):
        time.sleep(0.1)
        return _df(days)

    monkeypatch.setattr(kline_module, "fetch_klines", slow_fetch)

    n = 10
    t0 = time.perf_counter()
    out = kline_module.fetch_klines_batch([f"S{i}/USDT" for i in range(n)], days=30, workers=5)
    elapsed = time.perf_counter() - t0
    assert len(out) == n
    # 5 并发, 10 个 0.1s 请求 -> 理论 ~0.2s, 放宽到 0.6s
    assert elapsed < 0.6, f"concurrent too slow: {elapsed:.2f}s"


def test_empty_input(stub_fetch):
    assert kline_module.fetch_klines_batch([], days=30) == {}


def test_workers_one_falls_back_to_serial(stub_fetch):
    """workers=1 仍能正常工作（降级路径）。"""
    out = kline_module.fetch_klines_batch(["A/USDT", "B/USDT"], days=30, workers=1)
    assert set(out.keys()) == {"A/USDT", "B/USDT"}
