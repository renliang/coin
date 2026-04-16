import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { fetchCoinDetail, fetchKlines } from "../api/client";
import type { Signal, Position, KlineBar } from "../api/client";
import {
  modeColor,
  modeName,
  price as fmtPrice,
  pctSigned,
  scoreColor,
} from "../lib/format";
import LoadingSpinner from "../components/LoadingSpinner";
import CandlestickChart from "../components/CandlestickChart";
import ScoreBreakdown from "../components/ScoreBreakdown";

export default function CoinDetail() {
  const { symbol: symbolSlug } = useParams<{ symbol: string }>();
  const symbol = (symbolSlug ?? "").replace("-", "/").toUpperCase();

  const [scans, setScans] = useState<Signal[]>([]);
  const [trades, setTrades] = useState<Position[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [klines, setKlines] = useState<KlineBar[]>([]);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    fetchCoinDetail(symbol)
      .then((d) => {
        setScans(d.scans);
        setTrades(d.trades);
        setTotal(d.total_scans);
      })
      .finally(() => setLoading(false));
    fetchKlines(symbol, 60)
      .then((d) => setKlines(d.data))
      .catch(() => {});
  }, [symbol]);

  if (loading) return <LoadingSpinner />;

  const winCount = trades.filter((t) => (t.pnl_pct ?? 0) > 0).length;
  const winRate = trades.length > 0 ? ((winCount / trades.length) * 100).toFixed(0) : "—";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link to="/signals" className="p-2 rounded-lg hover:bg-slate-800 transition-colors">
          <ArrowLeft size={18} />
        </Link>
        <div>
          <h2 className="text-xl font-bold">{symbol}</h2>
          <p className="text-xs text-slate-500">
            共 {total} 次扫描 · {trades.length} 笔交易 · 胜率 {winRate}%
          </p>
        </div>
      </div>

      {/* K-line Chart + Latest Score Breakdown */}
      <div className="grid md:grid-cols-3 gap-4">
        {klines.length > 0 && (
          <div className="md:col-span-2 bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
            <h3 className="text-sm font-semibold text-slate-400 mb-3">K 线图 (60d)</h3>
            <CandlestickChart data={klines} height={280} />
          </div>
        )}
        {scans[0]?.score_breakdown != null && (
          <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
            <h3 className="text-sm font-semibold text-slate-400 mb-3">最新评分分解</h3>
            <ScoreBreakdown breakdown={scans[0].score_breakdown} />
          </div>
        )}
      </div>

      {/* Scan History */}
      <section>
        <h3 className="text-sm font-semibold text-slate-400 mb-3">扫描记录</h3>
        {scans.length === 0 ? (
          <p className="text-sm text-slate-600 py-6 text-center">无扫描记录</p>
        ) : (
          <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 border-b border-slate-800">
                    <th className="text-left py-2.5 px-4 font-medium">时间</th>
                    <th className="text-left py-2.5 px-4 font-medium">模式</th>
                    <th className="text-right py-2.5 px-4 font-medium">分数</th>
                    <th className="text-right py-2.5 px-4 font-medium">价格</th>
                    <th className="text-right py-2.5 px-4 font-medium">跌幅</th>
                    <th className="text-right py-2.5 px-4 font-medium">缩量比</th>
                    <th className="text-right py-2.5 px-4 font-medium">窗口</th>
                    <th className="text-right py-2.5 px-4 font-medium">入场</th>
                    <th className="text-right py-2.5 px-4 font-medium">止损</th>
                    <th className="text-right py-2.5 px-4 font-medium">止盈</th>
                  </tr>
                </thead>
                <tbody>
                  {scans.map((s, i) => (
                    <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                      <td className="py-2 px-4 text-xs font-mono text-slate-400">{(s.scan_time ?? "").slice(0, 16)}</td>
                      <td className="py-2 px-4">
                        <span className={`text-xs px-1.5 py-0.5 rounded ${modeColor(s.mode)}`}>
                          {s.signal_type || modeName(s.mode)}
                        </span>
                      </td>
                      <td className="py-2 px-4 text-right">
                        <span className={`font-mono text-xs font-semibold ${scoreColor(s.score)}`}>
                          {s.score.toFixed(2)}
                        </span>
                      </td>
                      <td className="py-2 px-4 text-right font-mono text-slate-300">{fmtPrice(s.price)}</td>
                      <td className="py-2 px-4 text-right font-mono text-slate-400">
                        {s.drop_pct != null ? `${(s.drop_pct * 100).toFixed(1)}%` : "—"}
                      </td>
                      <td className="py-2 px-4 text-right font-mono text-slate-400">
                        {s.volume_ratio != null ? s.volume_ratio.toFixed(2) : "—"}
                      </td>
                      <td className="py-2 px-4 text-right font-mono text-slate-400">
                        {s.window_days && s.window_days > 0 ? `${s.window_days}d` : "—"}
                      </td>
                      <td className="py-2 px-4 text-right font-mono text-slate-200">{fmtPrice(s.entry_price)}</td>
                      <td className="py-2 px-4 text-right font-mono text-red-400">{fmtPrice(s.stop_loss_price)}</td>
                      <td className="py-2 px-4 text-right font-mono text-emerald-400">{fmtPrice(s.take_profit_price)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {/* Trade History */}
      <section>
        <h3 className="text-sm font-semibold text-slate-400 mb-3">交易记录</h3>
        {trades.length === 0 ? (
          <p className="text-sm text-slate-600 py-6 text-center">无交易记录</p>
        ) : (
          <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 border-b border-slate-800">
                    <th className="text-left py-2.5 px-4 font-medium">开仓</th>
                    <th className="text-left py-2.5 px-4 font-medium">平仓</th>
                    <th className="text-left py-2.5 px-4 font-medium">方向</th>
                    <th className="text-right py-2.5 px-4 font-medium">入场</th>
                    <th className="text-right py-2.5 px-4 font-medium">出场</th>
                    <th className="text-right py-2.5 px-4 font-medium">盈亏</th>
                    <th className="text-left py-2.5 px-4 font-medium">原因</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t) => {
                    const pnl = t.pnl_pct ?? 0;
                    return (
                      <tr key={t.id} className="border-b border-slate-800/50">
                        <td className="py-2 px-4 text-xs font-mono text-slate-400">{t.opened_at.slice(0, 16)}</td>
                        <td className="py-2 px-4 text-xs font-mono text-slate-400">{(t.closed_at ?? "").slice(0, 16)}</td>
                        <td className="py-2 px-4">
                          <span className={t.side === "buy" ? "text-emerald-400" : "text-red-400"}>
                            {t.side === "buy" ? "多" : "空"} {t.leverage}x
                          </span>
                        </td>
                        <td className="py-2 px-4 text-right font-mono">{fmtPrice(t.entry_price)}</td>
                        <td className="py-2 px-4 text-right font-mono">{fmtPrice(t.exit_price)}</td>
                        <td className={`py-2 px-4 text-right font-mono font-semibold ${pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                          {pctSigned(pnl)}
                        </td>
                        <td className="py-2 px-4 text-xs text-slate-400">{t.exit_reason ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
