"""信号生命周期管理 — 刷新价格、检查状态转换、过期处理。"""

from datetime import datetime, timedelta

from scanner.tracker import get_active_signals, update_signal_lifecycle


def refresh_signal_prices(fetch_price_fn) -> int:
    """刷新所有活跃信号的当前价格和未实现盈亏。

    fetch_price_fn: callable(symbol) -> float | None
    返回成功刷新的信号数量。
    """
    signals = get_active_signals()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updated = 0

    for sig in signals:
        price = fetch_price_fn(sig["symbol"])
        if price is None:
            continue

        entry = sig.get("entry_price") or sig["price"]
        is_short = sig.get("signal_type") == "顶背离"

        if is_short:
            pnl_pct = (entry - price) / entry * 100
        else:
            pnl_pct = (price - entry) / entry * 100

        update_signal_lifecycle(
            sig["id"],
            sig["lifecycle_state"],
            current_price=price,
            unrealized_pnl_pct=round(pnl_pct, 2),
            price_updated_at=now,
        )
        updated += 1

    return updated


def check_lifecycle_transitions() -> dict:
    """检查状态转换：

    - detected -> entered: 当 current_price 触及 entry_price
    - entered -> tp_hit:   当 current_price 达到 take_profit_price
    - entered -> sl_hit:   当 current_price 达到 stop_loss_price
    """
    signals = get_active_signals()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    transitions = {"entered": 0, "tp_hit": 0, "sl_hit": 0}

    for sig in signals:
        current = sig.get("current_price")
        if current is None:
            continue

        entry = sig.get("entry_price")
        sl = sig.get("stop_loss_price")
        tp = sig.get("take_profit_price")
        state = sig["lifecycle_state"]
        is_short = sig.get("signal_type") == "顶背离"

        if state == "detected" and entry:
            if is_short:
                triggered = current >= entry
            else:
                triggered = current <= entry
            if triggered:
                update_signal_lifecycle(sig["id"], "entered", entered_at=now)
                transitions["entered"] += 1
                state = "entered"

        if state == "entered":
            if tp and not is_short and current >= tp:
                update_signal_lifecycle(sig["id"], "tp_hit", closed_at=now)
                transitions["tp_hit"] += 1
            elif tp and is_short and current <= tp:
                update_signal_lifecycle(sig["id"], "tp_hit", closed_at=now)
                transitions["tp_hit"] += 1
            elif sl and not is_short and current <= sl:
                update_signal_lifecycle(sig["id"], "sl_hit", closed_at=now)
                transitions["sl_hit"] += 1
            elif sl and is_short and current >= sl:
                update_signal_lifecycle(sig["id"], "sl_hit", closed_at=now)
                transitions["sl_hit"] += 1

    return transitions


def expire_stale_signals(hold_days: int = 3) -> int:
    """将超过 hold_days 天且仍为 detected/entered 的信号标记为 expired。"""
    signals = get_active_signals()
    now = datetime.now()
    cutoff = now - timedelta(days=hold_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    expired = 0

    for sig in signals:
        scan_time = sig.get("scan_time", "")
        if scan_time and scan_time < cutoff_str:
            update_signal_lifecycle(sig["id"], "expired", closed_at=now_str)
            expired += 1

    return expired
