import argparse
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime

import yaml
from tabulate import tabulate

from scanner.coingecko import fetch_market_caps, set_proxy as set_coingecko_proxy
from scanner.kline import fetch_klines_batch, fetch_futures_symbols, set_proxy as set_kline_proxy
from scanner.detector import detect_pattern
from scanner.scorer import score_result, rank_results
from scanner.tracker import save_scan, get_tracked_symbols, get_history, get_closed_trades
from scanner.signal import SignalConfig, TradeSignal, generate_signals, calculate_atr
from scanner.confirmation import confirm_signal
from scanner.breakout import detect_breakout
from scanner.new_coin import NewCoinConfig, build_new_listings_payload, screen_new_listings
from scanner.listing_intel import ListingIntelConfig, enrich_new_listings_payload
from scanner.stats import (
    compute_stats,
    compute_stats_by_mode,
    compute_stats_by_score_tier,
    compute_stats_by_month,
    format_stats_report,
    export_stats_json,
)


@dataclass
class TradingConfig:
    enabled: bool = False
    api_key_env: str = "BINANCE_API_KEY"
    api_secret_env: str = "BINANCE_API_SECRET"
    max_positions: int = 5
    order_timeout_minutes: int = 30
    score_sizing: dict[float, float] | None = None

    def __post_init__(self):
        if self.score_sizing is None:
            self.score_sizing = {0.6: 0.02, 0.7: 0.03, 0.8: 0.04, 0.9: 0.05}

    def get_api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")

    def get_api_secret(self) -> str:
        return os.environ.get(self.api_secret_env, "")


@dataclass
class ScheduleConfig:
    scan_time: str = "08:00"
    monitor_interval: int = 60


def load_config(
    path: str = "config.yaml",
) -> tuple[dict, SignalConfig, NewCoinConfig, ListingIntelConfig, TradingConfig, ScheduleConfig]:
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
        atr_period=sig.get("atr_period", 14),
        atr_sl_multiplier=sig.get("atr_sl_multiplier", 2.0),
        atr_tp_multiplier=sig.get("atr_tp_multiplier", 3.0),
        confirmation=sig.get("confirmation", True),
        confirmation_min_pass=sig.get("confirmation_min_pass", 3),
    )
    new_coin = NewCoinConfig.from_mapping(raw.get("new_coin"))
    listing_intel = ListingIntelConfig.from_mapping(
        raw.get("listing_intel"),
        proxy_https=proxy or None,
    )
    scanner_cfg = dict(raw.get("scanner", {}))
    if "breakout" in raw:
        scanner_cfg["breakout"] = raw["breakout"]

    # trading config
    t = raw.get("trading", {})
    score_sizing_raw = t.get("score_sizing")
    score_sizing = {float(k): float(v) for k, v in score_sizing_raw.items()} if score_sizing_raw else None
    trading_config = TradingConfig(
        enabled=t.get("enabled", False),
        api_key_env=t.get("api_key_env", "BINANCE_API_KEY"),
        api_secret_env=t.get("api_secret_env", "BINANCE_API_SECRET"),
        max_positions=t.get("max_positions", 5),
        order_timeout_minutes=t.get("order_timeout_minutes", 30),
        score_sizing=score_sizing,
    )

    # schedule config
    s = raw.get("schedule", {})
    schedule_config = ScheduleConfig(
        scan_time=s.get("scan_time", "08:00"),
        monitor_interval=s.get("monitor_interval", 60),
    )

    return scanner_cfg, signal_config, new_coin, listing_intel, trading_config, schedule_config


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
        atr = calculate_atr(df, period=signal_config.atr_period)
        matches.append({
            "symbol": symbol,
            "price": price,
            "drop_pct": detection.drop_pct,
            "volume_ratio": detection.volume_ratio,
            "window_days": detection.window_days,
            "score": score,
            "atr": atr,
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

    # 确认层过滤 + 加分
    if signal_config.confirmation:
        confirmed = []
        filtered_names = []
        for m in ranked:
            result = confirm_signal(klines[m["symbol"]], "long", signal_config.confirmation_min_pass)
            if result.passed:
                m["base_score"] = m["score"]
                m["confirm_bonus"] = result.bonus
                m["score"] = round(m["base_score"] + result.bonus, 4)
                confirmed.append(m)
            else:
                filtered_names.append(m["symbol"])
        if filtered_names:
            print(f"[确认] {len(ranked)} -> {len(confirmed)} 个 (过滤: {', '.join(filtered_names[:5])}{'...' if len(filtered_names) > 5 else ''})")
        ranked = confirmed
        # 按新分数重新排序
        ranked.sort(key=lambda x: x["score"], reverse=True)

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


def run_divergence(config: dict, signal_config: SignalConfig, top_n: int | None = None, symbols_override: list[str] | None = None) -> list[TradeSignal]:
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
        return []

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
        atr = calculate_atr(df, period=signal_config.atr_period)
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
            "atr": atr,
        })

    print(f"       背离命中 {len(matches)} 个")

    if not matches:
        print("\n未找到MACD背离的币种。")
        return []

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
        return []

    ranked = rank_results(matches, top_n=top_n)

    # 确认层过滤 + 加分
    if signal_config.confirmation:
        confirmed = []
        filtered_names = []
        for m in ranked:
            direction = "short" if m.get("signal_type") == "顶背离" else "long"
            result = confirm_signal(klines[m["symbol"]], direction, signal_config.confirmation_min_pass)
            if result.passed:
                m["base_score"] = m["score"]
                m["confirm_bonus"] = result.bonus
                m["score"] = round(m["base_score"] + result.bonus, 4)
                confirmed.append(m)
            else:
                filtered_names.append(m["symbol"])
        if filtered_names:
            print(f"[确认] {len(ranked)} -> {len(confirmed)} 个 (过滤: {', '.join(filtered_names[:5])}{'...' if len(filtered_names) > 5 else ''})")
        ranked = confirmed
        # 按新分数重新排序
        ranked.sort(key=lambda x: x["score"], reverse=True)

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
        return []

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
    return signals


