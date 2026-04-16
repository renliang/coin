"""Flask API Blueprint — JSON endpoints for React SPA."""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from scanner.stats import (
    compute_stats,
    compute_stats_by_mode,
    compute_stats_by_month,
    compute_stats_by_score_tier,
)
from scanner.tracker import (
    get_active_signals,
    get_closed_trades,
    get_closed_trades_by_symbol,
    get_open_positions,
    get_signal_count_trend,
    get_signal_outcomes,
    get_today_scans,
    query_scan_results,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/dashboard")
def dashboard():
    """聚合 Dashboard 数据：KPI + Top5 信号 + 活跃持仓 + 7日命中率。

    如果今天没有扫描数据，fallback 到最近一次扫描。
    """
    accum = get_today_scans("accumulation")
    div = get_today_scans("divergence")
    breakout = get_today_scans("breakout")

    all_signals = accum + div + breakout
    is_today = True
    last_scan_time = None

    # fallback：今天无数据时展示最近一次扫描
    if not all_signals:
        is_today = False
        all_signals, last_scan_time = _get_latest_scan_signals()

    all_signals.sort(key=lambda s: s.get("score", 0), reverse=True)

    # 按模式统计
    signal_counts = {"accumulation": 0, "divergence": 0, "breakout": 0}
    for s in all_signals:
        m = s.get("mode", "")
        if m in signal_counts:
            signal_counts[m] += 1

    positions = get_open_positions()
    closed = get_closed_trades()

    # 今日盈亏（今天平仓的交易）
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_closed = [t for t in closed if (t.get("closed_at") or "")[:10] == today_str]
    today_pnl_pct = sum(t.get("pnl_pct", 0) for t in today_closed)

    # 总胜率
    overall = compute_stats(closed)

    # 7日命中率
    hit_rate = _compute_7d_hit_rate(closed)

    return jsonify({
        "kpi": {
            "today_signals": len(all_signals),
            "active_positions": len(positions),
            "today_pnl_pct": round(today_pnl_pct, 4),
            "today_pnl_count": len(today_closed),
            "win_rate": overall.get("win_rate", 0),
            "total_trades": overall.get("total", 0),
        },
        "top_signals": all_signals[:5],
        "positions": positions,
        "hit_rate_7d": hit_rate,
        "signal_counts": signal_counts,
        "is_today": is_today,
        "last_scan_time": last_scan_time,
    })


@api_bp.route("/signals")
def signals():
    """分页查询信号，支持筛选。"""
    mode = request.args.get("mode", "").strip() or None
    min_score = request.args.get("min_score", type=float)
    date_from = request.args.get("date_from", "").strip() or None
    date_to = request.args.get("date_to", "").strip() or None
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    rows, total = query_scan_results(
        mode=mode,
        scan_time_from=date_from,
        scan_time_to=date_to,
        page=page,
        per_page=per_page,
    )

    if min_score is not None:
        rows = [r for r in rows if r.get("score", 0) >= min_score]

    total_pages = max(1, (total + per_page - 1) // per_page)

    return jsonify({
        "data": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    })


@api_bp.route("/positions")
def positions():
    """活跃持仓列表。"""
    return jsonify({"data": get_open_positions()})


@api_bp.route("/positions/closed")
def positions_closed():
    """已平仓交易，分页。"""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    all_trades = get_closed_trades()
    total = len(all_trades)
    start = (page - 1) * per_page
    end = start + per_page
    page_trades = all_trades[start:end]

    return jsonify({
        "data": page_trades,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    })


@api_bp.route("/coin/<path:symbol>")
def coin_detail(symbol: str):
    """单币种详情：扫描记录 + 交易记录。"""
    symbol = symbol.upper()
    scans, total = query_scan_results(symbol=symbol, per_page=500, max_per_page=500)
    trades = get_closed_trades_by_symbol(symbol)
    return jsonify({
        "symbol": symbol,
        "scans": scans,
        "trades": trades,
        "total_scans": total,
    })


@api_bp.route("/performance")
def performance():
    """绩效分析：总体 + 按模式/分数/月份。"""
    trades = get_closed_trades()
    overall = compute_stats(trades)
    by_mode = compute_stats_by_mode(trades)
    by_score = compute_stats_by_score_tier(trades)
    by_month = compute_stats_by_month(trades)

    # 累计盈亏曲线
    cumulative = []
    cum_pnl = 0.0
    sorted_trades = sorted(trades, key=lambda t: t.get("closed_at", ""))
    for t in sorted_trades:
        cum_pnl += t.get("pnl_pct", 0)
        cumulative.append({
            "date": (t.get("closed_at") or "")[:10],
            "cumulative_pnl": round(cum_pnl, 4),
        })

    return jsonify({
        "overall": overall,
        "by_mode": by_mode,
        "by_score": by_score,
        "by_month": by_month,
        "cumulative_pnl": cumulative,
    })


def _get_latest_scan_signals() -> tuple[list[dict], str | None]:
    """获取最近一天的所有扫描信号（跨模式合并），返回 (signals, scan_time_str)。"""
    from scanner.tracker import _get_conn
    conn = _get_conn()
    try:
        # 找最近一次扫描的日期
        row = conn.execute(
            "SELECT scan_time FROM scans ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return [], None
        last_time = row["scan_time"]
        last_day = last_time[:10]

        # 取该天所有信号（每个模式取最新一次 scan_id）
        all_signals = []
        for mode in ("accumulation", "divergence", "breakout"):
            scan_row = conn.execute(
                """SELECT MAX(s.id) AS max_id FROM scans s
                   JOIN scan_results r ON r.scan_id = s.id
                   WHERE r.mode = ? AND s.scan_time >= ?""",
                (mode, last_day + " 00:00:00"),
            ).fetchone()
            max_id = scan_row["max_id"] if scan_row else None
            if max_id is None:
                continue
            rows = conn.execute(
                """SELECT r.symbol, r.price, r.score, r.entry_price,
                          r.stop_loss_price, r.take_profit_price, r.signal_type, r.mode
                   FROM scan_results r WHERE r.scan_id = ? ORDER BY r.score DESC""",
                (max_id,),
            ).fetchall()
            all_signals.extend(dict(r) for r in rows)
        return all_signals, last_time
    finally:
        conn.close()


@api_bp.route("/scan/status")
def scan_status():
    """扫描状态（复用 app 层状态）。"""
    from history_ui.app import _scan_state
    return jsonify(dict(_scan_state))


@api_bp.route("/scan", methods=["POST"])
def trigger_scan():
    """触发扫描（复用 app 层逻辑）。"""
    import history_ui.app as _app
    if not _app._scan_lock.acquire(blocking=False):
        return jsonify({"started": False, "reason": "已有扫描在进行中"}), 409

    import threading

    def _run():
        _app._scan_state["running"] = True
        _app._scan_state["started_at"] = __import__("time").time()
        _app._scan_state["error"] = None
        try:
            import os
            from main import load_config, run, run_breakout, run_divergence
            cfg, sig_cfg, _, _ = load_config(
                os.path.join(os.path.dirname(__file__), "..", "config.yaml")
            )
            for fn, name in [(run, "accumulation"), (run_divergence, "divergence"), (run_breakout, "breakout")]:
                try:
                    fn(cfg, sig_cfg)
                except Exception as e:
                    _app._scan_state["error"] = f"{name}: {e}"
        finally:
            _app._scan_state["running"] = False
            _app._scan_state["finished_at"] = __import__("time").time()
            _app._scan_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"started": True})


@api_bp.route("/klines/<path:symbol>")
def klines(symbol: str):
    """获取某币种最近 N 天的 OHLCV K线数据。"""
    days = request.args.get("days", 30, type=int)
    days = min(max(7, days), 180)
    symbol = symbol.upper()
    try:
        from scanner.kline import fetch_klines
        df = fetch_klines(symbol, days=days)
        if df is None or df.empty:
            return jsonify({"error": f"No klines for {symbol}"}), 404
        data = []
        for _, row in df.iterrows():
            data.append({
                "timestamp": str(row["timestamp"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
        return jsonify({"symbol": symbol, "days": days, "data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/signals/active")
def active_signals():
    """活跃信号（含当前价格、未实现盈亏）。"""
    signals = get_active_signals()
    # 计算接近 SL/TP 的标记
    for sig in signals:
        sig["approaching"] = None
        current = sig.get("current_price")
        entry = sig.get("entry_price") or sig.get("price")
        sl = sig.get("stop_loss_price")
        tp = sig.get("take_profit_price")
        if current and entry and sl and tp:
            sl_dist = abs(current - sl) / abs(entry - sl) if abs(entry - sl) > 0 else 1
            tp_dist = abs(tp - current) / abs(tp - entry) if abs(tp - entry) > 0 else 1
            if sl_dist < 0.3:
                sig["approaching"] = "sl"
            elif tp_dist < 0.3:
                sig["approaching"] = "tp"
    return jsonify({"data": signals})


@api_bp.route("/signals/outcomes")
def signal_outcomes():
    """近 30 天信号结果分布。"""
    days = request.args.get("days", 30, type=int)
    outcomes = get_signal_outcomes(days=days)
    return jsonify({"data": outcomes})


@api_bp.route("/signals/trend")
def signal_trend():
    """近 7 天每天各模式信号数量趋势。"""
    days = request.args.get("days", 7, type=int)
    trend = get_signal_count_trend(days=days)
    return jsonify({"data": trend})


@api_bp.route("/config", methods=["GET"])
def get_config():
    """读取 config.yaml（跳过 numpy 序列化字段）。"""
    import os
    import yaml
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    with open(config_path) as f:
        raw = f.read()
    # 安全加载：跳过 numpy 对象，用 safe_load 的 fallback
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        data = {}
    if data is None:
        data = {}
    # 清理 numpy 序列化的 optimized 字段
    if "optimized" in data:
        opt = data["optimized"]
        for k, v in list(opt.items()):
            if not isinstance(v, (int, float, bool, str, type(None))):
                opt[k] = None
    return jsonify(data)


def _compute_7d_hit_rate(closed_trades: list[dict]) -> list[dict]:
    """近7天每天各模式的胜率。"""
    today = datetime.now().date()
    result = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        day_trades = [
            t for t in closed_trades
            if (t.get("closed_at") or "")[:10] == day_str
        ]
        day_data = {"date": day_str, "total": len(day_trades)}
        if day_trades:
            day_data["wins"] = sum(1 for t in day_trades if t.get("pnl_pct", 0) > 0)
            day_data["win_rate"] = round(day_data["wins"] / len(day_trades), 4)
        else:
            day_data["wins"] = 0
            day_data["win_rate"] = 0
        result.append(day_data)
    return result
