import argparse
import json
import os
from dataclasses import replace
from datetime import datetime

import yaml
from tabulate import tabulate

from scanner.coingecko import fetch_market_caps, set_proxy as set_coingecko_proxy
from scanner.kline import fetch_klines_batch, fetch_futures_symbols, set_proxy as set_kline_proxy
from scanner.detector import detect_pattern
from scanner.scorer import score_result, rank_results
from scanner.tracker import save_scan, get_tracked_symbols, get_history
from scanner.signal import SignalConfig, generate_signals
from scanner.confirmation import confirm_signal
from scanner.new_coin import NewCoinConfig, build_new_listings_payload, screen_new_listings
from scanner.listing_intel import ListingIntelConfig, enrich_new_listings_payload


def load_config(
    path: str = "config.yaml",
) -> tuple[dict, SignalConfig, NewCoinConfig, ListingIntelConfig]:
    with open(path) as f:
        raw = yaml.safe_load(f)
    proxy = (raw.get("proxy") or {}).get("https", "")
    if proxy:
        set_kline_proxy(proxy)
        set_coingecko_proxy(proxy)
        print(f"[代理] 使用 {proxy}")
    sig = raw.get("signal", {})
    signal_config = SignalConfig(
        min_score=sig.get("min_score", 0.6),
        hold_days=sig.get("hold_days", 3),
        stop_loss=sig.get("stop_loss", 0.05),
        take_profit=sig.get("take_profit", 0.08),
        confirmation=sig.get("confirmation", True),
        confirmation_min_pass=sig.get("confirmation_min_pass", 3),
    )
    new_coin = NewCoinConfig.from_mapping(raw.get("new_coin"))
    listing_intel = ListingIntelConfig.from_mapping(
        raw.get("listing_intel"),
        proxy_https=proxy or None,
    )
    return raw.get("scanner", {}), signal_config, new_coin, listing_intel