def run_breakout(config: dict, signal_config: SignalConfig, top_n: int | None = None, symbols_override: list[str] | None = None):
    breakout_cfg = config.get("breakout", {})
    top_n = top_n or breakout_cfg.get("top_n", 20)
    max_market_cap = config.get("max_market_cap", 100_000_000)

    # Step 1: 获取交易对列表
    if symbols_override:
        symbols = symbols_override
        print(f"[1/4] 使用指定的 {len(symbols)} 个交易对")
    else:
        print("[1/4] 获取Binance U本位永续与现货交集列表...")
        symbols = fetch_futures_symbols()
        print(f"       共 {len(symbols)} 个合约交易对")

    if not symbols:
        print("没有找到交易对。")
        return

    # Step 2: 拉K线（30天）
    print(f"[2/4] 从Binance拉取K线数据（{len(symbols)}个交易对，30天）...")
    klines = fetch_klines_batch(symbols, days=30, delay=0.5)
    print(f"       成功获取 {len(klines)} 个交易对的K线")

    # Step 3: 天量回踩检测
    print("[3/4] 天量回踩二攻检测中...")
    matches = []
    for symbol, df in klines.items():
        result = detect_breakout(
            df,
            spike_multiplier=breakout_cfg.get("spike_multiplier", 5.0),
            shrink_threshold=breakout_cfg.get("shrink_threshold", 0.3),
            reattack_multiplier=breakout_cfg.get("reattack_multiplier", 2.0),
            max_pullback_days=breakout_cfg.get("max_pullback_days", 10),
            freshness_days=breakout_cfg.get("freshness_days", 3),
        )
        if not result.matched:
            continue
        atr = calculate_atr(df, period=signal_config.atr_period)
        matches.append({
            "symbol": symbol,
            "price": result.reattack_close,
            "drop_pct": 0,
            "volume_ratio": 0,
            "window_days": result.days_since_spike,
            "score": result.score,
            "signal_type": "天量回踩",
            "mode": "breakout",
            "spike_date": result.spike_date,
            "spike_vol_ratio": result.spike_volume_ratio,
            "pullback_low": result.pullback_low,
            "spike_high": result.spike_high,
            "atr": atr,
        })

    print(f"       命中 {len(matches)} 个")

    if not matches:
        print("\n未找到天量回踩二攻模式的币种。")
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

    # 确认层过滤 + 加分
    if signal_config.confirmation:
        confirmed = []
        filtered_names = []
        for m in ranked:
            result = confirm_signal(klines[m["symbol"]], "long", signal_config.confirmation_min_pass)
            if result.passed:
                m["base_score"] = m["score"]
                m["confirm_bonus"] = result.bonus
                m["score"] = round(m["base_score"] + result.bonus, 4)
                confirmed.append(m)
            else:
                filtered_names.append(m["symbol"])
        if filtered_names:
            print(f"[确认] {len(ranked)} -> {len(confirmed)} 个 (过滤: {', '.join(filtered_names[:5])}{'...' if len(filtered_names) > 5 else ''})")
        ranked = confirmed
        ranked.sort(key=lambda x: x["score"], reverse=True)

    if not ranked:
        print("\n确认层过滤后没有剩余信号。")
        return

    # 保存到数据库
    scan_id = save_scan(ranked, mode="breakout")
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(ranked)} 个币种及价格")

    # 信号过滤
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return

    # 重算止损止盈（用天量回踩特有的位置）
    for s in signals:
        m = next(r for r in ranked if r["symbol"] == s.symbol)
        s.stop_loss_price = round(m["pullback_low"] * 0.97, 6)
        s.take_profit_price = round(m["spike_high"], 6)

    # 输出表格
    table_data = []
    for i, s in enumerate(signals, 1):
        m = next(r for r in ranked if r["symbol"] == s.symbol)
        table_data.append([
            i,
            s.symbol,
            s.signal_type,
            f"{s.price:.4f}",
            f"{s.score:.2f}",
            f"{m.get('spike_date', '')}",
            f"{m.get('spike_vol_ratio', 0):.0f}x",
            f"{s.entry_price:.4f}",
            f"{s.stop_loss_price:.4f}",
            f"{s.take_profit_price:.4f}",
        ])

    headers = ["排名", "币种", "类型", "价格", "评分", "天量日", "倍数", "入场", "止损", "止盈"]
    print(f"\n找到 {len(signals)} 个交易信号:\n")
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
            "spike_date": next(r for r in ranked if r["symbol"] == s.symbol).get("spike_date", ""),
            "spike_vol_ratio": next(r for r in ranked if r["symbol"] == s.symbol).get("spike_vol_ratio", 0),
            "entry_price": s.entry_price,
            "stop_loss_price": s.stop_loss_price,
            "take_profit_price": s.take_profit_price,
        }
        for s in signals
    ]
    json_path = f"results/breakout_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    txt_path = f"results/breakout_{ts}.txt"
    with open(txt_path, "w") as f:
        f.write(f"扫描时间: {ts}\n")
        f.write(f"模式: 天量回踩二攻\n")
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


