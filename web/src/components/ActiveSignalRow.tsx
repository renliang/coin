import { Link } from "react-router-dom";
import type { ActiveSignal } from "../api/client";
import { price, pctSigned, modeColor, modeName } from "../lib/format";

interface Props {
  signal: ActiveSignal;
}

const STATE_LABELS: Record<string, { text: string; cls: string }> = {
  detected: { text: "已检测", cls: "text-slate-400 bg-slate-500/15" },
  entered: { text: "已入场", cls: "text-blue-400 bg-blue-500/15" },
  tp_hit: { text: "止盈", cls: "text-emerald-400 bg-emerald-500/15" },
  sl_hit: { text: "止损", cls: "text-red-400 bg-red-500/15" },
  expired: { text: "已过期", cls: "text-slate-500 bg-slate-600/15" },
};

export default function ActiveSignalRow({ signal }: Props) {
  const state = STATE_LABELS[signal.lifecycle_state] ?? { text: "未知", cls: "text-slate-400 bg-slate-500/15" };
  const symbolSlug = signal.symbol.replace("/", "-");
  const pnl = signal.unrealized_pnl_pct;
  const isApproaching = signal.approaching != null;

  // SL/TP progress bar
  const entry = signal.entry_price ?? signal.price;
  const sl = signal.stop_loss_price ?? 0;
  const tp = signal.take_profit_price ?? 0;
  const current = signal.current_price ?? entry;
  const totalRange = Math.abs(tp - sl);
  const progress = totalRange > 0 ? Math.min(1, Math.max(0, Math.abs(current - sl) / totalRange)) : 0.5;

  return (
    <div
      className={`bg-[var(--color-card)] border rounded-xl p-3 transition-colors ${
        isApproaching
          ? signal.approaching === "sl"
            ? "border-red-500/40"
            : "border-emerald-500/40"
          : "border-slate-800"
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Link
            to={`/coin/${symbolSlug}`}
            className="font-semibold text-sm hover:text-blue-400 transition-colors"
          >
            {signal.symbol}
          </Link>
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${modeColor(signal.mode)}`}>
            {signal.signal_type || modeName(signal.mode)}
          </span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${state.cls}`}>
            {state.text}
          </span>
        </div>
        {pnl != null && (
          <span
            className={`font-mono text-sm font-bold ${
              pnl >= 0 ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {pctSigned(pnl)}
          </span>
        )}
      </div>

      {/* Progress bar: SL --- current --- TP */}
      <div className="relative h-1.5 bg-slate-800 rounded-full overflow-hidden mb-2">
        <div
          className={`absolute h-full rounded-full ${
            signal.approaching === "sl"
              ? "bg-red-500"
              : signal.approaching === "tp"
                ? "bg-emerald-500"
                : "bg-blue-500"
          }`}
          style={{ width: `${progress * 100}%` }}
        />
      </div>

      <div className="flex justify-between text-[10px] text-slate-500 font-mono">
        <span>SL {price(sl)}</span>
        <span>
          {signal.current_price != null
            ? `${price(signal.current_price)}`
            : `${price(entry)}`}
        </span>
        <span>TP {price(tp)}</span>
      </div>
    </div>
  );
}
