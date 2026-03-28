import argparse
import json
import os
import sys
import time
from datetime import datetime

import yaml
from tabulate import tabulate

from scanner.coingecko import fetch_market_caps, set_proxy as set_coingecko_proxy
from scanner.kline import fetch_klines_batch, fetch_futures_symbols, set_proxy as set_kline_proxy
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

    # Step 1: 获取交易对列表
    if symbols_override:
        symbols = symbols_override
        print(f"[1/4] 使用指定的 {len(symbols)} 个交易对")
    else:
        print(f"[1/4] 从Binance获取USDT永续合约列表...")
        symbols = fetch_futures_symbols()
        print(f"       共 {len(symbols)} 个合约交易对")

    if not symbols:
        print("没有找到交易对。")
        return

    # Step 2: 拉K线
    print(f"[2/4] 从Binance拉取K线数据（{len(symbols)}个交易对）...")
    klines = fetch_klines_batch(symbols, days=30, delay=0.5)
    print(f"       成功获取 {len(klines)} 个交易对的K线")

    # Step 3: 形态检测 + 评分
    print("[3/4] 形态检测中...")
    matches = []
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
        matches.append({
            "symbol": symbol,
            "drop_pct": detection.drop_pct,
            "volume_ratio": detection.volume_ratio,
            "window_days": detection.window_days,
            "score": score,
        })

    print(f"       形态命中 {len(matches)} 个")

    if not matches:
        print("\n未找到符合底部蓄力形态的币种。")
        return

    # Step 4: 对命中币种查市值，过滤小市值
    skip_cap = config.get("skip_market_cap_filter", False)
    if not symbols_override and not skip_cap:
        base_symbols = [m["symbol"].split("/")[0] for m in matches]
        print(f"[4/4] 查询 {len(base_symbols)} 个命中币种的市值...")
        market_caps = fetch_market_caps(base_symbols, page_delay=config.get("page_delay", 30))

        for m in matches:
            base = m["symbol"].split("/")[0]
            m["market_cap_m"] = market_caps.get(base, 0) / 1e6

        # 过滤市值
        before = len(matches)
        matches = [m for m in matches if 0 < m["market_cap_m"] <= max_market_cap / 1e6]
        print(f"       市值过滤: {before} -> {len(matches)} 个 (< ${max_market_cap / 1e6:.0f}M)")
    else:
        print("[4/4] 跳过市值过滤")
        for m in matches:
            m["market_cap_m"] = 0

    if not matches:
        print("\n过滤后没有符合条件的币种。")
        return

    ranked = rank_results(matches, top_n=top_n)

    # 输出表格
    table_data = []
    for i, r in enumerate(ranked, 1):
        table_data.append([
            i,
            r["symbol"],
            f"{r['market_cap_m']:.1f}" if r["market_cap_m"] > 0 else "-",
            f"{r['drop_pct'] * 100:.1f}%",
            f"{r['volume_ratio']:.2f}",
            r["window_days"],
            f"{r['score']:.2f}",
        ])

    headers = ["排名", "币种", "市值(M$)", "跌幅", "缩量比", "天数", "评分"]
    print(f"\n找到 {len(ranked)} 个底部蓄力形态币种:\n")
    print(tabulate(table_data, headers=headers, tablefmt="simple"))

    # 保存结果
    os.makedirs("results", exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_path = f"results/{ts}.json"
    with open(json_path, "w") as f:
        json.dump(ranked, f, ensure_ascii=False, indent=2)
    txt_path = f"results/{ts}.txt"
    with open(txt_path, "w") as f:
        f.write(f"扫描时间: {ts}\n")
        f.write(f"找到 {len(ranked)} 个底部蓄力形态币种:\n\n")
        f.write(tabulate(table_data, headers=headers, tablefmt="simple"))
        f.write("\n")
    print(f"\n结果已保存到 {json_path} 和 {txt_path}")


def main():
    parser = argparse.ArgumentParser(description="币种底部蓄力形态筛选器")
    parser.add_argument("--top", type=int, help="输出前N个结果")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--symbols", nargs="+", help="直接指定交易对（跳过自动扫描），如 BTC/USDT ETH/USDT")
    args = parser.parse_args()

    config = load_config(args.config)
    run(config, top_n=args.top, symbols_override=args.symbols)


if __name__ == "__main__":
    main()
