import type { Position } from "../api/client";
import { modeName, price as fmtPrice, pctSigned } from "../lib/format";

interface Props {
  position: Position;
}

export default function PositionRow({ position }: Props) {
  const { symbol, side, entry_price, leverage, score, opened_at, mode, pnl_pct } = position;
  const isLong = side === "long" || side === "buy";
  const sideLabel = isLong ? "多" : "空";
  const sideColor = isLong ? "text-emerald-400 bg-emerald-500/15" : "text-red-400 bg-red-500/15";

  // 持仓天数
  const days = Math.floor((Date.now() - new Date(opened_at).getTime()) / 86400000);

  return (
    <div className="flex items-center gap-3 bg-[var(--color-card)] border border-slate-800 rounded-lg px-4 py-3">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="font-semibold text-sm">{symbol}</span>
          <span className={`text-xs px-1.5 py-0.5 rounded ${sideColor}`}>
            {sideLabel} {leverage}x
          </span>
          {mode && (
            <span className="text-xs text-slate-500">{modeName(mode)}</span>
          )}
        </div>
        <div className="text-xs text-slate-500">
          入场 <span className="font-mono text-slate-300">{fmtPrice(entry_price)}</span>
          <span className="mx-2">|</span>
          分数 <span className="font-mono text-slate-300">{score.toFixed(2)}</span>
          <span className="mx-2">|</span>
          {days}天
        </div>
      </div>
      {pnl_pct != null && (
        <span
          className={`font-mono text-sm font-bold ${pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}
        >
          {pctSigned(pnl_pct)}
        </span>
      )}
    </div>
  );
}