def run(config: dict, signal_config: SignalConfig, top_n: int | None = None, symbols_override: list[str] | None = None):
    top_n = top_n or config.get("top_n", 20)
    max_market_cap = config.get("max_market_cap", 100_000_000)

    # Step 1: 获取交易对列表（Binance U本位永续 base ∩ Binance 现货）
    if symbols_override:
        symbols = symbols_override
        print(f"[1/4] 使用指定的 {len(symbols)} 个交易对")
    else:
        print(f"[1/4] 获取Binance U本位永续与现货交集列表...")
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
        # 当日收盘价（K线最后一根）
        price = float(df["close"].iloc[-1])
        matches.append({
            "symbol": symbol,
            "price": price,
            "drop_pct": detection.drop_pct,
            "volume_ratio": detection.volume_ratio,
            "window_days": detection.window_days,
            "score": score,
        })

    print(f"       形态命中 {len(matches)} 个")

    if not matches:
        print("\n未找到符合底部蓄力形态的币种。")
        return

    # Step 4: 市值过滤
    skip_cap = config.get("skip_market_cap_filter", False)
    if not symbols_override and not skip_cap:
        base_symbols = [m["symbol"].split("/")[0] for m in matches]
        print(f"[4/4] 查询 {len(base_symbols)} 个命中币种的市值...")
        market_caps = fetch_market_caps(base_symbols, page_delay=config.get("page_delay", 30))
        for m in matches:
            base = m["symbol"].split("/")[0]
            m["market_cap_m"] = market_caps.get(base, 0) / 1e6
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

    # 确认层过滤
    if signal_config.confirmation:
        confirmed = []
        filtered_names = []
        for m in ranked:
            result = confirm_signal(klines[m["symbol"]], "long", signal_config.confirmation_min_pass)
            if result.passed:
                confirmed.append(m)
            else:
                filtered_names.append(m["symbol"])
        if filtered_names:
            print(f"[确认] {len(ranked)} -> {len(confirmed)} 个 (过滤: {', '.join(filtered_names[:5])}{'...' if len(filtered_names) > 5 else ''})")
        ranked = confirmed

    if not ranked:
        print("\n确认层过滤后没有剩余信号。")
        return

    # 保存到数据库
    scan_id = save_scan(ranked)
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(ranked)} 个币种及价格")

    # 信号过滤
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return

    # 输出交易建议表格
    table_data = []
    for i, s in enumerate(signals, 1):
        table_data.append([
            i,
            s.symbol,
            f"{s.price:.4f}",
            f"{s.score:.2f}",
            f"{s.entry_price:.4f}",
            f"{s.stop_loss_price:.4f}",
            f"{s.take_profit_price:.4f}",
            s.hold_days,
        ])

    headers = ["排名", "币种", "价格", "评分", "入场价", "止损价", "止盈价", "持仓天数"]
    print(f"\n找到 {len(signals)} 个交易信号（止损{signal_config.stop_loss:.0%} / 止盈{signal_config.take_profit:.0%} / 持仓{signal_config.hold_days}天）:\n")
    print(tabulate(table_data, headers=headers, tablefmt="simple"))

    # 保存文件
    os.makedirs("results", exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_data = [
        {
            "symbol": s.symbol,
            "price": s.price,
            "score": s.score,
            "entry_price": s.entry_price,
            "stop_loss_price": s.stop_loss_price,
            "take_profit_price": s.take_profit_price,
            "hold_days": s.hold_days,
            "drop_pct": s.drop_pct,
            "volume_ratio": s.volume_ratio,
            "window_days": s.window_days,
        }
        for s in signals
    ]
    json_path = f"results/{ts}.json"
    with open(json_path, "w") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    txt_path = f"results/{ts}.txt"
    with open(txt_path, "w") as f:
        f.write(f"扫描时间: {ts}\n")
        f.write(f"信号参数: 止损{signal_config.stop_loss:.0%} / 止盈{signal_config.take_profit:.0%} / 持仓{signal_config.hold_days}天\n")
        f.write(f"找到 {len(signals)} 个交易信号:\n\n")
        f.write(tabulate(table_data, headers=headers, tablefmt="simple"))
        f.write("\n")
    print(f"结果已保存到 {json_path} 和 {txt_path}")


def run_divergence(config: dict, signal_config: SignalConfig, top_n: int | None = None, symbols_override: list[str] | None = None):
    from scanner.divergence import detect_divergence
    top_n = top_n or config.get("top_n", 20)
    max_market_cap = config.get("max_market_cap", 100_000_000)

    # Step 1: 获取交易对列表
    if symbols_override:
        symbols = symbols_override
        print(f"[1/4] 使用指定的 {len(symbols)} 个交易对")
    else:
        print(f"[1/4] 获取Binance U本位永续与现货交集列表...")
        symbols = fetch_futures_symbols()
        print(f"       共 {len(symbols)} 个合约交易对")

    if not symbols:
        print("没有找到交易对。")
        return

    # Step 2: 拉K线（背离模式需要90天）
    print(f"[2/4] 从Binance拉取K线数据（{len(symbols)}个交易对，90天）...")
    klines = fetch_klines_batch(symbols, days=90, delay=0.5)
    print(f"       成功获取 {len(klines)} 个交易对的K线")

    # Step 3: 背离检测
    print("[3/4] MACD背离检测中...")
    matches = []
    for symbol, df in klines.items():
        result = detect_divergence(df)
        if result.divergence_type == "none":
            continue
        price = float(df["close"].iloc[-1])
        signal_type = "底背离" if result.divergence_type == "bullish" else "顶背离"
        matches.append({
            "symbol": symbol,
            "price": price,
            "drop_pct": 0,
            "volume_ratio": 0,
            "window_days": result.pivot_distance,
            "score": result.score,
            "signal_type": signal_type,
            "mode": "divergence",
        })

    print(f"       背离命中 {len(matches)} 个")

    if not matches:
        print("\n未找到MACD背离的币种。")
        return

    # Step 4: 市值过滤
    skip_cap = config.get("skip_market_cap_filter", False)
    if not symbols_override and not skip_cap:
        base_symbols = [m["symbol"].split("/")[0] for m in matches]
        print(f"[4/4] 查询 {len(base_symbols)} 个命中币种的市值...")
        market_caps = fetch_market_caps(base_symbols, page_delay=config.get("page_delay", 30))
        for m in matches:
            base = m["symbol"].split("/")[0]
            m["market_cap_m"] = market_caps.get(base, 0) / 1e6
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

    # 确认层过滤
    if signal_config.confirmation:
        confirmed = []
        filtered_names = []
        for m in ranked:
            direction = "short" if m.get("signal_type") == "顶背离" else "long"
            result = confirm_signal(klines[m["symbol"]], direction, signal_config.confirmation_min_pass)
            if result.passed:
                confirmed.append(m)
            else:
                filtered_names.append(m["symbol"])
        if filtered_names:
            print(f"[确认] {len(ranked)} -> {len(confirmed)} 个 (过滤: {', '.join(filtered_names[:5])}{'...' if len(filtered_names) > 5 else ''})")
        ranked = confirmed

    if not ranked:
        print("\n确认层过滤后没有剩余信号。")
        return

    # 保存到数据库
    scan_id = save_scan(ranked, mode="divergence")
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(ranked)} 个币种及价格")

    # 信号过滤
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return

    # 输出交易建议表格
    table_data = []
    for i, s in enumerate(signals, 1):
        table_data.append([
            i,
            s.symbol,
            s.signal_type,
            f"{s.price:.4f}",
            f"{s.score:.2f}",
            f"{s.entry_price:.4f}",
            f"{s.stop_loss_price:.4f}",
            f"{s.take_profit_price:.4f}",
            s.hold_days,
        ])

    headers = ["排名", "币种", "类型", "价格", "评分", "入场价", "止损价", "止盈价", "持仓天数"]
    print(f"\n找到 {len(signals)} 个交易信号（止损{signal_config.stop_loss:.0%} / 止盈{signal_config.take_profit:.0%} / 持仓{signal_config.hold_days}天）:\n")
    print(tabulate(table_data, headers=headers, tablefmt="simple"))

    # 保存文件
    os.makedirs("results", exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_data = [
        {
            "symbol": s.symbol,
            "signal_type": s.signal_type,
            "price": s.price,
            "score": s.score,
            "entry_price": s.entry_price,
            "stop_loss_price": s.stop_loss_price,
            "take_profit_price": s.take_profit_price,
            "hold_days": s.hold_days,
        }
        for s in signals
    ]
    json_path = f"results/divergence_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    txt_path = f"results/divergence_{ts}.txt"
    with open(txt_path, "w") as f:
        f.write(f"扫描时间: {ts}\n")
        f.write(f"模式: MACD背离\n")
        f.write(f"信号参数: 止损{signal_config.stop_loss:.0%} / 止盈{signal_config.take_profit:.0%} / 持仓{signal_config.hold_days}天\n")
        f.write(f"找到 {len(signals)} 个交易信号:\n\n")
        f.write(tabulate(table_data, headers=headers, tablefmt="simple"))
        f.write("\n")
    print(f"结果已保存到 {json_path} 和 {txt_path}")


def show_tracking():
    """显示所有跟踪中的币种"""
    tracked = get_tracked_symbols()
    if not tracked:
        print("还没有跟踪数据，先运行一次扫描。")
        return
    table_data = []
    for t in tracked:
        price_change = ""
        if t["first_price"] and t["last_price"] and t["times"] > 1:
            pct = (t["last_price"] - t["first_price"]) / t["first_price"] * 100
            price_change = f"{pct:+.1f}%"
        table_data.append([
            t["symbol"],
            t["times"],
            f"{t['last_price']:.4f}" if t["last_price"] else "-",
            price_change,
            t["last_seen"],
        ])
    headers = ["币种", "命中次数", "最新价格", "价格变化", "最后出现"]
    print(tabulate(table_data, headers=headers, tablefmt="simple"))


def show_history(symbol: str):
    """显示某币种的历史记录"""
    records = get_history(symbol, limit=20)
    if not records:
        print(f"没有 {symbol} 的跟踪记录。")
        return
    table_data = []
    for r in records:
        table_data.append([
            r["scan_time"],
            f"{r['price']:.4f}",
            f"{r['drop_pct'] * 100:.1f}%",
            f"{r['volume_ratio']:.2f}",
            r["window_days"],
            f"{r['score']:.2f}",
        ])
    headers = ["扫描时间", "价格", "跌幅", "缩量比", "天数", "评分"]
    print(f"{symbol} 历史记录:\n")
    print(tabulate(table_data, headers=headers, tablefmt="simple"))


def run_new_coin_observation(
    new_cfg: NewCoinConfig,
    top_n: int | None = None,
    *,
    listing_intel_cfg: ListingIntelConfig | None = None,
):
    """新币观察清单（不跑蓄力/背离，不生成交易信号）。"""
    cfg = replace(new_cfg, top_n=top_n) if top_n is not None else new_cfg
    intel_cfg = listing_intel_cfg or ListingIntelConfig()
    step_tag = "[1/2]" if intel_cfg.enabled else "[1/1]"
    print(f"{step_tag} 新币观察清单（Binance U本位永续∩现货，上架≤{cfg.max_listing_days}天）...")
    if intel_cfg.enabled:
        print(
            "       L2 增强已启用：L2a 公告 / L2b DexScreener 链上池近似 / L2c 规则尽调分"
            "（Binance CMS 可能被 WAF 拦截，可配代理或 manual_overlay_csv）。"
        )
    rows = screen_new_listings(cfg)
    if not rows:
        print("\n没有符合新币条件的交易对。")
        print(
            "提示: 宇宙为「Binance U本位 USDT 永续 base ∩ Binance 现货」；另有上架天数、24h 成交额等门槛。"
            "可在 config.yaml 的 new_coin 段放宽 max_listing_days / min_quote_volume_24h；"
            "代理或限速导致单币请求失败时，有效条数也会偏少。"
        )
        return

    payload = build_new_listings_payload(rows)
    if intel_cfg.enabled:
        print("[2/2] L2 增强（公告 / 链上 / 尽调分）...")
        payload = enrich_new_listings_payload(payload, intel_cfg)
        rows = payload["rows"]
        st = (payload.get("meta") or {}).get("intel_stats") or {}
        if st:
            print(
                f"       intel: 尝试 {st.get('rows_attempted')} 行 | "
                f"L2a 命中 {st.get('l2a_matched')} | L2b 命中 {st.get('l2b_matched')} | "
                f"L2c 计分 {st.get('l2c_scored')}",
            )
            err = st.get("source_errors") or []
            if err:
                print(f"       警告: {err[:3]}{'…' if len(err) > 3 else ''}")

    table_data = []
    for i, r in enumerate(rows, 1):
        chg = r.get("change_24h_pct")
        chg_s = f"{chg:.2%}" if chg is not None else "-"
        avg7 = r.get("avg_quote_volume_7d")
        avg7_s = f"{avg7:,.0f}" if avg7 is not None else "-"
        mcap = r.get("market_cap_usd") or 0.0
        mcap_s = f"{mcap / 1e6:.2f}M" if mcap else "-"
        row_out = [
            i,
            r["symbol"],
            r["listing_days"],
            f"{r['price']:.6f}",
            f"{r['quote_volume_24h']:,.0f}",
            avg7_s,
            chg_s,
            mcap_s,
        ]
        if intel_cfg.enabled and intel_cfg.l2c_dd_score:
            row_out.extend([
                r.get("dd_score", "-"),
                r.get("trust_tier", "-"),
            ])
        table_data.append(row_out)
    headers = [
        "#", "交易对", "上架天数", "价格", "24h额", "7d均额*", "24h涨跌", "市值",
    ]
    if intel_cfg.enabled and intel_cfg.l2c_dd_score:
        headers.extend(["DD分", "信任档"])
    print(f"\n共 {len(rows)} 条（*7d均额为近似 quote 额；市值来自 CoinGecko 分页命中）:\n")
    print(tabulate(table_data, headers=headers, tablefmt="simple"))
    if len(rows) < cfg.top_n:
        vol_s = f"{cfg.min_quote_volume_24h:,.0f}"
        print(
            f"\n说明: 当前仅 {len(rows)} 条，少于 top_n={cfg.top_n}，表示通过筛选的候选本就这些（非截断误伤）。"
            f"常见原因：交集宇宙内同时满足 上架≤{cfg.max_listing_days} 天、24h 成交额≥{vol_s} USDT 的币较少；"
            "或部分交易对请求失败被跳过。可调大 max_listing_days / 调小 min_quote_volume_24h，或检查代理与 request_delay。"
        )

    os.makedirs("results", exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_path = f"results/new_listings_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    txt_path = f"results/new_listings_{ts}.txt"
    with open(txt_path, "w") as f:
        f.write(f"扫描时间: {ts}\n模式: new_listings\n\n")
        f.write(tabulate(table_data, headers=headers, tablefmt="simple"))
        f.write("\n")
    print(f"\n结果已保存到 {json_path} 和 {txt_path}")


def run_backtest_cli(
    config: dict,
    signal_config: SignalConfig,
    days: int,
    symbols_override: list[str] | None = None,
    verify_signal: bool = False,
    run_sensitivity: bool = False,
):
    """运行回测：拉取历史K线，滑动窗口检测，统计收益。"""
    from scanner.backtest import (
        run_backtest,
        compute_stats,
        format_stats,
        compute_signal_verification_splits,
        format_signal_verification,
    )
    from scanner.sensitivity import (
        run_scanner_sensitivity_grid,
        format_sensitivity_table,
        sensitivity_market_cap_note,
    )

    # Step 1: 获取交易对列表
    if symbols_override:
        symbols = symbols_override
        print(f"[1/3] 使用指定的 {len(symbols)} 个交易对")
    else:
        print(f"[1/3] 获取Binance U本位永续与现货交集列表...")
        symbols = fetch_futures_symbols()
        print(f"       共 {len(symbols)} 个合约交易对")

    if not symbols:
        print("没有找到交易对。")
        return

    # Step 2: 拉取历史K线
    print(f"[2/3] 从Binance拉取 {days} 天K线数据（{len(symbols)}个交易对）...")
    klines = fetch_klines_batch(symbols, days=days, delay=0.5)
    print(f"       成功获取 {len(klines)} 个交易对的K线")

    # Step 3: 回测
    print("[3/3] 滑动窗口回扫中...")
    hits = run_backtest(klines, config)
    print(f"       总命中 {len(hits)} 次形态")

    if not hits:
        print("\n历史数据中未检测到底部蓄力形态。")
        return

    stats = compute_stats(hits)
    output = format_stats(stats)
    print(f"\n{output}")

    if verify_signal:
        period = f"{signal_config.hold_days}d"
        sv = compute_signal_verification_splits(
            hits,
            min_score=signal_config.min_score,
            period=period,
        )
        print("\n" + format_signal_verification(sv))

    if run_sensitivity:
        grid = run_scanner_sensitivity_grid(klines, base_config=config)
        print("\n=== 参数敏感性（命中数，同一批 K 线）===\n")
        print(format_sensitivity_table(grid))
        print("\n" + sensitivity_market_cap_note(config.get("skip_market_cap_filter", False)))

    # 保存结果
    os.makedirs("results", exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    json_path = f"results/backtest_{ts}.json"
    json_data = {
        "stats": stats,
        "hits": [
            {
                "symbol": h.symbol,
                "detect_date": h.detect_date,
                "window_days": h.window_days,
                "drop_pct": h.drop_pct,
                "volume_ratio": h.volume_ratio,
                "score": h.score,
                "returns": h.returns,
            }
            for h in hits
        ],
    }
    with open(json_path, "w") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    txt_path = f"results/backtest_{ts}.txt"
    with open(txt_path, "w") as f:
        f.write(f"回测时间: {ts}\n")
        f.write(f"历史天数: {days}\n")
        f.write(f"币种数: {len(klines)}\n\n")
        f.write(output)
        f.write("\n")

    print(f"结果已保存到 {json_path} 和 {txt_path}")


def main():
    parser = argparse.ArgumentParser(description="币种形态筛选器")
    parser.add_argument(
        "--mode",
        choices=["accumulation", "divergence", "new"],
        default="accumulation",
        help="扫描模式: accumulation=底部蓄力, divergence=MACD背离, new=新币观察清单",
    )
    parser.add_argument("--top", type=int, help="输出前N个结果")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--symbols", nargs="+", help="直接指定交易对")
    parser.add_argument("--track", action="store_true", help="查看所有跟踪中的币种")
    parser.add_argument("--history", type=str, help="查看某币种历史记录，如 ZIL/USDT")
    parser.add_argument("--backtest", action="store_true", help="运行回测验证形态有效性")
    parser.add_argument(
        "--verify-signal",
        action="store_true",
        help="与 --backtest 联用：按检测日中位数分段，对比 signal 门槛下收益",
    )
    parser.add_argument(
        "--sensitivity",
        action="store_true",
        help="与 --backtest 联用：对 key scanner 参数输出命中数敏感性表",
    )
    parser.add_argument("--days", type=int, default=180, help="回测历史K线天数（默认180）")
    parser.add_argument(
        "--no-intel",
        action="store_true",
        help="与 --mode new 联用：关闭 L2 增强（公告/链上/尽调分）",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="关闭信号确认层（多指标共振过滤）",
    )
    args = parser.parse_args()

    config, signal_config, new_coin_config, listing_intel_config = load_config(args.config)

    if args.no_confirm:
        signal_config = replace(signal_config, confirmation=False)

    if args.track:
        show_tracking()
    elif args.history:
        show_history(args.history)
    elif args.backtest:
        run_backtest_cli(
            config,
            signal_config,
            days=args.days,
            symbols_override=args.symbols,
            verify_signal=args.verify_signal,
            run_sensitivity=args.sensitivity,
        )
    elif args.mode == "new":
        intel_cfg = (
            replace(listing_intel_config, enabled=False)
            if args.no_intel
            else listing_intel_config
        )
        run_new_coin_observation(
            new_coin_config,
            top_n=args.top,
            listing_intel_cfg=intel_cfg,
        )
    elif args.mode == "divergence":
        run_divergence(config, signal_config, top_n=args.top, symbols_override=args.symbols)
    else:
        run(config, signal_config, top_n=args.top, symbols_override=args.symbols)


if __name__ == "__main__":
    main()
