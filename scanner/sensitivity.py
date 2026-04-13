"""scanner 参数敏感性：在固定 K 线集上对比形态命中次数随配置的变化。"""

from copy import deepcopy

from scanner.backtest import run_backtest


def one_variation(
    klines: dict,
    base_config: dict,
    overrides: dict,
    label: str,
) -> dict:
    cfg = deepcopy(base_config)
    cfg.update(overrides)
    hits = run_backtest(klines, cfg)
    return {
        "label": label,
        "overrides": overrides,
        "hit_count": len(hits),
    }


def run_scanner_sensitivity_grid(
    klines: dict,
    base_config: dict | None = None,
) -> list[dict]:
    """对计划中的关键维度各做一次 one-off 扰动，观察命中数量变化。

    base_config 默认使用与 tests 一致的蓄力参数。
    """
    base = base_config or {
        "window_min_days": 7,
        "window_max_days": 14,
        "volume_ratio": 0.5,
        "drop_min": 0.05,
        "drop_max": 0.15,
        "max_daily_change": 0.05,
    }
    base_hits = len(run_backtest(klines, base))

    rows: list[dict] = [
        {"label": "baseline", "overrides": {}, "hit_count": base_hits},
    ]

    experiments = [
        ("max_daily_change=0.08", {"max_daily_change": 0.08}),
        ("max_daily_change=0.03", {"max_daily_change": 0.03}),
        ("drop_max=0.20", {"drop_max": 0.20}),
        ("drop_min=0.03", {"drop_min": 0.03}),
        ("volume_ratio=0.7", {"volume_ratio": 0.7}),
    ]
    for label, ov in experiments:
        rows.append(one_variation(klines, base, ov, label))

    return rows


def format_sensitivity_table(rows: list[dict]) -> str:
    from tabulate import tabulate

    table = [[r["label"], r["hit_count"], str(r.get("overrides") or {})] for r in rows]
    return tabulate(table, headers=["配置", "命中数", "相对基线的覆盖"], tablefmt="simple")


def sensitivity_market_cap_note(skip_filter: bool) -> str:
    """市值过滤开关对宇宙的影响需在实跑扫描时观察；离线敏感性仅记录状态。"""
    return "skip_market_cap_filter=%s（仅影响 run() 第4步，不参与 run_backtest 命中数）" % skip_filter
