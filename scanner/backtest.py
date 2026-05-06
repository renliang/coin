from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
from tabulate import tabulate

from scanner.confirmation import confirm_signal
from scanner.detector import detect_pattern
from scanner.scorer import score_result


RETURN_PERIODS = [3, 7, 14, 30]

# 模式标识
MODE_ACCUMULATION = "accumulation"
MODE_DIVERGENCE = "divergence"
MODE_BREAKOUT = "breakout"
MODE_SMC = "smc"
MODE_TREND = "trend"

VALID_MODES = (MODE_ACCUMULATION, MODE_DIVERGENCE, MODE_BREAKOUT, MODE_SMC, MODE_TREND)


@dataclass
class BacktestHit:
    symbol: str
    detect_date: str
    window_days: int
    drop_pct: float
    volume_ratio: float
    score: float
    returns: dict[str, float | None] = field(default_factory=dict)
    r_squared: float = 0.0
    max_daily_pct: float = 0.0
    mode: str = MODE_ACCUMULATION
    extras: dict = field(default_factory=dict)


# ─── 通用滑动窗口工具 ────────────────────────────────────────────────────

def _compute_returns(closes: np.ndarray, base_idx: int, n: int) -> dict[str, float | None]:
    base_price = closes[base_idx]
    returns: dict[str, float | None] = {}
    for period in RETURN_PERIODS:
        future_idx = base_idx + period
        if future_idx < n:
            returns[f"{period}d"] = (closes[future_idx] - base_price) / base_price
        else:
            returns[f"{period}d"] = None
    return returns


def _sliding_backtest(
    klines: dict[str, pd.DataFrame],
    detect_fn: Callable[[pd.DataFrame], tuple[bool, float, int, dict] | None],
    dedup_gap: int,
    min_history: int,
    mode_label: str,
) -> list[BacktestHit]:
    """通用滑动窗口回测。

    detect_fn(slice_df) 返回:
      None 或 (matched, score, window_days, extras_dict)。
      只有 matched=True 时才会被记录;extras_dict 用于装载模式专属字段。
    """
    all_hits: list[BacktestHit] = []
    for symbol, df in klines.items():
        n = len(df)
        if n < min_history + 1:
            continue
        closes = df["close"].values.astype(float)
        dates = df["timestamp"].values
        last_hit_idx = -dedup_gap

        for i in range(min_history, n + 1):
            if i - last_hit_idx < dedup_gap:
                continue
            slice_df = df.iloc[:i]
            res = detect_fn(slice_df)
            if not res:
                continue
            matched, score, window_days, extras = res
            if not matched:
                continue
            last_hit_idx = i
            returns = _compute_returns(closes, i - 1, n)
            detect_date = str(pd.Timestamp(dates[i - 1]).date())
            all_hits.append(BacktestHit(
                symbol=symbol,
                detect_date=detect_date,
                window_days=window_days,
                drop_pct=float(extras.pop("drop_pct", 0.0)),
                volume_ratio=float(extras.pop("volume_ratio", 0.0)),
                score=float(score),
                returns=returns,
                r_squared=float(extras.pop("r_squared", 0.0)),
                max_daily_pct=float(extras.pop("max_daily_pct", 0.0)),
                mode=mode_label,
                extras=extras,
            ))
    return all_hits


# ─── 模式 1: accumulation ───────────────────────────────────────────────

