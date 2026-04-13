import os

from flask import Flask, redirect, render_template, request, url_for

from scanner.tracker import get_closed_trades_by_symbol, get_tracked_symbols, query_scan_results


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    @app.route("/")
    def index():
        symbols = get_tracked_symbols()
        return render_template("index.html", symbols=symbols)

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
