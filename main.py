import argparse
import json
import os

from dotenv import load_dotenv

load_dotenv()

from dataclasses import dataclass, replace
from datetime import datetime

import yaml
from tabulate import tabulate

from scanner.coingecko import fetch_market_caps, set_proxy as set_coingecko_proxy
from scanner.kline import fetch_klines_batch, fetch_futures_symbols, set_proxy as set_kline_proxy
from scanner.detector import detect_pattern
from scanner.scorer import score_result, score_result_detailed, rank_results
from scanner.tracker import save_scan, get_tracked_symbols, get_history, get_closed_trades
from scanner.signal import SignalConfig, TradeSignal, generate_signals, calculate_atr
from scanner.confirmation import confirm_signal
from scanner.breakout import detect_breakout
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
    safety_factor: float = 1.5
    max_leverage: int = 20
    score_leverage: dict[float, float] | None = None

    def __post_init__(self):
        if self.score_sizing is None:
            self.score_sizing = {0.6: 0.02, 0.7: 0.03, 0.8: 0.04, 0.9: 0.05}
        if self.score_leverage is None:
            self.score_leverage = {0.6: 0.4, 0.7: 0.6, 0.8: 0.8, 0.9: 1.0}

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
) -> tuple[dict, SignalConfig, TradingConfig, ScheduleConfig, dict, dict]:
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
        max_stop_loss=sig.get("max_stop_loss", 0.05),
    )
    scanner_cfg = dict(raw.get("scanner", {}))
    if "breakout" in raw:
        scanner_cfg["breakout"] = raw["breakout"]
    if "smc" in raw:
        scanner_cfg["smc"] = raw["smc"]

    # trading config
    t = raw.get("trading", {})
    score_sizing_raw = t.get("score_sizing")
    score_sizing = {float(k): float(v) for k, v in score_sizing_raw.items()} if score_sizing_raw else None
    score_leverage_raw = t.get("score_leverage")
    score_leverage = {float(k): float(v) for k, v in score_leverage_raw.items()} if score_leverage_raw else None
    trading_config = TradingConfig(
        enabled=t.get("enabled", False),
        api_key_env=t.get("api_key_env", "BINANCE_API_KEY"),
        api_secret_env=t.get("api_secret_env", "BINANCE_API_SECRET"),
        max_positions=t.get("max_positions", 5),
        order_timeout_minutes=t.get("order_timeout_minutes", 30),
        score_sizing=score_sizing,
        safety_factor=float(t.get("safety_factor", 1.5)),
        max_leverage=int(t.get("max_leverage", 20)),
        score_leverage=score_leverage,
    )

    # schedule config
    s = raw.get("schedule", {})
    schedule_config = ScheduleConfig(
        scan_time=s.get("scan_time", "08:00"),
        monitor_interval=s.get("monitor_interval", 60),
    )

    # sentiment config
    sentiment_cfg = dict(raw.get("sentiment", {}))
    if "enabled" not in sentiment_cfg:
        sentiment_cfg["enabled"] = False
    if "weights" not in sentiment_cfg:
        sentiment_cfg["weights"] = {"twitter": 0.3, "telegram": 0.2, "news": 0.3, "onchain": 0.2}
    if "boost_range" not in sentiment_cfg:
        sentiment_cfg["boost_range"] = 0.2

    # portfolio config
    portfolio_cfg = dict(raw.get("portfolio", {}))
    if "enabled" not in portfolio_cfg:
        portfolio_cfg["enabled"] = False

    scanner_cfg["_sentiment_config"] = sentiment_cfg

    return scanner_cfg, signal_config, trading_config, schedule_config, sentiment_cfg, portfolio_cfg


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
        breakdown = score_result_detailed(
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
            "score": breakdown.total,
            "atr": atr,
            "r_squared": detection.r_squared,
            "max_daily_pct": detection.max_daily_pct,
            "score_breakdown": breakdown.to_dict(),
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

    # 信号过滤
    signals = generate_signals(ranked, signal_config, klines_map=klines)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return

    # 舆情评分加成
    sentiment_config = config.get("_sentiment_config", {})
    if sentiment_config.get("enabled"):
        from sentiment.store import query_latest_signal
        from sentiment.aggregator import compute_boost
        from sentiment.models import SentimentSignal
        from dataclasses import replace as dc_replace
        boost_range = sentiment_config.get("boost_range", 0.2)
        boosted = []
        for sig in signals:
            latest = query_latest_signal(sig.symbol)
            if latest:
                sent_sig = SentimentSignal(symbol=latest.symbol, score=latest.score,
                    direction=latest.direction, confidence=latest.confidence)
                boost = compute_boost(sent_sig, boost_range)
                new_score = max(0.0, min(1.0, sig.score * (1 + boost)))
                boosted.append(dc_replace(sig, score=new_score))
            else:
                boosted.append(sig)
        signals = boosted

    # 保存到数据库（存信号，含点位）
    scan_id = save_scan(signals)
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(signals)} 个信号")

    # 记录信号到 feedback 表
    try:
        from scanner.optimize.feedback import ensure_outcomes_table, record_signal_outcome
        from scanner.optimize.feature_engine import extract_features
        from scanner.kline import fetch_klines
        import json as _json

        ensure_outcomes_table()
        btc_df = fetch_klines("BTC/USDT", days=30)
        today = datetime.now().strftime("%Y-%m-%d")
        ranked_map = {m["symbol"]: m for m in ranked}
        for s in signals:
            df = klines.get(s.symbol) if klines else None
            if df is None:
                continue
            m = ranked_map.get(s.symbol, {})
            match_dict = {
                "symbol": s.symbol, "score": s.score,
                "volume_ratio": s.volume_ratio, "drop_pct": s.drop_pct,
                "r_squared": m.get("r_squared", 0),
                "max_daily_pct": m.get("max_daily_pct", 0),
                "window_days": s.window_days,
            }
            features = extract_features(match_dict, df, btc_df)
            record_signal_outcome(
                db_path=os.environ.get("COIN_DB_PATH", "scanner.db"),
                scan_result_id=None, symbol=s.symbol,
                signal_date=today, signal_price=s.price,
                features_json=_json.dumps(features),
                btc_price=float(btc_df["close"].iloc[-1]) if btc_df is not None else 0,
            )
    except Exception as e:
        print(f"[feedback] 记录失败（不影响扫描）: {e}")

    # 输出交易建议表格
    table_data = []
    for i, s in enumerate(signals, 1):
        entry_tag = " [SR]" if s.entry_method == "support_resistance" else " [SD]"
        table_data.append([
            i,
            s.symbol,
            f"{s.price:.4f}",
            f"{s.score:.2f}",
            f"{s.entry_price:.4f}" + entry_tag,
            f"{s.stop_loss_price:.4f}" + (" [已收紧]" if s.sl_capped else ""),
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
            "score_breakdown": result.score_breakdown_dict(),
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

    # 信号过滤
    signals = generate_signals(ranked, signal_config, klines_map=klines)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return []

    # 舆情评分加成
    sentiment_config = config.get("_sentiment_config", {})
    if sentiment_config.get("enabled"):
        from sentiment.store import query_latest_signal
        from sentiment.aggregator import compute_boost
        from sentiment.models import SentimentSignal
        from dataclasses import replace as dc_replace
        boost_range = sentiment_config.get("boost_range", 0.2)
        boosted = []
        for sig in signals:
            latest = query_latest_signal(sig.symbol)
            if latest:
                sent_sig = SentimentSignal(symbol=latest.symbol, score=latest.score,
                    direction=latest.direction, confidence=latest.confidence)
                boost = compute_boost(sent_sig, boost_range)
                new_score = max(0.0, min(1.0, sig.score * (1 + boost)))
                boosted.append(dc_replace(sig, score=new_score))
            else:
                boosted.append(sig)
        signals = boosted

    # 保存到数据库（存信号，含点位）
    scan_id = save_scan(signals, mode="divergence")
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(signals)} 个信号")

    # 记录信号到 feedback 表
    try:
        from scanner.optimize.feedback import ensure_outcomes_table, record_signal_outcome
        from scanner.optimize.feature_engine import extract_features
        from scanner.kline import fetch_klines
        import json as _json

        ensure_outcomes_table()
        btc_df = fetch_klines("BTC/USDT", days=30)
        today = datetime.now().strftime("%Y-%m-%d")
        for s in signals:
            df = klines.get(s.symbol) if klines else None
            if df is None:
                continue
            match_dict = {
                "symbol": s.symbol, "score": s.score,
                "volume_ratio": s.volume_ratio, "drop_pct": s.drop_pct,
                "r_squared": 0, "max_daily_pct": 0, "window_days": s.window_days,
            }
            features = extract_features(match_dict, df, btc_df)
            record_signal_outcome(
                db_path=os.environ.get("COIN_DB_PATH", "scanner.db"),
                scan_result_id=None, symbol=s.symbol,
                signal_date=today, signal_price=s.price,
                features_json=_json.dumps(features),
                btc_price=float(btc_df["close"].iloc[-1]) if btc_df is not None else 0,
            )
    except Exception as e:
        print(f"[feedback] 记录失败（不影响扫描）: {e}")

    # 输出交易建议表格
    table_data = []
    for i, s in enumerate(signals, 1):
        entry_tag = " [SR]" if s.entry_method == "support_resistance" else " [SD]"
        table_data.append([
            i,
            s.symbol,
            s.signal_type,
            f"{s.price:.4f}",
            f"{s.score:.2f}",
            f"{s.entry_price:.4f}" + entry_tag,
            f"{s.stop_loss_price:.4f}" + (" [已收紧]" if s.sl_capped else ""),
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
            "score_breakdown": result.score_breakdown_dict(),
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

    # 信号过滤
    signals = generate_signals(ranked, signal_config, klines_map=klines)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return

    # 重算止损止盈（用天量回踩特有的位置）
    for s in signals:
        m = next(r for r in ranked if r["symbol"] == s.symbol)
        s.stop_loss_price = round(m["pullback_low"] * 0.97, 6)
        s.take_profit_price = round(m["spike_high"], 6)

    # 保存到数据库（存信号，含覆写后的点位）
    scan_id = save_scan(signals, mode="breakout")
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(signals)} 个信号")

    # 输出表格
    table_data = []
    for i, s in enumerate(signals, 1):
        m = next(r for r in ranked if r["symbol"] == s.symbol)
        entry_tag = " [SR]" if s.entry_method == "support_resistance" else " [SD]"
        table_data.append([
            i,
            s.symbol,
            s.signal_type,
            f"{s.price:.4f}",
            f"{s.score:.2f}",
            f"{m.get('spike_date', '')}",
            f"{m.get('spike_vol_ratio', 0):.0f}x",
            f"{s.entry_price:.4f}" + entry_tag,
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


def run_smc(config: dict, signal_config: SignalConfig, top_n: int | None = None, symbols_override: list[str] | None = None):
    from scanner.smc import detect_smc
    smc_cfg = config.get("smc", {})
    top_n = top_n or smc_cfg.get("top_n", 20)
    max_market_cap = config.get("max_market_cap", 100_000_000)

    # SMC 模式可单独设置 min_score（默认 0.3，因为 SMC 评分天然低于蓄力/背离模式）
    smc_min_score = smc_cfg.get("min_score", 0.3)
    if smc_min_score != signal_config.min_score:
        signal_config = replace(signal_config, min_score=smc_min_score)

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

    # Step 2: 拉K线（SMC 需要 90 天数据）
    print(f"[2/4] 从Binance拉取K线数据（{len(symbols)}个交易对，90天）...")
    klines = fetch_klines_batch(symbols, days=90, delay=0.5)
    print(f"       成功获取 {len(klines)} 个交易对的K线")

    # Step 3: SMC 检测
    print("[3/4] Smart Money Concepts 检测中...")
    matches = []
    for symbol, df in klines.items():
        result = detect_smc(
            df,
            swing_length=smc_cfg.get("swing_length", 10),
            freshness_candles=smc_cfg.get("freshness_candles", 10),
            fvg_lookback=smc_cfg.get("fvg_lookback", 30),
            ob_lookback=smc_cfg.get("ob_lookback", 30),
            proximity_max=smc_cfg.get("proximity_max", 0.05),
        )
        if not result.matched:
            continue
        price = float(df["close"].iloc[-1])
        atr = calculate_atr(df, period=signal_config.atr_period)

        # 用 OB/FVG 作为入场区域
        entry_zone_top = 0.0
        entry_zone_bottom = 0.0
        if result.has_ob:
            entry_zone_top = result.ob_top
            entry_zone_bottom = result.ob_bottom
        elif result.has_fvg:
            entry_zone_top = result.fvg_top
            entry_zone_bottom = result.fvg_bottom

        matches.append({
            "symbol": symbol,
            "price": price,
            "drop_pct": 0,
            "volume_ratio": 0,
            "window_days": 0,
            "score": result.score,
            "signal_type": result.signal_type,
            "mode": "smc",
            "atr": atr,
            "direction": result.direction,
            "structure_type": result.structure_type,
            "structure_level": result.structure_level,
            "has_fvg": result.has_fvg,
            "fvg_top": result.fvg_top,
            "fvg_bottom": result.fvg_bottom,
            "has_ob": result.has_ob,
            "ob_top": result.ob_top,
            "ob_bottom": result.ob_bottom,
            "entry_zone_top": entry_zone_top,
            "entry_zone_bottom": entry_zone_bottom,
            "score_breakdown": result.score_breakdown_dict(),
        })

    print(f"       命中 {len(matches)} 个")

    if not matches:
        print("\n未找到 SMC 结构变化的币种。")
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
            direction = "short" if m.get("direction") == "bearish" else "long"
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
        ranked.sort(key=lambda x: x["score"], reverse=True)

    if not ranked:
        print("\n确认层过滤后没有剩余信号。")
        return

    # 信号过滤
    signals = generate_signals(ranked, signal_config, klines_map=klines)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return

    # 用 SMC 特有的 entry zone 优化止损止盈
    for s in signals:
        m = next(r for r in ranked if r["symbol"] == s.symbol)
        is_bearish = m.get("direction") == "bearish"
        struct_level = m.get("structure_level", 0)
        ez_top = m.get("entry_zone_top", 0)
        ez_bottom = m.get("entry_zone_bottom", 0)
        if is_bearish:
            # 看空：止损在结构突破位上方，止盈用 entry zone 下方
            if struct_level > 0 and struct_level > s.entry_price:
                s.stop_loss_price = round(struct_level * 1.01, 6)
            if ez_bottom > 0 and ez_bottom < s.entry_price:
                s.take_profit_price = round(ez_bottom * 0.99, 6)
        else:
            # 看多：止损在结构突破位下方，止盈用 ATR 或 entry zone 上方
            if struct_level > 0 and struct_level < s.entry_price:
                s.stop_loss_price = round(struct_level * 0.99, 6)
            if ez_top > 0 and ez_top > s.entry_price:
                s.take_profit_price = round(ez_top * 1.01, 6)

    # 舆情评分加成
    sentiment_config = config.get("_sentiment_config", {})
    if sentiment_config.get("enabled"):
        from sentiment.store import query_latest_signal
        from sentiment.aggregator import compute_boost
        from sentiment.models import SentimentSignal
        from dataclasses import replace as dc_replace
        boost_range = sentiment_config.get("boost_range", 0.2)
        boosted = []
        for sig in signals:
            latest = query_latest_signal(sig.symbol)
            if latest:
                sent_sig = SentimentSignal(symbol=latest.symbol, score=latest.score,
                    direction=latest.direction, confidence=latest.confidence)
                boost = compute_boost(sent_sig, boost_range)
                new_score = max(0.0, min(1.0, sig.score * (1 + boost)))
                boosted.append(dc_replace(sig, score=new_score))
            else:
                boosted.append(sig)
        signals = boosted

    # 保存到数据库
    scan_id = save_scan(signals, mode="smc")
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(signals)} 个信号")

    # 输出表格
    table_data = []
    for i, s in enumerate(signals, 1):
        m = next(r for r in ranked if r["symbol"] == s.symbol)
        entry_tag = " [SR]" if s.entry_method == "support_resistance" else " [SD]"
        fvg_tag = "FVG" if m.get("has_fvg") else ""
        ob_tag = "OB" if m.get("has_ob") else ""
        zone_tags = "+".join(filter(None, [m.get("structure_type", ""), fvg_tag, ob_tag]))
        table_data.append([
            i,
            s.symbol,
            s.signal_type,
            zone_tags,
            f"{s.price:.4f}",
            f"{s.score:.2f}",
            f"{s.entry_price:.4f}" + entry_tag,
            f"{s.stop_loss_price:.4f}",
            f"{s.take_profit_price:.4f}",
        ])

    headers = ["排名", "币种", "方向", "信号组合", "价格", "评分", "入场", "止损", "止盈"]
    print(f"\n找到 {len(signals)} 个 SMC 交易信号:\n")
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
            "structure_type": next(r for r in ranked if r["symbol"] == s.symbol).get("structure_type", ""),
            "has_fvg": next(r for r in ranked if r["symbol"] == s.symbol).get("has_fvg", False),
            "has_ob": next(r for r in ranked if r["symbol"] == s.symbol).get("has_ob", False),
            "entry_price": s.entry_price,
            "stop_loss_price": s.stop_loss_price,
            "take_profit_price": s.take_profit_price,
        }
        for s in signals
    ]
    json_path = f"results/smc_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    txt_path = f"results/smc_{ts}.txt"
    with open(txt_path, "w") as f:
        f.write(f"扫描时间: {ts}\n")
        f.write(f"模式: Smart Money Concepts\n")
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
    from scanner.trader.sizing import get_max_leverage, calculate_leverage, calculate_position
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
        stop_distance = abs(signal.entry_price - signal.stop_loss_price) / signal.entry_price
        exchange_max = get_max_leverage(exchange, signal.symbol)
        leverage = calculate_leverage(
            stop_distance=stop_distance,
            score=signal.score,
            safety_factor=trading_config.safety_factor,
            max_leverage=trading_config.max_leverage,
            exchange_max=exchange_max,
            score_leverage=trading_config.score_leverage,
        )
        if leverage < 1:
            logger.warning("[%s] 止损距离 %.1f%% 过大，安全杠杆<1，跳过", signal.symbol, stop_distance * 100)
            print(f"[交易] {signal.symbol} 止损距离 {stop_distance:.1%} 过大，跳过")
            continue
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

        logger.info("[%s] 止损距离=%.1f%%, 杠杆=%dx (安全上限=%dx, 交易所=%dx)",
                    signal.symbol, stop_distance * 100, leverage,
                    min(int(1 / (stop_distance * trading_config.safety_factor)), trading_config.max_leverage),
                    exchange_max)
        ok = execute_trade(exchange, signal, amount, leverage)
        if ok:
            success_count += 1
            margin_used = (amount * signal.entry_price) / leverage
            available -= margin_used

    print(f"[交易] 完成: 成功 {success_count}/{len(filtered)} 笔")


def run_serve(
    config: dict,
    signal_config: SignalConfig,
    trading_config: TradingConfig,
    schedule_config: ScheduleConfig,
    sentiment_config: dict | None = None,
    portfolio_config: dict | None = None,
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
    from datetime import datetime, timedelta
    hour, minute = map(int, schedule_config.scan_time.split(":"))

    def scheduled_scan():
        logger.info("=== 定时扫描开始（三模式）===")
        div_signals = []
        try:
            run(config, signal_config)
        except Exception as e:
            logger.error("accumulation 扫描异常: %s", e)
        try:
            div_signals = run_divergence(config, signal_config)
        except Exception as e:
            logger.error("divergence 扫描异常: %s", e)
        try:
            run_breakout(config, signal_config)
        except Exception as e:
            logger.error("breakout 扫描异常: %s", e)
        if div_signals and trading_config.enabled:
            top_signals = sorted(div_signals, key=lambda s: s.score, reverse=True)[:2]
            logger.info("背离信号 %d 个，挂单 top %d (按 score 排序)", len(div_signals), len(top_signals))
            execute_trading_pipeline(top_signals, trading_config)
        elif not trading_config.enabled:
            logger.info("trading.enabled=false，仅扫描不下单")
        logger.info("=== 定时扫描结束 ===")

    # 启动时立即跑一次（避免进程在 08:10 之后启动导致当天扫描被跳过）
    scheduler.add_job(scheduled_scan, "date",
                      run_date=datetime.now() + timedelta(seconds=10),
                      id="startup_scan")
    scheduler.add_job(scheduled_scan, "cron", hour=hour, minute=minute, id="daily_scan")
    logger.info("定时扫描已注册: 启动后10秒执行一次，之后每天 %s", schedule_config.scan_time)

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

    # 信号生命周期刷新任务（每 5 分钟）
    def scheduled_lifecycle():
        try:
            from scanner.lifecycle import refresh_signal_prices, check_lifecycle_transitions, expire_stale_signals
            from scanner.kline import fetch_ticker_price
            updated = refresh_signal_prices(fetch_ticker_price)
            transitions = check_lifecycle_transitions()
            expired = expire_stale_signals(hold_days=signal_config.hold_days)
            if updated or any(transitions.values()) or expired:
                logger.info("[lifecycle] 刷新 %d 个, 转换 %s, 过期 %d 个", updated, transitions, expired)
        except Exception as e:
            logger.error("lifecycle 刷新异常: %s", e)

    scheduler.add_job(scheduled_lifecycle, "interval", minutes=5, id="lifecycle_refresh")
    logger.info("信号生命周期刷新已注册: 每 5 分钟")

    if sentiment_config and sentiment_config.get("enabled"):
        interval = sentiment_config.get("news", {}).get("interval_minutes", 15)
        scheduler.add_job(run_sentiment_scan, "interval", minutes=interval,
            args=[sentiment_config], id="sentiment_scan")
        logger.info("舆情采集已注册: 每 %d 分钟", interval)

    if portfolio_config and portfolio_config.get("enabled"):
        scheduler.add_job(run_portfolio_rebalance, "cron",
            day_of_week="mon", hour=8, minute=0,
            args=[portfolio_config], id="portfolio_rebalance")
        logger.info("组合再平衡已注册: 每周一 08:00")

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


def run_optimize_cli(
    config: dict,
    signal_config: SignalConfig,
    days: int = 180,
    symbols_override: list[str] | None = None,
) -> None:
    """运行 Optuna 参数优化，基于回测数据搜索最优参数后写入 config.yaml。"""
    from scanner.backtest import run_backtest, compute_stats, format_stats
    from scanner.optimize.param_optimizer import optimize_params

    # 1. 获取交易对 + K线
    if symbols_override:
        symbols = symbols_override
        print(f"[optimize] 使用指定的 {len(symbols)} 个交易对")
    else:
        print("[optimize] 获取交易对列表...")
        symbols = fetch_futures_symbols()
        print(f"[optimize] 共 {len(symbols)} 个合约交易对")

    if not symbols:
        print("[optimize] 没有找到交易对，退出。")
        return

    print(f"[optimize] 拉取 {days} 天K线数据...")
    klines = fetch_klines_batch(symbols, days=days, delay=0.5)
    print(f"[optimize] 成功获取 {len(klines)} 个交易对的K线")

    # 2. 回测
    print("[optimize] 运行回测（滑动窗口）...")
    hits = run_backtest(klines, config)
    print(f"[optimize] 总命中 {len(hits)} 次形态")

    if not hits:
        print("[optimize] 历史数据中未检测到底部蓄力形态，无法优化。")
        return

    stats = compute_stats(hits)
    print(f"\n[optimize] 基准回测统计:\n{format_stats(stats)}")

    # 3. Optuna 参数搜索
    print("\n[optimize] 开始 Optuna 参数搜索（n_trials=200）...")
    result = optimize_params(hits, n_trials=200)
    print("\n[optimize] ===== 最优参数 =====")
    print(f"  drop_min:           {result.drop_min:.4f}")
    print(f"  drop_max:           {result.drop_max:.4f}")
    print(f"  max_daily_change:   {result.max_daily_change:.4f}")
    print(f"  min_score:          {result.min_score:.4f}")
    print(f"  w_volume:           {result.w_volume:.4f}")
    print(f"  w_drop:             {result.w_drop:.4f}")
    print(f"  w_trend:            {result.w_trend:.4f}")
    print(f"  w_slow:             {result.w_slow:.4f}")
    print(f"  validation_win_rate:    {result.validation_win_rate:.4f}")
    print(f"  validation_mean_return: {result.validation_mean_return:.4f}")
    print(f"  objective_value:        {result.objective_value:.4f}")

    # 4. 写入 config.yaml 的 optimized 段
    cfg_path = "config.yaml"
    try:
        with open(cfg_path) as f:
            raw = yaml.safe_load(f) or {}
        raw["optimized"] = {
            "drop_min": round(result.drop_min, 4),
            "drop_max": round(result.drop_max, 4),
            "max_daily_change": round(result.max_daily_change, 4),
            "min_score": round(result.min_score, 4),
            "w_volume": round(result.w_volume, 4),
            "w_drop": round(result.w_drop, 4),
            "w_trend": round(result.w_trend, 4),
            "w_slow": round(result.w_slow, 4),
            "validation_win_rate": round(result.validation_win_rate, 4),
            "validation_mean_return": round(result.validation_mean_return, 4),
            "objective_value": round(result.objective_value, 4),
        }
        with open(cfg_path, "w") as f:
            yaml.dump(raw, f, allow_unicode=True, default_flow_style=False)
        print(f"\n[optimize] 最优参数已写入 {cfg_path} 的 optimized 段")
    except Exception as e:
        print(f"[optimize] 写入 config.yaml 失败: {e}")


def run_retrain_cli() -> None:
    """收集信号反馈并重训练 ML 模型。"""
    from scanner.optimize.feedback import ensure_outcomes_table
    from scanner.optimize.retrain import run_retrain

    print("[retrain] 确保 signal_outcomes 表存在...")
    ensure_outcomes_table()
    print("[retrain] 开始重训练...")
    report = run_retrain()

    print("\n[retrain] ===== 重训练报告 =====")
    print(f"  时间:         {report.timestamp}")
    print(f"  样本数:       {report.samples_used}")
    print(f"  新模型准确率: {report.new_accuracy:.4f}")
    if report.old_accuracy is not None:
        print(f"  旧模型准确率: {report.old_accuracy:.4f}")
    else:
        print(f"  旧模型准确率: (无旧模型)")
    print(f"  是否提升:     {'是' if report.improved else '否'}")
    if report.model_path:
        print(f"  模型路径:     {report.model_path}")
    if report.report_path:
        print(f"  报告路径:     {report.report_path}")
    if report.samples_used < 100:
        print(f"\n[retrain] 样本数不足（{report.samples_used}/100），尚未训练模型。")
        print("[retrain] 请先运行扫描积累信号，待 return_7d 回填后再重训练。")


def run_optimize_report_cli() -> None:
    """查看当前最优参数和模型表现。"""
    from scanner.optimize.ml_filter import load_latest_model

    cfg_path = "config.yaml"
    optimized = None
    try:
        with open(cfg_path) as f:
            raw = yaml.safe_load(f) or {}
        optimized = raw.get("optimized")
    except Exception as e:
        print(f"[report] 读取 {cfg_path} 失败: {e}")

    print("\n[report] ===== 优化参数 =====")
    if optimized:
        for k, v in optimized.items():
            print(f"  {k}: {v}")
    else:
        print("  尚未运行过 --optimize，config.yaml 中没有 optimized 段。")

    print("\n[report] ===== ML 模型状态 =====")
    model_info = load_latest_model()
    if model_info is None:
        print("  尚未运行过 --retrain，models 目录中没有训练好的模型。")
    else:
        print(f"  训练时间:   {model_info.trained_at}")
        print(f"  样本数:     {model_info.sample_count}")
        print(f"  验证准确率: {model_info.validation_accuracy:.4f}")
        print(f"  特征数量:   {len(model_info.feature_names)}")


def run_sentiment_scan(sentiment_config: dict, symbols_override: list[str] | None = None) -> None:
    """采集舆情数据并生成情绪信号。"""
    if not sentiment_config.get("enabled"):
        print("[sentiment] 舆情功能未启用（sentiment.enabled=false）")
        return

    from sentiment.sources.news import CryptoPanicSource, RSSSource
    from sentiment.sources.feargreed import FearGreedSource
    from sentiment.sources.onchain import EtherscanSource
    from sentiment.analyzer import analyze_text, analyze_onchain
    from sentiment.store import save_items, save_signal
    from sentiment.aggregator import aggregate

    items = []

    # 恐惧贪婪指数（免费，无需 key）
    try:
        fg_src = FearGreedSource()
        fg_items = fg_src.fetch()
        items.extend(fg_items)
        print(f"[sentiment] 恐惧贪婪指数 获取 {len(fg_items)} 条")
    except Exception as e:
        print(f"[sentiment] 恐惧贪婪指数 获取失败: {e}")

    # RSS（免费，无需 key）
    try:
        rss_src = RSSSource()
        rss_items = rss_src.fetch(symbols=symbols_override)
        items.extend(rss_items)
        print(f"[sentiment] RSS 获取 {len(rss_items)} 条")
    except Exception as e:
        print(f"[sentiment] RSS 获取失败: {e}")

    # Etherscan 链上（需要免费 key）
    onchain_cfg = sentiment_config.get("onchain", {})
    etherscan_key = os.environ.get(onchain_cfg.get("etherscan_api_key_env", "ETHERSCAN_API_KEY"), "")
    if etherscan_key:
        try:
            eth_src = EtherscanSource(
                api_key=etherscan_key,
                min_value_usd=onchain_cfg.get("min_transfer_usd", 1_000_000),
            )
            eth_items = eth_src.fetch()
            items.extend(eth_items)
            print(f"[sentiment] Etherscan 获取 {len(eth_items)} 条")
        except Exception as e:
            print(f"[sentiment] Etherscan 获取失败: {e}")

    # CryptoPanic（可选，需付费 key）
    news_cfg = sentiment_config.get("news", {})
    api_key_env = news_cfg.get("cryptopanic_api_key_env", "CRYPTOPANIC_API_KEY")
    api_key = os.environ.get(api_key_env, "")
    if api_key:
        try:
            src = CryptoPanicSource(api_key=api_key)
            fetched = src.fetch(symbols=symbols_override)
            items.extend(fetched)
            print(f"[sentiment] CryptoPanic 获取 {len(fetched)} 条")
        except Exception as e:
            print(f"[sentiment] CryptoPanic 获取失败: {e}")

    if not items:
        print("[sentiment] 无可用舆情数据")
        return

    # 分析原始文本 items（无 score 的需 analyze_text）
    analyzed = []
    for item in items:
        if item.score == 0.0:
            score = analyze_text(item.raw_text)
            analyzed.append(replace(item, score=score))
        else:
            analyzed.append(item)

    # 保存 items
    save_items(analyzed)
    print(f"[sentiment] 已保存 {len(analyzed)} 条舆情数据")

    # 聚合信号
    weights = sentiment_config.get("weights", {"twitter": 0.3, "telegram": 0.2, "news": 0.3, "onchain": 0.2})
    signals = aggregate(analyzed, weights)
    for sig in signals:
        save_signal(sig)

    # 输出汇总
    table_data = [[s.symbol, f"{s.score:.3f}", s.direction, f"{s.confidence:.2f}"] for s in signals]
    headers = ["Symbol", "Score", "Direction", "Confidence"]
    print(f"\n[sentiment] 生成 {len(signals)} 个情绪信号:\n")
    print(tabulate(table_data, headers=headers, tablefmt="simple"))


def run_sentiment_status() -> None:
    """查看最新情绪信号状态。"""
    from sentiment.store import query_latest_signal

    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", ""]
    table_data = []
    for sym in symbols:
        sig = query_latest_signal(sym)
        if sig:
            table_data.append([
                sig.symbol or "(global)",
                f"{sig.score:.3f}",
                sig.direction,
                f"{sig.confidence:.2f}",
            ])
        else:
            table_data.append([sym or "(global)", "-", "-", "-"])

    headers = ["Symbol", "Score", "Direction", "Confidence"]
    print("\n[sentiment] 最新情绪信号:\n")
    print(tabulate(table_data, headers=headers, tablefmt="simple"))


def run_portfolio_status(portfolio_config: dict) -> None:
    """查看组合最新状态：权重 + NAV。"""
    from portfolio.store import query_latest_weights, query_nav_history

    weights = query_latest_weights()
    nav_history = query_nav_history(limit=1)
    nav = nav_history[0]["nav"] if nav_history else None

    if not weights:
        print("[portfolio] 暂无组合权重数据，请先运行 portfolio rebalance")
        return

    table_data = [[sid, f"{w:.4f}"] for sid, w in sorted(weights.items())]
    headers = ["Strategy", "Weight"]
    nav_str = f"{nav:.4f}" if nav is not None else "N/A"
    print(f"\n[portfolio] 组合权重 (NAV={nav_str}):\n")
    print(tabulate(table_data, headers=headers, tablefmt="simple"))


def run_portfolio_rebalance(portfolio_config: dict) -> None:
    """重新计算组合权重并保存。"""
    if not portfolio_config.get("enabled"):
        print("[portfolio] 组合管理未启用（portfolio.enabled=false）")
        return

    from scanner.tracker import get_closed_trades
    from portfolio.tracker import compute_strategy_stats
    from portfolio.allocator import optimize_weights
    from portfolio.models import StrategyResult
    from portfolio.store import save_weights

    trades = get_closed_trades()
    if not trades:
        print("[portfolio] 暂无已关仓交易数据，无法计算权重")
        return

    # 按模式分组计算日收益
    returns_by_mode: dict[str, list[float]] = {}
    for t in trades:
        mode = t.get("mode", "accumulation") or "accumulation"
        ret = t.get("return_pct", 0.0) or 0.0
        returns_by_mode.setdefault(mode, []).append(ret)

    strategies = []
    for mode, rets in returns_by_mode.items():
        stats = compute_strategy_stats(mode, rets)
        strategies.append(StrategyResult(
            strategy_id=mode,
            sharpe=stats["sharpe"],
            win_rate=stats["win_rate"],
            max_drawdown=stats["max_drawdown"],
            daily_returns=rets,
        ))

    max_weight = portfolio_config.get("max_strategy_weight", 0.5)
    min_weight = portfolio_config.get("min_strategy_weight", 0.05)
    weights = optimize_weights(strategies, max_weight=max_weight, min_weight=min_weight)

    if not weights:
        print("[portfolio] 权重优化失败，无可用数据")
        return

    save_weights(weights)
    table_data = [[sid, f"{w:.4f}"] for sid, w in sorted(weights.items())]
    headers = ["Strategy", "Weight"]
    print("\n[portfolio] 组合再平衡完成:\n")
    print(tabulate(table_data, headers=headers, tablefmt="simple"))


def run_portfolio_report(portfolio_config: dict) -> None:
    """生成组合绩效 HTML 报告。"""
    from scanner.tracker import get_closed_trades
    from portfolio.tracker import generate_portfolio_report
    from portfolio.store import query_latest_weights

    trades = get_closed_trades()
    if not trades:
        print("[portfolio] 暂无已关仓交易数据")
        return

    returns_by_mode: dict[str, list[float]] = {}
    for t in trades:
        mode = t.get("mode", "accumulation") or "accumulation"
        ret = t.get("return_pct", 0.0) or 0.0
        returns_by_mode.setdefault(mode, []).append(ret)

    weights = query_latest_weights()
    if not weights:
        # 等权回退
        n = len(returns_by_mode)
        weights = {k: 1.0 / n for k in returns_by_mode} if n > 0 else {}

    os.makedirs("results", exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_path = f"results/portfolio_report_{ts}.html"
    generate_portfolio_report(returns_by_mode, weights, output_path)
    print(f"[portfolio] 绩效报告已生成: {output_path}")


def _build_legacy_argv(args: argparse.Namespace) -> list[str]:
    """将旧 flag 风格参数转换为新子命令 argv。"""
    argv = ["--config", args.config]

    if args.optimize:
        argv += ["optimize", "run", "--days", str(args.days)]
        if args.symbols:
            argv += ["--symbols"] + args.symbols
        return argv
    if args.retrain:
        return argv + ["retrain"]
    if args.optimize_report:
        return argv + ["optimize", "report"]
    if args.serve:
        return argv + ["serve"]
    if args.stats:
        cmd = argv + ["stats"]
        if args.json_only:
            cmd.append("--json-only")
        return cmd
    if args.track:
        return argv + ["track"]
    if args.history:
        return argv + ["history", args.history]
    if args.backtest:
        cmd = argv + ["backtest", "--days", str(args.days)]
        if args.symbols:
            cmd += ["--symbols"] + args.symbols
        if args.verify_signal:
            cmd.append("--verify-signal")
        if args.sensitivity:
            cmd.append("--sensitivity")
        return cmd

    # scan mode (default)
    cmd = argv + ["scan", "--mode", args.mode]
    if args.top:
        cmd += ["--top", str(args.top)]
    if args.symbols:
        cmd += ["--symbols"] + args.symbols
    if args.no_confirm:
        cmd.append("--no-confirm")
    return cmd


def main():
    import sys

    # 检测是否使用了新子命令格式
    known_subcommands = {"scan", "backtest", "track", "history", "serve", "stats", "optimize", "retrain", "sentiment", "portfolio"}
    if len(sys.argv) > 1 and sys.argv[1] in known_subcommands:
        from cli import main as cli_main
        cli_main(sys.argv[1:])
        return

    # 兼容旧 flag 格式 — 解析后转换为新子命令
    parser = argparse.ArgumentParser(description="币种形态筛选器（旧命令格式，建议使用子命令：coin scan / coin backtest / ...）")
    parser.add_argument("--mode", choices=["accumulation", "divergence", "breakout", "smc"], default="divergence")
    parser.add_argument("--top", type=int)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument("--track", action="store_true")
    parser.add_argument("--history", type=str)
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--verify-signal", action="store_true")
    parser.add_argument("--sensitivity", action="store_true")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--no-confirm", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--optimize", action="store_true")
    parser.add_argument("--retrain", action="store_true")
    parser.add_argument("--optimize-report", action="store_true")
    args = parser.parse_args()

    new_argv = _build_legacy_argv(args)
    print(f"[提示] 旧命令格式仍可用，推荐使用: python main.py {' '.join(new_argv[2:])}")

    from cli import main as cli_main
    cli_main(new_argv)


if __name__ == "__main__":
    main()
