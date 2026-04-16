import { useEffect, useState } from "react";
import { DollarSign, TrendingDown, Activity, Layers } from "lucide-react";
import type { DashboardData } from "../api/client";
import { fetchDashboard } from "../api/client";
import type { PortfolioStatus, RiskEvent } from "../api/portfolio";
import { fetchPortfolioStatus, fetchRiskEvents } from "../api/portfolio";
import type { SentimentSignalData } from "../api/sentiment";
import { fetchSentimentLatest } from "../api/sentiment";
import StatCard from "../components/StatCard";
import WeightsPieChart from "../components/WeightsPieChart";
import SignalCard from "../components/SignalCard";
import LoadingSpinner from "../components/LoadingSpinner";

export default function DashboardV2() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioStatus | null>(null);
  const [sentimentSignals, setSentimentSignals] = useState<SentimentSignalData[]>([]);
  const [riskEvents, setRiskEvents] = useState<RiskEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setError(null);
    fetchDashboard()
      .then(setDashboard)
      .catch((e: Error) => setError(e.message));
    fetchPortfolioStatus()
      .then(setPortfolio)
      .catch(() => {});
    fetchSentimentLatest()
      .then((r) => setSentimentSignals(r.signals))
      .catch(() => {});
    fetchRiskEvents(5)
      .then((r) => setRiskEvents(r.events))
      .catch(() => {});
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

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

  if (!dashboard) return <LoadingSpinner />;

  // Compute average sentiment score
  const avgSentiment =
    sentimentSignals.length > 0
      ? sentimentSignals.reduce((sum, s) => sum + s.score, 0) /
        sentimentSignals.length
      : 0;
  const sentimentLabel =
    avgSentiment > 0.1 ? "偏多" : avgSentiment < -0.1 ? "偏空" : "中性";

  const strategyCount = portfolio
    ? Object.keys(portfolio.weights).length
    : 0;

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold">总览</h2>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          icon={<DollarSign size={18} />}
          label="总净值"
          value={portfolio ? portfolio.nav.toFixed(4) : "--"}
        />
        <StatCard
          icon={<TrendingDown size={18} />}
          label="回撤"
          value={
            portfolio
              ? `${(portfolio.drawdown_pct * 100).toFixed(2)}%`
              : "--"
          }
          trend={
            portfolio && portfolio.drawdown_pct > 0.05 ? "down" : "neutral"
          }
        />
        <StatCard
          icon={<Activity size={18} />}
          label="市场情绪"
          value={sentimentSignals.length > 0 ? avgSentiment.toFixed(3) : "--"}
          sub={sentimentSignals.length > 0 ? sentimentLabel : undefined}
          trend={
            avgSentiment > 0.1
              ? "up"
              : avgSentiment < -0.1
                ? "down"
                : "neutral"
          }
        />
        <StatCard
          icon={<Layers size={18} />}
          label="策略数"
          value={String(strategyCount)}
        />
      </div>

      {/* Two-col: Weights + Risk events */}
      <div className="grid lg:grid-cols-2 gap-6">
        {/* 策略权重 */}
        <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
          <p className="text-sm font-semibold text-slate-400 mb-3">策略权重</p>
          {portfolio ? (
            <WeightsPieChart weights={portfolio.weights} />
          ) : (
            <p className="text-sm text-slate-600 py-8 text-center">
              加载中...
            </p>
          )}
        </div>

        {/* 最近风控事件 */}
        <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
          <p className="text-sm font-semibold text-slate-400 mb-3">
            最近风控事件
          </p>
          {riskEvents.length === 0 ? (
            <p className="text-sm text-slate-600 py-8 text-center">
              暂无风控事件
            </p>
          ) : (
            <div className="space-y-2">
              {riskEvents.map((e) => (
                <div
                  key={e.id}
                  className="flex items-start gap-2 py-1.5 border-b border-slate-800/50 last:border-0"
                >
                  <span
                    className={`inline-block px-1.5 py-0.5 rounded text-xs shrink-0 mt-0.5 ${
                      e.level === "portfolio"
                        ? "bg-red-500/15 text-red-400"
                        : e.level === "strategy"
                          ? "bg-amber-500/15 text-amber-400"
                          : "bg-blue-500/15 text-blue-400"
                    }`}
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
          )}
        </div>
      </div>

      {/* Recent scan signals */}
      <section className="space-y-3">
        <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider">
          最新扫描信号
        </h3>
        {dashboard.top_signals.length === 0 ? (
          <p className="text-sm text-slate-600 py-8 text-center">暂无信号</p>
        ) : (
          <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-2">
            {dashboard.top_signals.map((s) => (
              <SignalCard key={s.symbol + s.mode} signal={s} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