def _run_accumulation_backtest(
    klines: dict[str, pd.DataFrame],
    config: dict,
    confirmation: bool = False,
    confirmation_min_pass: int = 3,
) -> list[BacktestHit]:
    """底部蓄力形态回测(原始 run_backtest 逻辑)。"""
    window_min = config.get("window_min_days", 7)
    window_max = config.get("window_max_days", 14)
    vol_ratio = config.get("volume_ratio", 0.5)
    drop_min = config.get("drop_min", 0.05)
    drop_max = config.get("drop_max", 0.15)
    max_daily = config.get("max_daily_change", 0.05)

    all_hits: list[BacktestHit] = []
    for symbol, df in klines.items():
        closes = df["close"].values.astype(float)
        dates = df["timestamp"].values
        n = len(df)
        last_hit_idx = -window_max

        for i in range(window_max, n + 1):
            if i - last_hit_idx < window_max:
                continue
            slice_df = df.iloc[:i]
            result = detect_pattern(
                slice_df,
                window_min_days=window_min,
                window_max_days=window_max,
                volume_ratio=vol_ratio,
                drop_min=drop_min,
                drop_max=drop_max,
                max_daily_change=max_daily,
            )
            if not result.matched:
                continue
            last_hit_idx = i
            score = score_result(
                result, drop_min=drop_min, drop_max=drop_max, max_daily_change=max_daily,
            )
            if confirmation:
                conf = confirm_signal(slice_df, "long", confirmation_min_pass)
                if not conf.passed:
                    last_hit_idx = -window_max
                    continue
                score = score + conf.bonus
            returns = _compute_returns(closes, i - 1, n)
            detect_date = str(pd.Timestamp(dates[i - 1]).date())
            all_hits.append(BacktestHit(
                symbol=symbol,
                detect_date=detect_date,
                window_days=result.window_days,
                drop_pct=result.drop_pct,
                volume_ratio=result.volume_ratio,
                score=score,
                returns=returns,
                r_squared=result.r_squared,
                max_daily_pct=result.max_daily_pct,
                mode=MODE_ACCUMULATION,
            ))
    return all_hits


# ─── 模式 2: divergence ─────────────────────────────────────────────────

def _run_divergence_backtest(
    klines: dict[str, pd.DataFrame], config: dict,
) -> list[BacktestHit]:
    """MACD 底背离回测(只记录看多信号 bullish)。"""
    from scanner.divergence import detect_divergence

    div_cfg = config.get("divergence", {}) if isinstance(config.get("divergence"), dict) else {}
    pivot_len = div_cfg.get("pivot_len", 7)
    min_distance = div_cfg.get("min_distance", 15)
    max_distance = div_cfg.get("max_distance", 60)
    min_price_diff = div_cfg.get("min_price_diff", 0.05)

    def detect(slice_df: pd.DataFrame):
        result = detect_divergence(
            slice_df,
            pivot_len=pivot_len,
            min_distance=min_distance,
            max_distance=max_distance,
            min_price_diff=min_price_diff,
        )
        if result.divergence_type != "bullish":
            return None
        return True, result.score, int(result.pivot_distance), {
            "divergence_type": result.divergence_type,
        }

    # 去重间隔取 max_distance,避免相邻 pivot 触发重复信号
    return _sliding_backtest(
        klines,
        detect_fn=detect,
        dedup_gap=max_distance,
        min_history=40,
        mode_label=MODE_DIVERGENCE,
    )


# ─── 模式 3: breakout ───────────────────────────────────────────────────

def _run_breakout_backtest(
    klines: dict[str, pd.DataFrame], config: dict,
) -> list[BacktestHit]:
    """天量回踩二攻回测。"""
    from scanner.breakout import detect_breakout

    breakout_cfg = config.get("breakout", {}) if isinstance(config.get("breakout"), dict) else {}
    spike_mult = breakout_cfg.get("spike_multiplier", 5.0)
    shrink_thr = breakout_cfg.get("shrink_threshold", 0.3)
    reattack_mult = breakout_cfg.get("reattack_multiplier", 2.0)
    max_pullback = breakout_cfg.get("max_pullback_days", 10)
    freshness = breakout_cfg.get("freshness_days", 3)

    def detect(slice_df: pd.DataFrame):
        result = detect_breakout(
            slice_df,
            spike_multiplier=spike_mult,
            shrink_threshold=shrink_thr,
            reattack_multiplier=reattack_mult,
            max_pullback_days=max_pullback,
            freshness_days=freshness,
        )
        if not result.matched:
            return None
        return True, result.score, int(result.days_since_spike), {
            "spike_volume_ratio": result.spike_volume_ratio,
            "spike_date": result.spike_date,
            "reattack_close": result.reattack_close,
        }

    # 去重: 一个突破信号约 10-25 天事件窗,取 15 天保险
    return _sliding_backtest(
        klines,
        detect_fn=detect,
        dedup_gap=15,
        min_history=25,
        mode_label=MODE_BREAKOUT,
    )