def execute_trading_pipeline(
    signals: list[TradeSignal],
    trading_config: TradingConfig,
) -> None:
    """交易管线：仓位过滤 → 计算仓位 → 下单执行。"""
    import logging
    from scanner.kline import get_authed_usdm
    from scanner.trader.sizing import get_max_leverage, calculate_position
    from scanner.trader.position import filter_signals
    from scanner.trader.executor import execute_trade

    logger = logging.getLogger("trader")

    api_key = trading_config.get_api_key()
    api_secret = trading_config.get_api_secret()
    if not api_key or not api_secret:
        logger.error("[交易] API Key 未配置，跳过自动下单")
        print("[交易] API Key 未配置，跳过自动下单。请设置环境变量 BINANCE_API_KEY 和 BINANCE_API_SECRET")
        return

    # 获取代理（复用已配置的）
    from scanner.kline import _authed_usdm, _usdm
    proxy = ""
    if _usdm and hasattr(_usdm, "httpsProxy"):
        proxy = _usdm.httpsProxy or ""
    exchange = get_authed_usdm(api_key, api_secret, proxy)

    # 仓位过滤
    try:
        filtered = filter_signals(exchange, signals, trading_config.max_positions)
    except Exception as e:
        logger.error("[交易] 仓位查询失败: %s，跳过本轮下单", e)
        print(f"[交易] 仓位查询失败: {e}，跳过本轮下单")
        return

    if not filtered:
        print("[交易] 无可开仓信号（已持有或仓位已满）")
        return

    print(f"[交易] 准备下单: {len(filtered)} 个信号")

    # 查询余额
    try:
        balance_info = exchange.fetch_balance()
        available = float(balance_info.get("free", {}).get("USDT", 0))
        print(f"[交易] 可用余额: {available:.2f} USDT")
    except Exception as e:
        logger.error("[交易] 余额查询失败: %s", e)
        print(f"[交易] 余额查询失败: {e}")
        return

    # 逐个下单
    success_count = 0
    for signal in filtered:
        leverage = get_max_leverage(exchange, signal.symbol)
        amount = calculate_position(
            balance=available,
            price=signal.entry_price,
            score=signal.score,
            leverage=leverage,
            score_sizing=trading_config.score_sizing,
        )
        if amount <= 0:
            logger.warning("[%s] 计算仓位为 0，跳过", signal.symbol)
            continue

        ok = execute_trade(exchange, signal, amount, leverage)
        if ok:
            success_count += 1
            # 扣减可用余额估算（实际由交易所管理）
            margin_used = (amount * signal.entry_price) / leverage
            available -= margin_used

    print(f"[交易] 完成: 成功 {success_count}/{len(filtered)} 笔")


