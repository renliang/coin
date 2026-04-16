/** 格式化百分比 */
export function pct(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`;
}

/** 格式化带符号的百分比 */
export function pctSigned(value: number, decimals = 1): string {
  const v = value * 100;
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(decimals)}%`;
}

/** 格式化价格 */
export function price(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1000) return value.toFixed(1);
  if (value >= 1) return value.toFixed(2);
  if (value >= 0.01) return value.toFixed(4);
  return value.toFixed(6);
}

/** 格式化分数 badge 颜色 */
export function scoreColor(score: number): string {
  if (score >= 0.85) return "text-emerald-400";
  if (score >= 0.75) return "text-blue-400";
  if (score >= 0.65) return "text-amber-400";
  return "text-slate-400";
}

/** 格式化分数背景颜色 */
export function scoreBg(score: number): string {
  if (score >= 0.85) return "bg-emerald-500/15 border-emerald-500/30";
  if (score >= 0.75) return "bg-blue-500/15 border-blue-500/30";
  if (score >= 0.65) return "bg-amber-500/15 border-amber-500/30";
  return "bg-slate-500/15 border-slate-500/30";
}

/** 模式中文名 */
export function modeName(mode: string): string {
  const map: Record<string, string> = {
    accumulation: "蓄力",
    divergence: "背离",
    breakout: "突破",
    smc: "SMC",
  };
  return map[mode] ?? mode;
}

/** 模式颜色 */
export function modeColor(mode: string): string {
  const map: Record<string, string> = {
    accumulation: "text-blue-400 bg-blue-500/15",
    divergence: "text-purple-400 bg-purple-500/15",
    breakout: "text-orange-400 bg-orange-500/15",
    smc: "text-teal-400 bg-teal-500/15",
  };
  return map[mode] ?? "text-slate-400 bg-slate-500/15";
}

/** 相对时间 */
export function timeAgo(dateStr: string): string {
  const d = new Date(dateStr);
  const now = Date.now();
  const diff = now - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  return `${days}天前`;
}
