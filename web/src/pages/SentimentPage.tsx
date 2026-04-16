import { useEffect, useState } from "react";
import type { SentimentSignalData, SentimentItemData, SentimentHistoryPoint } from "../api/sentiment";
import { fetchSentimentLatest, fetchSentimentHistory, fetchSentimentItems } from "../api/sentiment";
import SentimentTable from "../components/SentimentTable";
import SentimentChart from "../components/SentimentChart";
import SentimentItems from "../components/SentimentItems";
import LoadingSpinner from "../components/LoadingSpinner";

export default function SentimentPage() {
  const [signals, setSignals] = useState<SentimentSignalData[]>([]);
  const [history, setHistory] = useState<SentimentHistoryPoint[]>([]);
  const [items, setItems] = useState<SentimentItemData[]>([]);
  const [itemsTotal, setItemsTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [source, setSource] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const perPage = 20;

  const loadItems = (p: number, src: string) => {
    const params: Record<string, string> = {
      page: String(p),
      per_page: String(perPage),
    };
    if (src) params.source = src;

    fetchSentimentItems(params)
      .then((r) => {
        setItems(r.items);
        setItemsTotal(r.total);
      })
      .catch(() => {});
  };

  const load = () => {
    setLoading(true);
    setError(null);

    Promise.all([
      fetchSentimentLatest().then((r) => setSignals(r.signals)),
      fetchSentimentHistory().then((r) => setHistory(r.history)),
    ])
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));

    loadItems(page, source);
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    loadItems(page, source);
  }, [page, source]);

  const handleSourceFilter = (src: string) => {
    setSource(src);
    setPage(1);
  };

  if (error) {
    return (
      <div className="text-center py-20 text-red-400">
        <p className="text-lg mb-2">加载失败</p>
        <p className="text-sm text-slate-500">{error}</p>
        <button
          onClick={load}
          className="mt-4 px-4 py-2 rounded-lg bg-blue-500/15 text-blue-400 text-sm hover:bg-blue-500/25 transition-colors"
        >
          重试
        </button>
      </div>
    );
  }

  if (loading) return <LoadingSpinner />;

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold">舆情分析</h2>

      {/* 情绪信号 */}
      <section className="space-y-3">
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider">
          情绪信号
        </h3>
        <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
          <SentimentTable signals={signals} />
        </div>
      </section>

      {/* 情绪趋势 */}
      <section className="space-y-3">
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider">
          情绪趋势
        </h3>
        <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
          <SentimentChart history={history} />
        </div>
      </section>

      {/* 原始数据 */}
      <section className="space-y-3">
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider">
          原始数据
        </h3>
        <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
          <SentimentItems
            items={items}
            total={itemsTotal}
            page={page}
            perPage={perPage}
            onPageChange={setPage}
            onSourceFilter={handleSourceFilter}
            currentSource={source}
          />
        </div>
      </section>
    </div>
  );
}
