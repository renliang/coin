import { useEffect, useState } from "react";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { PerformanceData } from "../api/client";
import { fetchPerformance } from "../api/client";
import { pct, pctSigned } from "../lib/format";
import LoadingSpinner from "../components/LoadingSpinner";

export default function Performance() {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchPerformance()
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingSpinner />;
  if (!data) return <p className="text-center py-16 text-slate-600">加载失败</p>;

  const { overall, by_mode, by_score, by_month, cumulative_pnl } = data;

  const modeData = Object.entries(by_mode).map(([mode, s]) => ({
    mode: MODE_LABELS[mode] ?? mode,
    win_rate: +(s.win_rate * 100).toFixed(1),
    total: s.total,
  }));

  const scoreData = Object.entries(by_score).map(([tier, s]) => ({
    tier,
    win_rate: +(s.win_rate * 100).toFixed(1),
    total: s.total,
  }));

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold">绩效分析</h2>

      {/* KPI Summary */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <MiniKpi label="总交易" value={String(overall.total)} />
        <MiniKpi label="胜率" value={pct(overall.win_rate)} color={overall.win_rate >= 0.6 ? "text-emerald-400" : "text-amber-400"} />
        <MiniKpi label="平均盈亏" value={pctSigned(overall.avg_pnl_pct)} color={overall.avg_pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"} />
        <MiniKpi label="盈亏比" value={overall.profit_factor.toFixed(2)} color={overall.profit_factor >= 1.5 ? "text-emerald-400" : "text-amber-400"} />
        <MiniKpi label="最大亏损" value={overall.max_loss !== 0 ? pctSigned(overall.max_loss) : "—"} color="text-red-400" />
      </div>

      {/* Cumulative P&L Curve */}
      {cumulative_pnl.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-slate-400 mb-3">累计收益曲线</h3>
          <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={cumulative_pnl}>
                <defs>
                  <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="date"
                  tick={{ fill: "#64748b", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: "#64748b", fontSize: 11 }}
                  tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                  axisLine={false}
                  tickLine={false}
                  width={45}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }}
                  formatter={(v: number) => [pctSigned(v), "累计盈亏"]}
                />
                <Area
                  type="monotone"
                  dataKey="cumulative_pnl"
                  stroke="#10b981"
                  fill="url(#pnlGrad)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Win Rate by Mode */}
        {modeData.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold text-slate-400 mb-3">按模式胜率</h3>
            <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={modeData} layout="vertical" barSize={20}>
                  <XAxis type="number" domain={[0, 100]} tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
                  <YAxis type="category" dataKey="mode" tick={{ fill: "#94a3b8", fontSize: 12 }} axisLine={false} tickLine={false} width={50} />
                  <Tooltip contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => [`${v}%`, "胜率"]} />
                  <Bar dataKey="win_rate" radius={[0, 6, 6, 0]}>
                    {modeData.map((_, i) => (
                      <Cell key={i} fill={MODE_COLORS[i] ?? "#64748b"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        )}

        {/* Win Rate by Score Tier */}
        {scoreData.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold text-slate-400 mb-3">按分数段胜率</h3>
            <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={scoreData} layout="vertical" barSize={20}>
                  <XAxis type="number" domain={[0, 100]} tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
                  <YAxis type="category" dataKey="tier" tick={{ fill: "#94a3b8", fontSize: 12 }} axisLine={false} tickLine={false} width={60} />
                  <Tooltip contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => [`${v}%`, "胜率"]} />
                  <Bar dataKey="win_rate" radius={[0, 6, 6, 0]} fill="#3b82f6" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        )}
      </div>

      {/* Monthly Stats Table */}
      {Object.keys(by_month).length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-slate-400 mb-3">月度统计</h3>
          <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-500 border-b border-slate-800">
                  <th className="text-left py-2.5 px-4 font-medium">月份</th>
                  <th className="text-right py-2.5 px-4 font-medium">交易数</th>
                  <th className="text-right py-2.5 px-4 font-medium">胜率</th>
                  <th className="text-right py-2.5 px-4 font-medium">平均盈亏</th>
                  <th className="text-right py-2.5 px-4 font-medium">盈亏比</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(by_month).map(([month, s]) => (
                  <tr key={month} className="border-b border-slate-800/50">
                    <td className="py-2.5 px-4 font-mono">{month}</td>
                    <td className="py-2.5 px-4 text-right font-mono">{s.total}</td>
                    <td className={`py-2.5 px-4 text-right font-mono ${s.win_rate >= 0.6 ? "text-emerald-400" : "text-amber-400"}`}>
                      {pct(s.win_rate)}
                    </td>
                    <td className={`py-2.5 px-4 text-right font-mono ${s.avg_pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {pctSigned(s.avg_pnl_pct)}
                    </td>
                    <td className="py-2.5 px-4 text-right font-mono">{s.profit_factor.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {overall.total === 0 && (
        <p className="text-center py-16 text-slate-600">暂无交易数据，绩效分析将在产生交易后可用</p>
      )}
    </div>
  );
}

function MiniKpi({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-[var(--color-card)] border border-slate-800 rounded-lg px-4 py-3">
      <p className="text-xs text-slate-500 mb-0.5">{label}</p>
      <p className={`text-lg font-bold font-mono ${color ?? "text-slate-100"}`}>{value}</p>
    </div>
  );
}

const MODE_LABELS: Record<string, string> = { accumulation: "蓄力", divergence: "背离", breakout: "突破" };
const MODE_COLORS = ["#3b82f6", "#8b5cf6", "#f97316"];
