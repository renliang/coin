import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { Radio, Briefcase, TrendingUp, Target, AlertTriangle } from "lucide-react";
import type { DashboardData, ActiveSignal } from "../api/client";
import { fetchDashboard, fetchActiveSignals, fetchSignalTrend } from "../api/client";
import KpiCard from "../components/KpiCard";
import SignalCard from "../components/SignalCard";
import PositionRow from "../components/PositionRow";
import ActiveSignalRow from "../components/ActiveSignalRow";
import MarketTemperature from "../components/MarketTemperature";
import LoadingSpinner from "../components/LoadingSpinner";
import { pct, pctSigned } from "../lib/format";

interface TrendItem {
  day: string;
  mode: string;
  cnt: number;
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeSignals, setActiveSignals] = useState<ActiveSignal[]>([]);
  const [signalTrend, setSignalTrend] = useState<TrendItem[]>([]);

  const load = () => {
    fetchDashboard()
      .then(setData)
      .catch((e: Error) => setError(e.message));
    fetchActiveSignals()
      .then((r) => setActiveSignals(r.data))
      .catch(() => {});
    fetchSignalTrend(7)
      .then((r) => setSignalTrend(r.data))
      .catch(() => {});
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  if (error) {
    return (
      <div className="text-center py-20 text-red-400">
        <p className="text-lg mb-2">加载失败</p>
        <p className="text-sm text-slate-500">{error}</p>
        <button
          onClick={load}
          className="mt-4 px-4 py-2 rounded-lg bg-blue-500/15 text-blue-400 text-sm hover:bg-blue-500/25 transition-colors"
        >
          重试
        </button>
      </div>
    );
  }

  if (!data) return <LoadingSpinner />;

  const { kpi, top_signals, positions, hit_rate_7d, signal_counts, is_today, last_scan_time } = data;

  // urgent: approaching SL/TP
  const urgentSignals = activeSignals.filter((s) => s.approaching != null);

  return (
    <div className="space-y-6">
      {/* Header + Market Temperature */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-xl font-bold">仪表盘</h2>
        <div className="flex items-center gap-4">
          <MarketTemperature trend={signalTrend} />
          <div className="text-xs text-slate-500">
            {!is_today && last_scan_time && (
              <span className="text-amber-400">
                最近: {last_scan_time.slice(0, 16)}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Fallback notice */}
      {!is_today && last_scan_time && (
        <div className="bg-amber-500/10 border border-amber-500/20 text-amber-300 text-sm rounded-lg px-4 py-2.5">
          今日尚未扫描，以下为最近一次扫描结果（{last_scan_time.slice(0, 16)}）
        </div>
      )}

      {/* ═══ SECTION 1: URGENT ═══ */}
      {(urgentSignals.length > 0 || positions.length > 0) && (
        <section className="space-y-3">
          <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
            <AlertTriangle size={12} />
            需要关注
          </h3>

          {/* Approaching SL/TP alerts */}
          {urgentSignals.length > 0 && (
            <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-2">
              {urgentSignals.map((s) => (
                <ActiveSignalRow key={s.id} signal={s} />
              ))}
            </div>
          )}

          {/* Active Positions */}
          {positions.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs text-slate-500">
                活跃持仓 ({positions.length})
              </p>
              {positions.map((p) => (
                <PositionRow key={p.id} position={p} />
              ))}
            </div>
          )}
        </section>
      )}

      {/* ═══ SECTION 2: TODAY ═══ */}
      <section className="space-y-4">
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider">
          {is_today ? "今日概况" : "最近概况"}
        </h3>

        {/* KPI Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <KpiCard
            title={is_today ? "今日信号" : "最近信号"}
            value={String(kpi.today_signals)}
            icon={<Radio size={18} />}
            sub={`蓄力 ${signal_counts.accumulation} / 背离 ${signal_counts.divergence} / 突破 ${signal_counts.breakout}`}
          />
          <KpiCard
            title="活跃持仓"
            value={String(kpi.active_positions)}
            icon={<Briefcase size={18} />}
          />
          <KpiCard
            title="今日盈亏"
            value={kpi.today_pnl_count > 0 ? pctSigned(kpi.today_pnl_pct) : "—"}
            sub={kpi.today_pnl_count > 0 ? `${kpi.today_pnl_count} 笔交易` : "今日无平仓"}
            icon={<TrendingUp size={18} />}
            trend={kpi.today_pnl_pct > 0 ? "up" : kpi.today_pnl_pct < 0 ? "down" : "neutral"}
          />
          <KpiCard
            title="累计胜率"
            value={kpi.total_trades > 0 ? pct(kpi.win_rate) : "—"}
            sub={kpi.total_trades > 0 ? `${kpi.total_trades} 笔交易` : "暂无数据"}
            icon={<Target size={18} />}
          />
        </div>

        {/* Top 5 Signals + Active Signal Tracking */}
        <div className="grid lg:grid-cols-2 gap-6">
          <div>
            <h4 className="text-sm font-semibold text-slate-400 mb-3">
              高分信号 TOP 5
            </h4>
            {top_signals.length === 0 ? (
              <p className="text-sm text-slate-600 py-8 text-center">暂无信号</p>
            ) : (
              <div className="space-y-2">
                {top_signals.map((s) => (
                  <SignalCard key={s.symbol + s.mode} signal={s} />
                ))}
              </div>
            )}
          </div>

          <div>
            <h4 className="text-sm font-semibold text-slate-400 mb-3">
              信号追踪 ({activeSignals.length})
            </h4>
            {activeSignals.length === 0 ? (
              <p className="text-sm text-slate-600 py-8 text-center">暂无活跃信号</p>
            ) : (
              <div className="space-y-2 max-h-[400px] overflow-y-auto">
                {activeSignals.slice(0, 10).map((s) => (
                  <ActiveSignalRow key={s.id} signal={s} />
                ))}
                {activeSignals.length > 10 && (
                  <p className="text-xs text-slate-500 text-center py-1">
                    +{activeSignals.length - 10} 更多
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ═══ SECTION 3: TRENDS ═══ */}
      <section className="space-y-4">
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider">
          趋势分析
        </h3>

        <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
          <p className="text-sm font-semibold text-slate-400 mb-3">
            近 7 日交易统计
          </p>
          {hit_rate_7d.every((d) => d.total === 0) ? (
            <p className="text-sm text-slate-600 py-8 text-center">近 7 天无交易数据</p>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={hit_rate_7d} barSize={24}>
                <XAxis
                  dataKey="date"
                  tickFormatter={(d: string) => d.slice(5)}
                  tick={{ fill: "#64748b", fontSize: 12 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: "#64748b", fontSize: 12 }}
                  axisLine={false}
                  tickLine={false}
                  width={30}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#1e293b",
                    border: "1px solid #334155",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                  labelStyle={{ color: "#94a3b8" }}
                  formatter={(value: number, name: string) => {
                    if (name === "wins") return [value, "盈利"];
                    return [value, "总计"];
                  }}
                />
                <Bar dataKey="total" radius={[4, 4, 0, 0]}>
                  {hit_rate_7d.map((entry, i) => (
                    <Cell
                      key={i}
                      fill={entry.wins > 0 ? "#10b98140" : "#33415540"}
                    />
                  ))}
                </Bar>
                <Bar dataKey="wins" radius={[4, 4, 0, 0]}>
                  {hit_rate_7d.map((_, i) => (
                    <Cell key={i} fill="#10b981" />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>
    </div>
  );
}
