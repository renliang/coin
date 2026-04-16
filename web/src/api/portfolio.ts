import { get, post } from "./client";

export interface PortfolioStatus {
  weights: Record<string, number>;
  nav: number;
  high_water_mark: number;
  drawdown_pct: number;
  portfolio_halted: boolean;
  halted_strategies: string[];
}

export interface NavHistoryPoint {
  date: string;
  nav: number;
  high_water_mark: number;
}

export interface RiskEvent {
  id: number;
  level: string;
  strategy_id: string;
  event_type: string;
  details: string;
  created_at: string;
}

export function fetchPortfolioStatus() {
  return get<PortfolioStatus>("/portfolio/status");
}

export function fetchNavHistory(days = 90) {
  return get<{ history: NavHistoryPoint[] }>("/portfolio/nav-history", {
    days: String(days),
  });
}

export function fetchRiskEvents(limit = 20) {
  return get<{ events: RiskEvent[] }>("/portfolio/risk-events", {
    limit: String(limit),
  });
}

export function triggerRebalance() {
  return post<{
    success: boolean;
    weights?: Record<string, number>;
    error?: string;
  }>("/portfolio/rebalance");
}