# ─── 模式 4: smc ────────────────────────────────────────────────────────

def _run_smc_backtest(
    klines: dict[str, pd.DataFrame], config: dict,
) -> list[BacktestHit]:
    """Smart Money Concepts 回测(只记录看多 bullish 结构)。"""
    from scanner.smc import detect_smc

    smc_cfg = config.get("smc", {}) if isinstance(config.get("smc"), dict) else {}
    swing_length = smc_cfg.get("swing_length", 10)
    freshness_candles = smc_cfg.get("freshness_candles", 10)
    fvg_lookback = smc_cfg.get("fvg_lookback", 30)
    ob_lookback = smc_cfg.get("ob_lookback", 30)
    proximity_max = smc_cfg.get("proximity_max", 0.05)

    def detect(slice_df: pd.DataFrame):
        result = detect_smc(
            slice_df,
            swing_length=swing_length,
            freshness_candles=freshness_candles,
            fvg_lookback=fvg_lookback,
            ob_lookback=ob_lookback,
            proximity_max=proximity_max,
        )
        if not result.matched or result.direction != "bullish":
            return None
        return True, result.score, 0, {
            "structure_type": result.structure_type,
            "has_fvg": result.has_fvg,
            "has_ob": result.has_ob,
        }

    return _sliding_backtest(
        klines,
        detect_fn=detect,
        dedup_gap=freshness_candles,
        min_history=swing_length * 2 + 5,
        mode_label=MODE_SMC,
    )


# ─── 模式 5: trend(滑窗入场信号回测) ───────────────────────────────────

def _run_trend_backtest_signals(
    klines: dict[str, pd.DataFrame], config: dict,
) -> list[BacktestHit]:
    """趋势跟踪入场信号回测。

    与其他模式不同: scan_trend_entries 需要传入完整 klines dict + BTC 大盘,
    因此按时间步 t 切片所有 symbol 后整体调用,再按 symbol 去重。
    评分用 breakout_strength 线性映射到 [0.5, 1.0]。
    """
    from scanner.trend_scanner import scan_trend_entries

    trend_cfg = config.get("trend_follow", {}) if isinstance(config.get("trend_follow"), dict) else {}
    entry_n = trend_cfg.get("entry_n", 30)
    exit_n = trend_cfg.get("exit_n", 15)
    trend_ema = trend_cfg.get("trend_ema", 200)
    btc_trend_ema = trend_cfg.get("btc_trend_ema", 100)
    atr_period = trend_cfg.get("atr_period", 14)
    chandelier_mult = trend_cfg.get("chandelier_mult", 3.0)

    btc_df = None
    for sym in ("BTC/USDT", "BTCUSDT"):
        if sym in klines:
            btc_df = klines[sym]
            break

    if not klines:
        return []

    timeline = max(len(df) for df in klines.values())
    min_required = max(entry_n, trend_ema, atr_period) + 1
    if timeline < min_required + 1:
        return []

    last_hit: dict[str, int] = {}
    all_hits: list[BacktestHit] = []

    for t in range(min_required, timeline + 1):
        sliced = {sym: df.iloc[:t] for sym, df in klines.items() if len(df) >= t}
        btc_slice = btc_df.iloc[:t] if btc_df is not None and len(btc_df) >= t else None

        signals = scan_trend_entries(
            sliced,
            btc_slice,
            entry_n=entry_n,
            exit_n=exit_n,
            trend_ema=trend_ema,
            btc_trend_ema=btc_trend_ema,
            atr_period=atr_period,
            chandelier_mult=chandelier_mult,
        )

        for sig in signals:
            prev = last_hit.get(sig.symbol, -entry_n)
            if t - prev < entry_n:
                continue
            last_hit[sig.symbol] = t

            df = klines[sig.symbol]
            n = len(df)
            closes = df["close"].values.astype(float)
            dates = df["timestamp"].values
            returns = _compute_returns(closes, t - 1, n)
            detect_date = str(pd.Timestamp(dates[t - 1]).date())
            score = float(min(1.0, max(0.0, 0.5 + sig.breakout_strength * 10.0)))
            all_hits.append(BacktestHit(
                symbol=sig.symbol,
                detect_date=detect_date,
                window_days=entry_n,
                drop_pct=0.0,
                volume_ratio=0.0,
                score=score,
                returns=returns,
                mode=MODE_TREND,
                extras={
                    "breakout_strength": float(sig.breakout_strength),
                    "atr": float(sig.atr),
                    "donchian_high": float(sig.donchian_high),
                    "stop_chandelier": float(sig.initial_stop_chandelier),
                    "stop_donchian": float(sig.initial_stop_donchian),
                },
            ))
    return all_hits


