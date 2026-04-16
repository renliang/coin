import type { Signal } from "../api/client";
import { modeColor, modeName, price, scoreBg, scoreColor } from "../lib/format";

interface Props {
  signal: Signal;
  compact?: boolean;
}

export default function SignalCard({ signal, compact }: Props) {
  const { symbol, score, mode, entry_price, stop_loss_price, take_profit_price, signal_type } = signal;

  return (
    <div className="bg-[var(--color-card)] border border-slate-800 rounded-lg p-3 hover:border-slate-700 transition-colors">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm">{symbol}</span>
          <span className={`text-xs px-1.5 py-0.5 rounded ${modeColor(mode)}`}>
            {signal_type || modeName(mode)}
          </span>
        </div>
        <span
          className={`font-mono text-sm font-bold px-2 py-0.5 rounded border ${scoreBg(score)} ${scoreColor(score)}`}
        >
          {score.toFixed(2)}
        </span>
      </div>

      {!compact && (
        <div className="grid grid-cols-3 gap-2 text-xs">
          <div>
            <span className="text-slate-500">入场</span>
            <p className="font-mono text-slate-200">{price(entry_price)}</p>
          </div>
          <div>
            <span className="text-slate-500">止损</span>
            <p className="font-mono text-red-400">{price(stop_loss_price)}</p>
          </div>
          <div>
            <span className="text-slate-500">止盈</span>
            <p className="font-mono text-emerald-400">{price(take_profit_price)}</p>
          </div>
        </div>
      )}
    </div>
  );
}
