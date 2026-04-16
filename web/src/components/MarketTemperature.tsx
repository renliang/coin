interface TrendItem {
  day: string;
  mode: string;
  cnt: number;
}

interface Props {
  trend: TrendItem[];
}

export default function MarketTemperature({ trend }: Props) {
  // aggregate daily totals
  const dailyMap = new Map<string, number>();
  for (const t of trend) {
    dailyMap.set(t.day, (dailyMap.get(t.day) ?? 0) + t.cnt);
  }
  const days = [...dailyMap.entries()].sort(([a], [b]) => a.localeCompare(b));

  if (days.length === 0) {
    return (
      <div className="text-xs text-slate-500 text-center py-2">
        暂无趋势数据
      </div>
    );
  }

  const todayCount = days[days.length - 1]?.[1] ?? 0;
  const avg = days.reduce((s, [, c]) => s + c, 0) / days.length;
  const ratio = avg > 0 ? todayCount / avg : 0;

  let label: string;
  let color: string;
  if (ratio < 0.5) {
    label = "冷";
    color = "text-blue-400 bg-blue-500/15 border-blue-500/30";
  } else if (ratio <= 1.5) {
    label = "温";
    color = "text-amber-400 bg-amber-500/15 border-amber-500/30";
  } else {
    label = "热";
    color = "text-red-400 bg-red-500/15 border-red-500/30";
  }

  return (
    <div className="flex items-center gap-3">
      <span className={`px-2.5 py-1 rounded-lg text-xs font-bold border ${color}`}>
        {label}
      </span>
      <div className="flex items-end gap-0.5 h-6">
        {days.map(([day, cnt]) => {
          const maxCnt = Math.max(...days.map(([, c]) => c), 1);
          const h = Math.max(4, (cnt / maxCnt) * 24);
          return (
            <div
              key={day}
              className="w-2 rounded-sm bg-slate-600"
              style={{ height: `${h}px` }}
              title={`${day}: ${cnt}`}
            />
          );
        })}
      </div>
      <span className="text-xs text-slate-500">
        今日 {todayCount} / 均值 {avg.toFixed(0)}
      </span>
    </div>
  );
}
