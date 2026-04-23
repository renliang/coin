"""CLI 子命令入口 — 用 argparse subparsers 组织所有命令。"""

import argparse
import sys

from dataclasses import replace


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="coin",
        description="Coin Quant — 币种形态筛选与量化交易工具",
    )
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    sub = parser.add_subparsers(dest="command")

    # ── scan ──────────────────────────────────────────────
    p_scan = sub.add_parser("scan", help="扫描信号（蓄力/背离/突破/趋势）")
    p_scan.add_argument(
        "--mode", "-m",
        choices=["accumulation", "divergence", "breakout", "smc", "trend"],
        default="divergence",
        help="扫描模式 (默认: divergence)",
    )
    p_scan.add_argument("--top", type=int, help="输出前 N 个结果")
    p_scan.add_argument("--symbols", nargs="+", help="直接指定交易对")
    p_scan.add_argument("--no-confirm", action="store_true", help="关闭多指标共振过滤")

    # ── backtest ──────────────────────────────────────────
    p_bt = sub.add_parser("backtest", help="回测验证形态有效性")
    p_bt.add_argument("--days", type=int, default=180, help="历史 K 线天数 (默认 180)")
    p_bt.add_argument("--symbols", nargs="+", help="直接指定交易对")
    p_bt.add_argument("--verify-signal", action="store_true", help="对比 signal 门槛下收益")
    p_bt.add_argument("--sensitivity", action="store_true", help="输出参数敏感性表")

    # ── track ─────────────────────────────────────────────
    sub.add_parser("track", help="查看所有跟踪中的币种")

    # ── history ────────────────────────────────────────────
    p_hist = sub.add_parser("history", help="查看某币种历史记录")
    p_hist.add_argument("symbol", help="交易对，如 ZIL/USDT")

    # ── serve ─────────────────────────────────────────────
    sub.add_parser("serve", help="常驻模式：定时扫描 + 自动下单 + 订单监控")

    # ── stats ─────────────────────────────────────────────
    p_stats = sub.add_parser("stats", help="信号成功率统计")
    p_stats.add_argument("--json-only", action="store_true", help="仅导出 JSON")

    # ── optimize ──────────────────────────────────────────
    p_opt = sub.add_parser("optimize", help="参数优化与模型管理")
    p_opt.add_argument(
        "action",
        nargs="?",
        default="run",
        choices=["run", "report"],
        help="run=运行优化, report=查看当前参数 (默认: run)",
    )
    p_opt.add_argument("--days", type=int, default=180, help="回测历史天数")
    p_opt.add_argument("--symbols", nargs="+", help="直接指定交易对")

    # ── retrain ───────────────────────────────────────────
    sub.add_parser("retrain", help="收集反馈 + 重训练 ML 模型")

    # ── sentiment ─────────────────────────────────────────
    p_sent = sub.add_parser("sentiment", help="舆情采集与情绪信号")
    p_sent.add_argument(
        "action",
        nargs="?",
        default="scan",
        choices=["scan", "status"],
        help="scan=采集舆情, status=查看最新信号 (默认: scan)",
    )
    p_sent.add_argument("--symbols", nargs="+", help="直接指定交易对")

    # ── portfolio ─────────────────────────────────────────
    p_port = sub.add_parser("portfolio", help="组合权重管理")
    p_port.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=["status", "rebalance", "report"],
        help="status=查看权重, rebalance=再平衡, report=生成报告 (默认: status)",
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # ── 延迟导入，只在实际运行时加载 ──
    from main import (
        load_config,
        run,
        run_divergence,
        run_breakout,
        run_smc,
        run_trend,
        run_backtest_cli,
        run_serve,
        run_stats,
        run_optimize_cli,
        run_retrain_cli,
        run_optimize_report_cli,
        run_sentiment_scan,
        run_sentiment_status,
        run_portfolio_status,
        run_portfolio_rebalance,
        run_portfolio_report,
        show_tracking,
        show_history,
        execute_trading_pipeline,
    )

    config, signal_config, trading_config, schedule_config, sentiment_config, portfolio_config = load_config(args.config)

    if args.command == "scan":
        if args.no_confirm:
            signal_config = replace(signal_config, confirmation=False)
        if args.mode == "smc":
            run_smc(config, signal_config, top_n=args.top, symbols_override=args.symbols)
        elif args.mode == "breakout":
            run_breakout(config, signal_config, top_n=args.top, symbols_override=args.symbols)
        elif args.mode == "divergence":
            # CLI 手动扫描只刷数据，不自动下单。下单由 serve 模式的每日 cron 统一负责。
            run_divergence(config, signal_config, top_n=args.top, symbols_override=args.symbols)
        elif args.mode == "trend":
            run_trend(config, top_n=args.top, symbols_override=args.symbols)
        else:
            run(config, signal_config, top_n=args.top, symbols_override=args.symbols)

    elif args.command == "backtest":
        run_backtest_cli(
            config, signal_config,
            days=args.days,
            symbols_override=args.symbols,
            verify_signal=args.verify_signal,
            run_sensitivity=args.sensitivity,
        )

    elif args.command == "track":
        show_tracking()

    elif args.command == "history":
        show_history(args.symbol)

    elif args.command == "serve":
        run_serve(config, signal_config, trading_config, schedule_config,
                  sentiment_config=sentiment_config, portfolio_config=portfolio_config)

    elif args.command == "stats":
        run_stats(json_only=args.json_only)

    elif args.command == "optimize":
        if args.action == "report":
            run_optimize_report_cli()
        else:
            run_optimize_cli(config, signal_config, days=args.days, symbols_override=args.symbols)

    elif args.command == "retrain":
        run_retrain_cli()

    elif args.command == "sentiment":
        if args.action == "status":
            run_sentiment_status()
        else:
            run_sentiment_scan(sentiment_config, symbols_override=args.symbols)

    elif args.command == "portfolio":
        if args.action == "rebalance":
            run_portfolio_rebalance(portfolio_config)
        elif args.action == "report":
            run_portfolio_report(portfolio_config)
        else:
            run_portfolio_status(portfolio_config)
