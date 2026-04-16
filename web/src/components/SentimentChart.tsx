import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import type { SentimentHistoryPoint } from "../api/sentiment";

interface Props {
  history: SentimentHistoryPoint[];
}

export default function SentimentChart({ history }: Props) {
  if (history.length === 0) {
    return (
      <p className="text-sm text-slate-600 py-8 text-center">暂无历史数据</p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={history}>
        <XAxis
          dataKey="date"
          tickFormatter={(d: string) => d.slice(5)}
          tick={{ fill: "#64748b", fontSize: 12 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          domain={[-1, 1]}
          tick={{ fill: "#64748b", fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          width={40}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#1e293b",
            border: "1px solid #334155",
            borderRadius: "8px",
            fontSize: "12px",
          }}
          labelStyle={{ color: "#94a3b8" }}
          formatter={(value: number) => [value.toFixed(3), "情绪得分"]}
        />
        <ReferenceLine y={0} stroke="#334155" strokeDasharray="3 3" />
        <ReferenceLine y={0.1} stroke="#10b98140" strokeDasharray="3 3" />
        <ReferenceLine y={-0.1} stroke="#ef444440" strokeDasharray="3 3" />
        <Line
          type="monotone"
          dataKey="score"
          stroke="#3b82f6"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, fill: "#3b82f6" }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