# ─── 顶层入口 ────────────────────────────────────────────────────────────

def run_backtest(
    klines: dict[str, pd.DataFrame],
    config: dict,
    confirmation: bool = False,
    confirmation_min_pass: int = 3,
    mode: str = MODE_ACCUMULATION,
) -> list[BacktestHit]:
    """对所有币种做滑动窗口回扫,返回命中列表。

    Args:
        mode: 检测模式,见 VALID_MODES。默认 accumulation 以保持向后兼容。
    """
    if mode == MODE_ACCUMULATION:
        return _run_accumulation_backtest(klines, config, confirmation, confirmation_min_pass)
    if mode == MODE_DIVERGENCE:
        return _run_divergence_backtest(klines, config)
    if mode == MODE_BREAKOUT:
        return _run_breakout_backtest(klines, config)
    if mode == MODE_SMC:
        return _run_smc_backtest(klines, config)
    if mode == MODE_TREND:
        return _run_trend_backtest_signals(klines, config)
    raise ValueError(f"unknown backtest mode: {mode}; valid={VALID_MODES}")


# ─── 统计与格式化(沿用旧实现) ───────────────────────────────────────────

def _calc_period_stats(hits: list[BacktestHit], period: str) -> dict:
    """计算单个周期的统计指标。"""
    values = [h.returns[period] for h in hits if h.returns.get(period) is not None]
    if not values:
        return {"count": 0, "win_rate": 0.0, "mean": 0.0, "median": 0.0, "max": 0.0, "min": 0.0}
    arr = np.array(values)
    return {
        "count": len(arr),
        "win_rate": float(np.mean(arr > 0)),
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "max": float(np.max(arr)),
        "min": float(np.min(arr)),
    }


def compute_stats(hits: list[BacktestHit]) -> dict:
    """计算整体统计和分档统计。"""
    periods = [f"{p}d" for p in RETURN_PERIODS]

    overall = {}
    for period in periods:
        overall[period] = _calc_period_stats(hits, period)

    tiers = {
        "high": [h for h in hits if h.score >= 0.6],
        "mid": [h for h in hits if 0.4 <= h.score < 0.6],
        "low": [h for h in hits if h.score < 0.4],
    }
    by_tier = {}
    for tier_name, tier_hits in tiers.items():
        by_tier[tier_name] = {}
        for period in periods:
            by_tier[tier_name][period] = _calc_period_stats(tier_hits, period)

    return {
        "total_hits": len(hits),
        "overall": overall,
        "by_tier": by_tier,
    }


