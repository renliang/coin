import os

from flask import Flask, render_template, request

from scanner.tracker import query_scan_results


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    @app.route("/")
    def index():
        symbol = request.args.get("symbol", "").strip() or None
        mode = request.args.get("mode", "").strip() or None
        scan_time_from = request.args.get("scan_time_from", "").strip() or None
        scan_time_to = request.args.get("scan_time_to", "").strip() or None

        try:
            page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            page = 1
        try:
            per_page = int(request.args.get("per_page", "50"))
        except ValueError:
            per_page = 50

        rows, total = query_scan_results(
            symbol=symbol,
            mode=mode,
            scan_time_from=scan_time_from,
            scan_time_to=scan_time_to,
            page=page,
            per_page=per_page,
        )

        per_page_eff = min(max(1, per_page), 200)
        total_pages = max(1, (total + per_page_eff - 1) // per_page_eff) if total else 1
        if page > total_pages:
            page = total_pages
            rows, total = query_scan_results(
                symbol=symbol,
                mode=mode,
                scan_time_from=scan_time_from,
                scan_time_to=scan_time_to,
                page=page,
                per_page=per_page,
            )

        return render_template(
            "history.html",
            rows=rows,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            symbol=symbol or "",
            mode=mode or "",
            scan_time_from=scan_time_from or "",
            scan_time_to=scan_time_to or "",
            per_page_eff=per_page_eff,
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
