import { Shield, ShieldAlert } from "lucide-react";
import type { RiskEvent } from "../api/portfolio";

interface Props {
  portfolioHalted: boolean;
  drawdownPct: number;
  haltedStrategies: string[];
  riskEvents: RiskEvent[];
}

function levelBadge(level: string) {
  const styles: Record<string, string> = {
    portfolio: "bg-red-500/15 text-red-400",
    strategy: "bg-amber-500/15 text-amber-400",
    position: "bg-blue-500/15 text-blue-400",
  };
  return styles[level] ?? "bg-slate-500/15 text-slate-400";
}

export default function RiskStatus({
  portfolioHalted,
  drawdownPct,
  haltedStrategies,
  riskEvents,
}: Props) {
  return (
    <div className="space-y-4">
      {/* Status header */}
      <div className="flex items-center gap-3">
        {portfolioHalted ? (
          <ShieldAlert size={24} className="text-red-400" />
        ) : (
          <Shield size={24} className="text-emerald-400" />
        )}
        <div>
          <p className="text-sm font-semibold">
            {portfolioHalted ? (
              <span className="text-red-400">已暂停交易</span>
            ) : (
              <span className="text-emerald-400">正常运行</span>
            )}
          </p>
          <p className="text-xs text-slate-500">
            回撤: {(drawdownPct * 100).toFixed(2)}%
          </p>
        </div>
      </div>

      {/* Halted strategies */}
      {haltedStrategies.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 mb-1.5">暂停策略</p>
          <div className="flex flex-wrap gap-1.5">
            {haltedStrategies.map((s) => (
              <span
                key={s}
                className="px-2 py-0.5 rounded text-xs bg-red-500/15 text-red-400"
              >
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Risk events */}
      {riskEvents.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 mb-1.5">风控事件</p>
          <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
            {riskEvents.map((e) => (
              <div
                key={e.id}
                className="flex items-start gap-2 py-1.5 border-b border-slate-800/50 last:border-0"
              >
                <span
                  className={`inline-block px-1.5 py-0.5 rounded text-xs shrink-0 mt-0.5 ${levelBadge(e.level)}`}
                >
                  {e.level}
                </span>
                <div className="min-w-0">
                  <p className="text-xs text-slate-300 truncate">
                    {e.event_type}: {e.details}
                  </p>
                  <p className="text-xs text-slate-600">
                    {e.strategy_id} &middot; {e.created_at.slice(0, 16)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