def run_serve(
    config: dict,
    signal_config: SignalConfig,
    trading_config: TradingConfig,
    schedule_config: ScheduleConfig,
) -> None:
    """常驻模式：APScheduler 定时扫描 + 自动下单 + 订单监控。"""
    import logging
    import signal
    from apscheduler.schedulers.blocking import BlockingScheduler

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler("logs/trader.log"),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger("serve")
    os.makedirs("logs", exist_ok=True)

    scheduler = BlockingScheduler()

    # 定时扫描任务
    hour, minute = map(int, schedule_config.scan_time.split(":"))

    def scheduled_scan():
        logger.info("=== 定时扫描开始 ===")
        try:
            signals = run_divergence(config, signal_config)
            if signals and trading_config.enabled:
                execute_trading_pipeline(signals, trading_config)
            elif not trading_config.enabled:
                logger.info("trading.enabled=false，仅扫描不下单")
        except Exception as e:
            logger.error("定时扫描异常: %s", e)
        logger.info("=== 定时扫描结束 ===")

    scheduler.add_job(scheduled_scan, "cron", hour=hour, minute=minute, id="daily_scan")
    logger.info("定时扫描已注册: 每天 %s", schedule_config.scan_time)

    # 订单监控任务
    if trading_config.enabled:
        def scheduled_monitor():
            try:
                from scanner.kline import get_authed_usdm
                from scanner.trader.monitor import run_monitor_cycle
                api_key = trading_config.get_api_key()
                api_secret = trading_config.get_api_secret()
                if not api_key or not api_secret:
                    return
                from scanner.kline import _usdm
                proxy = ""
                if _usdm and hasattr(_usdm, "httpsProxy"):
                    proxy = _usdm.httpsProxy or ""
                exchange = get_authed_usdm(api_key, api_secret, proxy)
                run_monitor_cycle(exchange, trading_config.order_timeout_minutes)
            except Exception as e:
                logger.error("订单监控异常: %s", e)

        scheduler.add_job(
            scheduled_monitor,
            "interval",
            seconds=schedule_config.monitor_interval,
            id="order_monitor",
        )
        logger.info("订单监控已注册: 每 %d 秒", schedule_config.monitor_interval)

    print(f"[serve] 常驻模式启动 — 扫描时间: {schedule_config.scan_time}, 交易: {'开启' if trading_config.enabled else '关闭'}")
    print("[serve] 按 Ctrl+C 退出")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("常驻模式退出")


def run_stats(json_only: bool = False) -> None:
    """输出信号成功率统计。"""
    trades = get_closed_trades()
    if not trades:
        print("暂无已关仓交易数据。")
        return

    overall = compute_stats(trades)
    by_mode = compute_stats_by_mode(trades)
    by_score = compute_stats_by_score_tier(trades)
    by_month = compute_stats_by_month(trades)

    if not json_only:
        print(format_stats_report(overall, by_mode, by_score, by_month))

    path = export_stats_json(overall, by_mode, by_score, by_month, trades=trades)
    print(f"\n[导出] {path}")


def main():
    parser = argparse.ArgumentParser(description="币种形态筛选器")
    parser.add_argument(
        "--mode",
        choices=["accumulation", "divergence", "new", "breakout"],
        default="divergence",
        help="扫描模式: divergence=MACD背离(默认), accumulation=底部蓄力, new=新币观察清单, breakout=天量回踩",
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
    parser.add_argument(
        "--serve",
        action="store_true",
        help="常驻模式：APScheduler 定时扫描 + 自动下单 + 订单监控",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="查看信号成功率统计（按模式/评分/月份）",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="与 --stats 联用：仅导出 JSON，不打印表格",
    )
    args = parser.parse_args()

    config, signal_config, new_coin_config, listing_intel_config, trading_config, schedule_config = load_config(args.config)

    if args.no_confirm:
        signal_config = replace(signal_config, confirmation=False)

    if args.serve:
        run_serve(config, signal_config, trading_config, schedule_config)
    elif args.stats:
        run_stats(json_only=args.json_only)
    elif args.track:
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
    elif args.mode == "breakout":
        run_breakout(config, signal_config, top_n=args.top, symbols_override=args.symbols)
    elif args.mode == "divergence":
        signals = run_divergence(config, signal_config, top_n=args.top, symbols_override=args.symbols)
        if signals and trading_config.enabled:
            execute_trading_pipeline(signals, trading_config)
    else:
        run(config, signal_config, top_n=args.top, symbols_override=args.symbols)


if __name__ == "__main__":
    main()
