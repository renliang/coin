import type { ReactNode } from "react";

interface Props {
  title: string;
  value: string;
  sub?: string;
  icon: ReactNode;
  trend?: "up" | "down" | "neutral";
}

export default function KpiCard({ title, value, sub, icon, trend }: Props) {
  const trendColor =
    trend === "up"
      ? "text-emerald-400"
      : trend === "down"
        ? "text-red-400"
        : "text-slate-500";

  return (
    <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4 flex items-start gap-3">
      <div className="p-2.5 rounded-lg bg-slate-800/60 text-slate-400 shrink-0">
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-xs text-slate-500 mb-1">{title}</p>
        <p className="text-xl font-bold font-mono tracking-tight">{value}</p>
        {sub && <p className={`text-xs mt-0.5 ${trendColor}`}>{sub}</p>}
      </div>
    </div>
  );
}
