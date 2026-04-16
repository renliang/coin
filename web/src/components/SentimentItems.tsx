import type { SentimentItemData } from "../api/sentiment";
import { timeAgo } from "../lib/format";

const SOURCES = ["全部", "twitter", "telegram", "news", "onchain"] as const;

interface Props {
  items: SentimentItemData[];
  total: number;
  page: number;
  perPage: number;
  onPageChange: (page: number) => void;
  onSourceFilter: (source: string) => void;
  currentSource: string;
}

function sourceColor(source: string): string {
  const map: Record<string, string> = {
    twitter: "text-blue-400",
    telegram: "text-cyan-400",
    news: "text-amber-400",
    onchain: "text-emerald-400",
  };
  return map[source] ?? "text-slate-400";
}

export default function SentimentItems({
  items,
  total,
  page,
  perPage,
  onPageChange,
  onSourceFilter,
  currentSource,
}: Props) {
  const totalPages = Math.ceil(total / perPage);

  return (
    <div className="space-y-4">
      {/* Source filter buttons */}
      <div className="flex gap-2 flex-wrap">
        {SOURCES.map((s) => (
          <button
            key={s}
            onClick={() => onSourceFilter(s === "全部" ? "" : s)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              (s === "全部" && currentSource === "") || s === currentSource
                ? "bg-blue-500/20 text-blue-400"
                : "bg-slate-800/50 text-slate-400 hover:text-slate-200 hover:bg-slate-800"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Items list */}
      <div className="space-y-2 max-h-[500px] overflow-y-auto">
        {items.length === 0 ? (
          <p className="text-sm text-slate-600 py-8 text-center">暂无数据</p>
        ) : (
          items.map((item) => (
            <div
              key={item.id}
              className="bg-slate-800/30 border border-slate-800/50 rounded-lg p-3"
            >
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <span
                    className={`text-xs font-medium ${sourceColor(item.source)}`}
                  >
                    {item.source}
                  </span>
                  {item.symbol && (
                    <span className="text-xs text-slate-500">
                      {item.symbol}
                    </span>
                  )}
                </div>
                <span className="text-xs text-slate-600">
                  {timeAgo(item.timestamp)}
                </span>
              </div>
              <p className="text-sm text-slate-300 line-clamp-2">
                {item.raw_text}
              </p>
              <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-500">
                <span>
                  得分:{" "}
                  <span
                    className={`font-mono ${
                      item.score > 0
                        ? "text-emerald-400"
                        : item.score < 0
                          ? "text-red-400"
                          : "text-slate-400"
                    }`}
                  >
                    {item.score.toFixed(3)}
                  </span>
                </span>
                <span>置信度: {(item.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800/50 text-slate-400 hover:text-slate-200 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            上一页
          </button>
          <span className="text-xs text-slate-500">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800/50 text-slate-400 hover:text-slate-200 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  );
}
