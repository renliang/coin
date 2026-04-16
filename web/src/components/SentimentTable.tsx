import type { SentimentSignalData } from "../api/sentiment";
import { timeAgo } from "../lib/format";

interface Props {
  signals: SentimentSignalData[];
}

function scoreColor(score: number): string {
  if (score > 0.1) return "text-emerald-400";
  if (score < -0.1) return "text-red-400";
  return "text-slate-400";
}

function directionLabel(dir: string): string {
  const map: Record<string, string> = {
    bullish: "看涨",
    bearish: "看跌",
    neutral: "中性",
  };
  return map[dir] ?? dir;
}

export default function SentimentTable({ signals }: Props) {
  if (signals.length === 0) {
    return (
      <p className="text-sm text-slate-600 py-8 text-center">暂无数据</p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-slate-500 text-xs border-b border-slate-800">
            <th className="text-left py-2 px-3 font-medium">币种</th>
            <th className="text-right py-2 px-3 font-medium">得分</th>
            <th className="text-center py-2 px-3 font-medium">方向</th>
            <th className="text-right py-2 px-3 font-medium">置信度</th>
            <th className="text-right py-2 px-3 font-medium">更新</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s) => (
            <tr
              key={s.symbol}
              className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors"
            >
              <td className="py-2.5 px-3 font-medium">{s.symbol}</td>
              <td
                className={`py-2.5 px-3 text-right font-mono ${scoreColor(s.score)}`}
              >
                {s.score.toFixed(3)}
              </td>
              <td className="py-2.5 px-3 text-center">
                <span
                  className={`inline-block px-2 py-0.5 rounded text-xs ${
                    s.direction === "bullish"
                      ? "bg-emerald-500/15 text-emerald-400"
                      : s.direction === "bearish"
                        ? "bg-red-500/15 text-red-400"
                        : "bg-slate-500/15 text-slate-400"
                  }`}
                >
                  {directionLabel(s.direction)}
                </span>
              </td>
              <td className="py-2.5 px-3 text-right font-mono text-slate-400">
                {(s.confidence * 100).toFixed(0)}%
              </td>
              <td className="py-2.5 px-3 text-right text-slate-500">
                {timeAgo(s.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
