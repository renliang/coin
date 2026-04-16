import type { ScoreBreakdownData } from "../api/client";

const BAR_COLORS = [
  "bg-blue-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-purple-500",
];

interface Props {
  breakdown: ScoreBreakdownData;
}

export default function ScoreBreakdown({ breakdown }: Props) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-500 font-medium">
        评分分解 <span className="text-slate-400">({breakdown.total.toFixed(2)})</span>
      </p>
      {breakdown.components.map((c, i) => {
        const weighted = c.score * c.weight;
        return (
          <div key={c.name} className="flex items-center gap-2 text-xs">
            <span className="text-slate-400 w-16 shrink-0">{c.name}</span>
            <div className="flex-1 h-4 bg-slate-800 rounded-full overflow-hidden relative">
              <div
                className={`h-full rounded-full ${BAR_COLORS[i % BAR_COLORS.length]} opacity-80`}
                style={{ width: `${Math.min(c.score * 100, 100)}%` }}
              />
            </div>
            <span className="font-mono text-slate-300 w-10 text-right">
              {c.score.toFixed(2)}
            </span>
            <span className="font-mono text-slate-500 w-8 text-right text-[10px]">
              x{c.weight}
            </span>
            <span className="font-mono text-slate-200 w-10 text-right">
              {weighted.toFixed(3)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
