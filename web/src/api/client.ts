const BASE = "/api";

async function get<T>(path: string, params?: Record<string, string | undefined>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v != null && v !== "") url.searchParams.set(k, v);
    }
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path, { method: "POST" });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

// ── Types ──

export interface ScoreComponent {
  name: string;
  score: number;
  weight: number;
}

export interface ScoreBreakdownData {
  mode: string;
  components: ScoreComponent[];
  total: number;
}

export interface KlineBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ActiveSignal extends Signal {
  id: number;
  lifecycle_state: string;
  current_price: number | null;
  unrealized_pnl_pct: number | null;
  price_updated_at: string | null;
  entered_at: string | null;
  approaching: "sl" | "tp" | null;
}

export interface Signal {
  symbol: string;
  price: number;
  score: number;
  entry_price: number | null;
  stop_loss_price: number | null;
  take_profit_price: number | null;
  signal_type: string;
  mode: string;
  drop_pct?: number;
  volume_ratio?: number;
  window_days?: number;
  market_cap_m?: number;
  scan_time?: string;
  score_breakdown?: ScoreBreakdownData | null;
}

export interface Position {
  id: number;
  symbol: string;
  side: string;
  entry_price: number;
  size: number;
  leverage: number;
  score: number;
  status: string;
  opened_at: string;
  closed_at: string | null;
  exit_price: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  exit_reason: string | null;
  mode: string;
}

export interface DashboardData {
  kpi: {
    today_signals: number;
    active_positions: number;
    today_pnl_pct: number;
    today_pnl_count: number;
    win_rate: number;
    total_trades: number;
  };
  top_signals: Signal[];
  positions: Position[];
  hit_rate_7d: { date: string; total: number; wins: number; win_rate: number }[];
  signal_counts: { accumulation: number; divergence: number; breakout: number };
  is_today: boolean;
  last_scan_time: string | null;
}

export interface PaginatedSignals {
  data: Signal[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

export interface PerformanceData {
  overall: {
    total: number;
    wins: number;
    win_rate: number;
    avg_pnl_pct: number;
    profit_factor: number;
    max_gain: number;
    max_loss: number;
  };
  by_mode: Record<string, { total: number; wins: number; win_rate: number; avg_pnl_pct: number; profit_factor: number }>;
  by_score: Record<string, { total: number; wins: number; win_rate: number; avg_pnl_pct: number; profit_factor: number }>;
  by_month: Record<string, { total: number; wins: number; win_rate: number; avg_pnl_pct: number; profit_factor: number }>;
  cumulative_pnl: { date: string; cumulative_pnl: number }[];
}

// ── API Functions ──

export const fetchDashboard = () => get<DashboardData>("/dashboard");

export const fetchSignals = (params?: {
  mode?: string;
  min_score?: string;
  date_from?: string;
  date_to?: string;
  page?: string;
  per_page?: string;
}) => get<PaginatedSignals>("/signals", params);

export const fetchPositions = () => get<{ data: Position[] }>("/positions");

export const fetchClosedPositions = (page = "1", per_page = "20") =>
  get<{ data: Position[]; total: number; page: number; total_pages: number }>(
    "/positions/closed",
    { page, per_page },
  );

export const fetchCoinDetail = (symbol: string) =>
  get<{ symbol: string; scans: Signal[]; trades: Position[]; total_scans: number }>(
    `/coin/${symbol}`,
  );

export const fetchPerformance = () => get<PerformanceData>("/performance");

export const triggerScan = () => post<{ started: boolean; reason?: string }>("/scan");

export const fetchScanStatus = () =>
  get<{ running: boolean; started_at: number | null; finished_at: number | null; error: string | null }>(
    "/scan/status",
  );

export const fetchKlines = (symbol: string, days = 30) =>
  get<{ symbol: string; days: number; data: KlineBar[] }>(`/klines/${symbol}`, { days: String(days) });

export const fetchActiveSignals = () =>
  get<{ data: ActiveSignal[] }>("/signals/active");

export const fetchSignalOutcomes = (days = 30) =>
  get<{ data: Record<string, number> }>("/signals/outcomes", { days: String(days) });

export const fetchSignalTrend = (days = 7) =>
  get<{ data: { day: string; mode: string; cnt: number }[] }>("/signals/trend", { days: String(days) });
