import { useEffect, useState } from "react";
import { DollarSign, TrendingDown, BarChart3, Layers } from "lucide-react";
import type { PortfolioStatus, NavHistoryPoint, RiskEvent } from "../api/portfolio";
import { fetchPortfolioStatus, fetchNavHistory, fetchRiskEvents, triggerRebalance } from "../api/portfolio";
import StatCard from "../components/StatCard";
import WeightsPieChart from "../components/WeightsPieChart";
import NavChart from "../components/NavChart";
import RiskStatus from "../components/RiskStatus";
import LoadingSpinner from "../components/LoadingSpinner";

export default function PortfolioPage() {
  const [status, setStatus] = useState<PortfolioStatus | null>(null);
  const [navHistory, setNavHistory] = useState<NavHistoryPoint[]>([]);
  const [riskEvents, setRiskEvents] = useState<RiskEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rebalancing, setRebalancing] = useState(false);

  const load = () => {
    setLoading(true);
    setError(null);

    Promise.all([
      fetchPortfolioStatus().then(setStatus),
      fetchNavHistory().then((r) => setNavHistory(r.history)),
      fetchRiskEvents().then((r) => setRiskEvents(r.events)),
    ])
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const handleRebalance = () => {
    setRebalancing(true);
    triggerRebalance()
      .then((r) => {
        if (r.success && r.weights) {
          setStatus((prev) =>
            prev ? { ...prev, weights: r.weights! } : prev,
          );
        }
      })
      .catch(() => {})
      .finally(() => setRebalancing(false));
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

  if (loading || !status) return <LoadingSpinner />;

  const strategyCount = Object.keys(status.weights).length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-xl font-bold">组合管理</h2>
        <button
          onClick={handleRebalance}
          disabled={rebalancing}
          className="px-4 py-2 rounded-lg bg-blue-500/15 text-blue-400 text-sm font-medium hover:bg-blue-500/25 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {rebalancing ? "再平衡中..." : "再平衡"}
        </button>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          icon={<DollarSign size={18} />}
          label="净值"
          value={status.nav.toFixed(4)}
        />
        <StatCard
          icon={<BarChart3 size={18} />}
          label="高水位"
          value={status.high_water_mark.toFixed(4)}
        />
        <StatCard
          icon={<TrendingDown size={18} />}
          label="回撤"
          value={`${(status.drawdown_pct * 100).toFixed(2)}%`}
          trend={status.drawdown_pct > 0.05 ? "down" : "neutral"}
          sub={status.drawdown_pct > 0.1 ? "警告: 回撤较大" : undefined}
        />
        <StatCard
          icon={<Layers size={18} />}
          label="策略数"
          value={String(strategyCount)}
        />
      </div>

      {/* Two-col: Weights + Risk */}
      <div className="grid lg:grid-cols-2 gap-6">
        {/* 策略权重 */}
        <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
          <p className="text-sm font-semibold text-slate-400 mb-3">策略权重</p>
          <WeightsPieChart weights={status.weights} />
          {strategyCount > 0 && (
            <div className="mt-3 space-y-1">
              {Object.entries(status.weights).map(([name, w]) => (
                <div
                  key={name}
                  className="flex items-center justify-between text-xs py-1 border-b border-slate-800/50 last:border-0"
                >
                  <span className="text-slate-300">{name}</span>
                  <span className="font-mono text-slate-400">
                    {(w * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 风控状态 */}
        <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
          <p className="text-sm font-semibold text-slate-400 mb-3">风控状态</p>
          <RiskStatus
            portfolioHalted={status.portfolio_halted}
            drawdownPct={status.drawdown_pct}
            haltedStrategies={status.halted_strategies}
            riskEvents={riskEvents}
          />
        </div>
      </div>

      {/* NAV Chart */}
      <div className="bg-[var(--color-card)] border border-slate-800 rounded-xl p-4">
        <p className="text-sm font-semibold text-slate-400 mb-3">NAV 曲线</p>
        <NavChart history={navHistory} />
      </div>
    </div>
  );
}