def split_hits_by_median_date(hits: list[BacktestHit]) -> tuple[list[BacktestHit], list[BacktestHit]]:
    """按检测日期中位数将命中分为前半段与后半段(用于简易样本外/分段对比)。

    日期少于 2 条时,后半段为空列表。
    """
    if len(hits) < 2:
        return hits, []
    dated = sorted(hits, key=lambda h: h.detect_date)
    mid = len(dated) // 2
    return dated[:mid], dated[mid:]


def compute_tier_period_stat(hits: list[BacktestHit], tier_min_score: float, period: str) -> dict:
    """计算 score >= tier_min_score 的子集在某个持有周期上的统计(与 signal 门槛对齐)。"""
    sub = [h for h in hits if h.score >= tier_min_score]
    return _calc_period_stats(sub, period)


def compute_signal_verification_splits(
    hits: list[BacktestHit],
    min_score: float = 0.6,
    period: str = "3d",
) -> dict:
    """分段对比「高分档」在指定周期上的胜率/均值,便于核对样本外表现。

    返回 early/late/full 三组统计,对应 median 前/后/全部。
    """
    early, late = split_hits_by_median_date(hits)
    return {
        "period": period,
        "min_score": min_score,
        "full": compute_tier_period_stat(hits, min_score, period),
        "early_window": compute_tier_period_stat(early, min_score, period),
        "late_window": compute_tier_period_stat(late, min_score, period),
        "early_hits": len(early),
        "late_hits": len(late),
    }


def format_signal_verification(sv: dict) -> str:
    """格式化分段 signal 验证结果。"""
    lines = [
        f"=== Signal 分段验证 (score≥{sv['min_score']}, {sv['period']}) ===",
        f"前半段命中数: {sv['early_hits']}, 后半段命中数: {sv['late_hits']}",
        "",
    ]
    for label, key in [("全部", "full"), ("前半段(较早)", "early_window"), ("后半段(较晚/近似样本外)", "late_window")]:
        s = sv[key]
        lines.append(
            f"{label}: count={s['count']}, win_rate={s['win_rate']:.1%}, "
            f"mean={s['mean']:.2%}, median={s['median']:.2%}",
        )
    lines.append("")
    lines.append("说明: 后半段统计在命中数较多时可作简易样本外参考；若后半段明显弱于前半段,需警惕过拟合。")
    return "\n".join(lines)


def format_stats(stats: dict) -> str:
    """格式化统计结果为终端表格字符串。"""
    lines = []
    lines.append(f"总命中次数: {stats['total_hits']}")
    lines.append("")

    lines.append("=== 整体统计 ===")
    lines.append("")
    table = []
    for period in ["3d", "7d", "14d", "30d"]:
        s = stats["overall"][period]
        table.append([
            period,
            s["count"],
            f"{s['win_rate']:.1%}",
            f"{s['mean']:.2%}",
            f"{s['median']:.2%}",
            f"{s['max']:.2%}",
            f"{s['min']:.2%}",
        ])
    headers = ["周期", "样本数", "胜率", "平均收益", "中位数", "最大收益", "最大亏损"]
    lines.append(tabulate(table, headers=headers, tablefmt="simple"))
    lines.append("")

    tier_names = {"high": "高分(≥0.6)", "mid": "中分(0.4-0.6)", "low": "低分(<0.4)"}
    for tier_key, tier_label in tier_names.items():
        lines.append(f"=== {tier_label} ===")
        lines.append("")
        table = []
        for period in ["3d", "7d", "14d", "30d"]:
            s = stats["by_tier"][tier_key][period]
            table.append([
                period,
                s["count"],
                f"{s['win_rate']:.1%}",
                f"{s['mean']:.2%}",
                f"{s['median']:.2%}",
                f"{s['max']:.2%}",
                f"{s['min']:.2%}",
            ])
        lines.append(tabulate(table, headers=headers, tablefmt="simple"))
        lines.append("")

    return "\n".join(lines)
