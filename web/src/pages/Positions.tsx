import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { Position } from "../api/client";
import { fetchPositions, fetchClosedPositions } from "../api/client";
import { modeName, price as fmtPrice, pctSigned } from "../lib/format";
import LoadingSpinner from "../components/LoadingSpinner";

type Tab = "active" | "closed";

export default function Positions() {
  const [tab, setTab] = useState<Tab>("active");
  const [active, setActive] = useState<Position[]>([]);
  const [closed, setClosed] = useState<Position[]>([]);
  const [closedTotal, setClosedTotal] = useState(0);
  const [closedPages, setClosedPages] = useState(1);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    if (tab === "active") {
      fetchPositions()
        .then((r) => setActive(r.data))
        .finally(() => setLoading(false));
    } else {
      fetchClosedPositions(String(page), "15")
        .then((r) => {
          setClosed(r.data);
          setClosedTotal(r.total);
          setClosedPages(r.total_pages);
        })
        .finally(() => setLoading(false));
    }
  }, [tab, page]);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">持仓管理</h2>
        <div className="flex gap-1 bg-slate-800/50 rounded-lg p-0.5">
          {(["active", "closed"] as const).map((t) => (
            <button
              key={t}
              onClick={() => { setTab(t); setPage(1); }}
              className={`px-4 py-1.5 rounded-md text-sm transition-colors ${
                tab === t
                  ? "bg-[var(--color-card)] text-white shadow"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {t === "active" ? "活跃持仓" : "已平仓"}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <LoadingSpinner />
      ) : tab === "active" ? (
        <ActivePositions positions={active} />
      ) : (
        <ClosedPositions
          trades={closed}
          total={closedTotal}
          page={page}
          totalPages={closedPages}
          onPage={setPage}
        />
      )}
    </div>
  );
}

function ActivePositions({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return <p className="text-center py-16 text-slate-600">暂无活跃持仓</p>;
  }

  return (
    <div className="space-y-3">
      {positions.map((p) => (
        <ActiveCard key={p.id} position={p} />
      ))}
    </div>
  );
}

function ActiveCard({ position }: { position: Position }) {
  const { symbol, side, entry_price, leverage, score, opened_at, mode } = position;
  const sideLabel = side === "buy" ? "多" : "空";
  const sideColor = side === "buy" ? "text-emerald-400 bg-emerald-500/15" : "text-red-400 bg-red-500/15";
  const days = Math.floor((Date.now() - new Date(opened_at).getTime()) / 86400000);
  const symbolSlug = symbol.replace("/", "-");

  return (
    <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Link to={`/coin/${symbolSlug}`} className="font-semibold hover:text-blue-400 transition-colors">
            {symbol}
          </Link>
          <span className={`text-xs px-1.5 py-0.5 rounded ${sideColor}`}>
            {sideLabel} {leverage}x
          </span>
          {mode && <span className="text-xs text-slate-500">{modeName(mode)}</span>}
        </div>
        <span className="text-xs text-slate-500">{days}天</span>
      </div>

      <div className="grid grid-cols-3 gap-3 text-xs">
        <div>
          <span className="text-slate-500">入场</span>
          <p className="font-mono text-slate-200">{fmtPrice(entry_price)}</p>
        </div>
        <div>
          <span className="text-slate-500">分数</span>
          <p className="font-mono text-slate-200">{score.toFixed(2)}</p>
        </div>
        <div>
          <span className="text-slate-500">开仓时间</span>
          <p className="font-mono text-slate-300">{opened_at.slice(0, 16)}</p>
        </div>
      </div>
    </div>
  );
}

function ClosedPositions({
  trades,
  total,
  page,
  totalPages,
  onPage,
}: {
  trades: Position[];
  total: number;
  page: number;
  totalPages: number;
  onPage: (p: number) => void;
}) {
  if (total === 0) {
    return <p className="text-center py-16 text-slate-600">暂无已平仓交易</p>;
  }

  const wins = trades.filter((t) => (t.pnl_pct ?? 0) > 0).length;

  return (
    <>
      <p className="text-xs text-slate-500">
        共 {total} 笔 · 本页胜率 {trades.length > 0 ? ((wins / trades.length) * 100).toFixed(0) : 0}%
      </p>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-800">
              <th className="text-left py-2 px-3 font-medium">币种</th>
              <th className="text-left py-2 px-3 font-medium">方向</th>
              <th className="text-right py-2 px-3 font-medium">杠杆</th>
              <th className="text-right py-2 px-3 font-medium">入场</th>
              <th className="text-right py-2 px-3 font-medium">出场</th>
              <th className="text-right py-2 px-3 font-medium">盈亏</th>
              <th className="text-left py-2 px-3 font-medium">原因</th>
              <th className="text-left py-2 px-3 font-medium">模式</th>
              <th className="text-left py-2 px-3 font-medium">平仓时间</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => {
              const pnl = t.pnl_pct ?? 0;
              const isWin = pnl > 0;
              const symbolSlug = t.symbol.replace("/", "-");
              return (
                <tr key={t.id} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                  <td className="py-2.5 px-3">
                    <Link to={`/coin/${symbolSlug}`} className="hover:text-blue-400 transition-colors">
                      {t.symbol}
                    </Link>
                  </td>
                  <td className="py-2.5 px-3">
                    <span className={t.side === "buy" ? "text-emerald-400" : "text-red-400"}>
                      {t.side === "buy" ? "多" : "空"}
                    </span>
                  </td>
                  <td className="py-2.5 px-3 text-right font-mono">{t.leverage}x</td>
                  <td className="py-2.5 px-3 text-right font-mono">{fmtPrice(t.entry_price)}</td>
                  <td className="py-2.5 px-3 text-right font-mono">{fmtPrice(t.exit_price)}</td>
                  <td className={`py-2.5 px-3 text-right font-mono font-semibold ${isWin ? "text-emerald-400" : "text-red-400"}`}>
                    {pctSigned(pnl)}
                  </td>
                  <td className="py-2.5 px-3">
                    <ReasonBadge reason={t.exit_reason} />
                  </td>
                  <td className="py-2.5 px-3 text-slate-400">{modeName(t.mode)}</td>
                  <td className="py-2.5 px-3 text-xs text-slate-500 font-mono">{(t.closed_at ?? "").slice(0, 16)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button
            disabled={page <= 1}
            onClick={() => onPage(page - 1)}
            className="p-2 rounded-lg hover:bg-slate-800 disabled:opacity-30"
          >
            <ChevronLeft size={18} />
          </button>
          <span className="text-sm text-slate-400">
            {page} / {totalPages}
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => onPage(page + 1)}
            className="p-2 rounded-lg hover:bg-slate-800 disabled:opacity-30"
          >
            <ChevronRight size={18} />
          </button>
        </div>
      )}
    </>
  );
}

function ReasonBadge({ reason }: { reason: string | null }) {
  const r = reason ?? "";
  const map: Record<string, string> = {
    tp: "bg-emerald-500/15 text-emerald-400",
    sl: "bg-red-500/15 text-red-400",
    timeout: "bg-amber-500/15 text-amber-400",
    manual: "bg-slate-500/15 text-slate-400",
  };
  const labels: Record<string, string> = {
    tp: "止盈",
    sl: "止损",
    timeout: "超时",
    manual: "手动",
  };
  const cls = map[r] ?? "bg-slate-500/15 text-slate-400";
  const label = labels[r] ?? (r || "—");
  return <span className={`text-xs px-1.5 py-0.5 rounded ${cls}`}>{label}</span>;
}
