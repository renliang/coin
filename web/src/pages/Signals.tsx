import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw, Search, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import type { Signal, PaginatedSignals } from "../api/client";
import { fetchSignals, triggerScan, fetchScanStatus } from "../api/client";
import {
  modeColor,
  modeName,
  price,
  scoreBg,
  scoreColor,
  pct,
} from "../lib/format";
import LoadingSpinner from "../components/LoadingSpinner";
import ScoreBreakdown from "../components/ScoreBreakdown";

const MODES = [
  { value: "", label: "全部模式" },
  { value: "accumulation", label: "蓄力" },
  { value: "divergence", label: "背离" },
  { value: "breakout", label: "突破" },
];

export default function Signals() {
  const [data, setData] = useState<PaginatedSignals | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // filters
  const [mode, setMode] = useState("");
  const [minScore, setMinScore] = useState("0.6");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);

  // scan state
  const [scanning, setScanning] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchSignals({
      mode: mode || undefined,
      min_score: minScore || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      page: String(page),
      per_page: "20",
    })
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [mode, minScore, dateFrom, dateTo, page]);

  useEffect(() => {
    load();
  }, [load]);

  // scan polling
  const startScan = () => {
    triggerScan()
      .then((res) => {
        if (res.started) {
          setScanning(true);
          pollRef.current = setInterval(async () => {
            const status = await fetchScanStatus();
            if (!status.running) {
              if (pollRef.current) clearInterval(pollRef.current);
              pollRef.current = null;
              setScanning(false);
              load();
            }
          }, 3000);
        }
      })
      .catch(() => {});
  };

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // expand detail
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">信号流</h2>
        <button
          onClick={startScan}
          disabled={scanning}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-500/15 text-blue-400 text-sm font-medium hover:bg-blue-500/25 transition-colors disabled:opacity-50"
        >
          {scanning ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <RefreshCw size={16} />
          )}
          {scanning ? "扫描中..." : "立即扫描"}
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={mode}
          onChange={(e) => { setMode(e.target.value); setPage(1); }}
          className="bg-[var(--color-card)] border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
        >
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </select>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">分数</span>
          <input
            type="range"
            min="0.5"
            max="1"
            step="0.05"
            value={minScore}
            onChange={(e) => { setMinScore(e.target.value); setPage(1); }}
            className="w-24 accent-blue-500"
          />
          <span className="text-xs font-mono text-slate-300 w-8">{Number(minScore).toFixed(2)}</span>
        </div>

        <input
          type="date"
          value={dateFrom}
          onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
          className="bg-[var(--color-card)] border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
          placeholder="开始日期"
        />
        <span className="text-slate-600">-</span>
        <input
          type="date"
          value={dateTo}
          onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
          className="bg-[var(--color-card)] border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
          placeholder="结束日期"
        />

        {(mode || dateFrom || dateTo || minScore !== "0.6") && (
          <button
            onClick={() => { setMode(""); setMinScore("0.6"); setDateFrom(""); setDateTo(""); setPage(1); }}
            className="text-xs text-slate-500 hover:text-slate-300"
          >
            重置筛选
          </button>
        )}
      </div>

      {/* Content */}
      {loading && !data ? (
        <LoadingSpinner />
      ) : error ? (
        <div className="text-center py-12 text-red-400">
          <p>{error}</p>
          <button onClick={load} className="mt-3 text-sm text-blue-400">重试</button>
        </div>
      ) : data && data.data.length === 0 ? (
        <div className="text-center py-16 text-slate-600">
          <Search size={40} className="mx-auto mb-3 opacity-50" />
          <p>无匹配信号</p>
        </div>
      ) : data ? (
        <>
          <p className="text-xs text-slate-500">
            共 {data.total} 条信号 · 第 {data.page}/{data.total_pages} 页
          </p>

          {/* Signal Cards Grid */}
          <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {data.data.map((s) => (
              <SignalDetailCard
                key={`${s.scan_time}-${s.symbol}-${s.mode}`}
                signal={s}
                expanded={expanded === `${s.scan_time}-${s.symbol}`}
                onToggle={() =>
                  setExpanded(
                    expanded === `${s.scan_time}-${s.symbol}`
                      ? null
                      : `${s.scan_time}-${s.symbol}`,
                  )
                }
              />
            ))}
          </div>

          {/* Pagination */}
          {data.total_pages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
                className="p-2 rounded-lg hover:bg-slate-800 disabled:opacity-30 transition-colors"
              >
                <ChevronLeft size={18} />
              </button>
              {Array.from({ length: Math.min(data.total_pages, 7) }, (_, i) => {
                const p = _pageNum(page, data.total_pages, i);
                return (
                  <button
                    key={p}
                    onClick={() => setPage(p)}
                    className={`w-8 h-8 rounded-lg text-sm transition-colors ${
                      p === page
                        ? "bg-blue-500/20 text-blue-400 font-medium"
                        : "hover:bg-slate-800 text-slate-400"
                    }`}
                  >
                    {p}
                  </button>
                );
              })}
              <button
                disabled={page >= data.total_pages}
                onClick={() => setPage(page + 1)}
                className="p-2 rounded-lg hover:bg-slate-800 disabled:opacity-30 transition-colors"
              >
                <ChevronRight size={18} />
              </button>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}

/** 页码计算 */
function _pageNum(current: number, total: number, index: number): number {
  const maxVisible = Math.min(total, 7);
  let start = Math.max(1, current - Math.floor(maxVisible / 2));
  if (start + maxVisible - 1 > total) start = total - maxVisible + 1;
  return start + index;
}

/** 可展开的信号卡片 */
function SignalDetailCard({
  signal,
  expanded,
  onToggle,
}: {
  signal: Signal;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { symbol, score, mode, entry_price, stop_loss_price, take_profit_price, signal_type, scan_time } = signal;
  const symbolSlug = symbol.replace("/", "-");

  return (
    <div
      className="bg-[var(--color-card)] border border-slate-800 rounded-xl hover:border-slate-700 transition-colors cursor-pointer"
      onClick={onToggle}
    >
      <div className="p-4">
        {/* Header row */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Link
              to={`/coin/${symbolSlug}`}
              onClick={(e) => e.stopPropagation()}
              className="font-semibold hover:text-blue-400 transition-colors"
            >
              {symbol}
            </Link>
            <span className={`text-xs px-1.5 py-0.5 rounded ${modeColor(mode)}`}>
              {signal_type || modeName(mode)}
            </span>
          </div>
          <span className={`font-mono text-sm font-bold px-2 py-0.5 rounded border ${scoreBg(score)} ${scoreColor(score)}`}>
            {score.toFixed(2)}
          </span>
        </div>

        {/* Price row */}
        <div className="grid grid-cols-3 gap-3 text-xs">
          <div>
            <span className="text-slate-500">入场</span>
            <p className="font-mono text-slate-200 mt-0.5">{price(entry_price)}</p>
          </div>
          <div>
            <span className="text-slate-500">止损</span>
            <p className="font-mono text-red-400 mt-0.5">{price(stop_loss_price)}</p>
          </div>
          <div>
            <span className="text-slate-500">止盈</span>
            <p className="font-mono text-emerald-400 mt-0.5">{price(take_profit_price)}</p>
          </div>
        </div>

        {/* Expanded detail */}
        {expanded && (
          <div className="mt-3 pt-3 border-t border-slate-800 space-y-3">
            <div className="grid grid-cols-2 gap-2 text-xs">
              {signal.drop_pct != null && (
                <div>
                  <span className="text-slate-500">跌幅</span>
                  <p className="font-mono text-slate-300">{pct(signal.drop_pct)}</p>
                </div>
              )}
              {signal.volume_ratio != null && (
                <div>
                  <span className="text-slate-500">缩量比</span>
                  <p className="font-mono text-slate-300">{signal.volume_ratio.toFixed(2)}</p>
                </div>
              )}
              {signal.window_days != null && signal.window_days > 0 && (
                <div>
                  <span className="text-slate-500">窗口</span>
                  <p className="font-mono text-slate-300">{signal.window_days} 天</p>
                </div>
              )}
              {signal.market_cap_m != null && signal.market_cap_m > 0 && (
                <div>
                  <span className="text-slate-500">市值</span>
                  <p className="font-mono text-slate-300">
                    ${signal.market_cap_m >= 1000
                      ? `${(signal.market_cap_m / 1000).toFixed(1)}B`
                      : `${signal.market_cap_m.toFixed(0)}M`}
                  </p>
                </div>
              )}
              {scan_time && (
                <div className="col-span-2">
                  <span className="text-slate-500">扫描时间</span>
                  <p className="font-mono text-slate-300">{scan_time}</p>
                </div>
              )}
            </div>
            {signal.score_breakdown && (
              <ScoreBreakdown breakdown={signal.score_breakdown} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
