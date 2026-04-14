import os
import threading
import time

from flask import Flask, jsonify, redirect, render_template, request, url_for

from scanner.tracker import (
    get_closed_trades_by_symbol,
    get_today_scans,
    get_tracked_symbols,
    query_scan_results,
)

# 手动扫描状态（单例，进程内共享）
_scan_lock = threading.Lock()
_scan_state: dict = {"running": False, "started_at": None, "finished_at": None, "error": None}


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    @app.route("/")
    def index():
        return render_template(
            "index.html",
            accum=get_today_scans("accumulation"),
            div=get_today_scans("divergence"),
            breakout=get_today_scans("breakout"),
        )

    @app.route("/history")
    def history():
        symbol = request.args.get("symbol", "").strip().upper().replace("-", "/")
        mode = request.args.get("mode", "").strip()
        scan_time_from = request.args.get("scan_time_from", "").strip()
        scan_time_to = request.args.get("scan_time_to", "").strip()
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1
        try:
            per_page = min(200, max(1, int(request.args.get("per_page", 50))))
        except ValueError:
            per_page = 50

        rows, total = query_scan_results(
            symbol=symbol or None,
            mode=mode or None,
            scan_time_from=scan_time_from or None,
            scan_time_to=scan_time_to or None,
            page=page,
            per_page=per_page,
        )
        total_pages = max(1, (total + per_page - 1) // per_page)

        return render_template(
            "history.html",
            rows=rows,
            total=total,
            page=page,
            total_pages=total_pages,
            per_page_eff=per_page,
            symbol=symbol,
            mode=mode,
            scan_time_from=scan_time_from,
            scan_time_to=scan_time_to,
        )

    @app.route("/scan", methods=["POST"])
    def trigger_scan():
        if not _scan_lock.acquire(blocking=False):
            return jsonify({"started": False, "reason": "已有扫描在进行中"}), 409

        def _run():
            _scan_state["running"] = True
            _scan_state["started_at"] = time.time()
            _scan_state["error"] = None
            try:
                from main import load_config, run, run_breakout, run_divergence
                cfg, sig_cfg, _, _ = load_config(
                    os.path.join(os.path.dirname(__file__), "..", "config.yaml")
                )
                try:
                    run(cfg, sig_cfg)
                except Exception as e:
                    _scan_state["error"] = f"accumulation: {e}"
                try:
                    run_divergence(cfg, sig_cfg)
                except Exception as e:
                    _scan_state["error"] = f"divergence: {e}"
                try:
                    run_breakout(cfg, sig_cfg)
                except Exception as e:
                    _scan_state["error"] = f"breakout: {e}"
            finally:
                _scan_state["running"] = False
                _scan_state["finished_at"] = time.time()
                _scan_lock.release()

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({"started": True})

    @app.route("/scan/status")
    def scan_status():
        return jsonify(dict(_scan_state))

    @app.route("/search")
    def search():
        symbol = request.args.get("symbol", "").strip().upper().replace("-", "/")
        if not symbol:
            return redirect(url_for("index"))
        return redirect(url_for("coin_detail", symbol_slug=symbol))

    @app.route("/coin/<path:symbol_slug>")
    def coin_detail(symbol_slug: str):
        symbol = symbol_slug.upper()
        scans, _ = query_scan_results(symbol=symbol, per_page=500, max_per_page=500)
        trades = get_closed_trades_by_symbol(symbol)
        return render_template(
            "coin.html",
            symbol=symbol,
            scans=scans,
            trades=trades,
        )

    return app


def main() -> None:
    host = os.environ.get("HISTORY_UI_HOST", "127.0.0.1")
    port_s = os.environ.get("HISTORY_UI_PORT", "5050")
    try:
        port = int(port_s)
    except ValueError:
        port = 5050
    debug = os.environ.get("HISTORY_UI_DEBUG", "").lower() in ("1", "true", "yes")
    app = create_app()
    app.run(host=host, port=port, debug=debug)
