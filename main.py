import argparse
import sys
import time

import yaml
from tabulate import tabulate

from scanner.coingecko import fetch_small_cap_coins, set_proxy as set_coingecko_proxy
from scanner.kline import fetch_klines_batch, set_proxy as set_kline_proxy
from scanner.detector import detect_pattern
from scanner.scorer import score_result, rank_results


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        raw = yaml.safe_load(f)
    proxy = (raw.get("proxy") or {}).get("https", "")
    if proxy:
        set_kline_proxy(proxy)
        set_coingecko_proxy(proxy)
        print(f"[代理] 使用 {proxy}")
    return raw.get("scanner", {})


def run(config: dict, top_n: int | None = None, symbols_override: list[str] | None = None):
    top_n = top_n or config.get("top_n", 20)
    max_market_cap = config.get("max_market_cap", 100_000_000)

    if symbols_override:
        # 直接使用指定的交易对，跳过CoinGecko
        symbols = symbols_override
        coin_map = {s: {"market_cap": 0} for s in symbols}
        print(f"[1/3] 使用指定的 {len(symbols)} 个交易对，跳过CoinGecko")
    else:
        # Step 1: CoinGecko 市值筛选
        print(f"[1/3] 从CoinGecko拉取市值 < ${max_market_cap / 1e6:.0f}M 的币种...")
        coins = fetch_small_cap_coins(
            max_market_cap,
            max_coins=config.get("max_coins", 500),
            max_pages=config.get("max_pages", 10),
        )
        print(f"       找到 {len(coins)} 个小市值币种")

        if not coins:
            print("没有找到符合条件的币种。")
            return

        symbols = [f"{c['symbol']}/USDT" for c in coins]
        coin_map = {f"{c['symbol']}/USDT": c for c in coins}

    print(f"[2/3] 从Binance拉取K线数据（约{len(symbols)}个交易对）...")
    klines = fetch_klines_batch(symbols, days=30, delay=0.5)
    print(f"       成功获取 {len(klines)} 个交易对的K线")

    # Step 3: 形态检测 + 评分
    print("[3/3] 形态检测中...")
    results = []
    for symbol, df in klines.items():
        detection = detect_pattern(
            df,
            window_min_days=config.get("window_min_days", 7),
            window_max_days=config.get("window_max_days", 14),
            volume_ratio=config.get("volume_ratio", 0.5),
            drop_min=config.get("drop_min", 0.05),
            drop_max=config.get("drop_max", 0.15),
            max_daily_change=config.get("max_daily_change", 0.05),
        )
        if not detection.matched:
            continue
        score = score_result(
            detection,
            drop_min=config.get("drop_min", 0.05),
            drop_max=config.get("drop_max", 0.15),
            max_daily_change=config.get("max_daily_change", 0.05),
        )
        coin_info = coin_map.get(symbol, {})
        results.append({
            "symbol": symbol,
            "market_cap_m": coin_info.get("market_cap", 0) / 1e6,
            "drop_pct": detection.drop_pct,
            "volume_ratio": detection.volume_ratio,
            "window_days": detection.window_days,
            "score": score,
        })

    ranked = rank_results(results, top_n=top_n)

    if not ranked:
        print("\n未找到符合底部蓄力形态的币种。")
        return

    # 输出表格
    table_data = []
    for i, r in enumerate(ranked, 1):
        table_data.append([
            i,
            r["symbol"],
            f"{r['market_cap_m']:.1f}",
            f"{r['drop_pct'] * 100:.1f}%",
            f"{r['volume_ratio']:.2f}",
            r["window_days"],
            f"{r['score']:.2f}",
        ])

    headers = ["排名", "币种", "市值(M$)", "跌幅", "缩量比", "天数", "评分"]
    print(f"\n找到 {len(ranked)} 个底部蓄力形态币种:\n")
    print(tabulate(table_data, headers=headers, tablefmt="simple"))


def main():
    parser = argparse.ArgumentParser(description="币种底部蓄力形态筛选器")
    parser.add_argument("--top", type=int, help="输出前N个结果")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--symbols", nargs="+", help="直接指定交易对（跳过CoinGecko），如 BTC/USDT ETH/USDT")
    args = parser.parse_args()

    config = load_config(args.config)
    run(config, top_n=args.top, symbols_override=args.symbols)


if __name__ == "__main__":
    main()
