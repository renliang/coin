"""信号成功率统计分析。"""


def compute_stats(trades: list[dict]) -> dict:
    if not trades:
        return {
            "total": 0, "wins": 0, "win_rate": 0,
            "avg_pnl_pct": 0, "profit_factor": 0,
            "max_gain": 0, "max_loss": 0,
        }
    total = len(trades)
    wins = sum(1 for t in trades if t["pnl_pct"] > 0)
    win_rate = wins / total
    pnl_pcts = [t["pnl_pct"] for t in trades]
    avg_pnl_pct = sum(pnl_pcts) / total
    total_gain = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    total_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    profit_factor = total_gain / total_loss if total_loss > 0 else total_gain
    return {
        "total": total,
        "wins": wins,
        "win_rate": round(win_rate, 4),
        "avg_pnl_pct": round(avg_pnl_pct, 6),
        "profit_factor": round(profit_factor, 2),
        "max_gain": max(pnl_pcts),
        "max_loss": min(pnl_pcts) if min(pnl_pcts) < 0 else 0,
    }


def _group_by(trades: list[dict], key_fn) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for t in trades:
        k = key_fn(t)
        groups.setdefault(k, []).append(t)
    return groups


def compute_stats_by_mode(trades: list[dict]) -> dict[str, dict]:
    groups = _group_by(trades, lambda t: t.get("mode", ""))
    return {mode: compute_stats(group) for mode, group in sorted(groups.items())}


def compute_stats_by_score_tier(trades: list[dict]) -> dict[str, dict]:
    def tier(t):
        s = t.get("score", 0)
        if s >= 0.8:
            return "0.8+"
        if s >= 0.7:
            return "0.7-0.8"
        return "0.6-0.7"
    groups = _group_by(trades, tier)
    order = ["0.8+", "0.7-0.8", "0.6-0.7"]
    return {k: compute_stats(groups.get(k, [])) for k in order if k in groups}


def compute_stats_by_month(trades: list[dict]) -> dict[str, dict]:
    def month_key(t):
        return t.get("closed_at", "")[:7]
    groups = _group_by(trades, month_key)
    return {month: compute_stats(group) for month, group in sorted(groups.items(), reverse=True)}
