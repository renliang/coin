import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { NavHistoryPoint } from "../api/portfolio";

interface Props {
  history: NavHistoryPoint[];
}

export default function NavChart({ history }: Props) {
  if (history.length === 0) {
    return (
      <p className="text-sm text-slate-600 py-8 text-center">暂无净值数据</p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={300}>
      <ComposedChart data={history}>
        <XAxis
          dataKey="date"
          tickFormatter={(d: string) => d.slice(5)}
          tick={{ fill: "#64748b", fontSize: 12 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: "#64748b", fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          width={50}
          domain={["auto", "auto"]}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#1e293b",
            border: "1px solid #334155",
            borderRadius: "8px",
            fontSize: "12px",
          }}
          labelStyle={{ color: "#94a3b8" }}
          formatter={(value: number, name: string) => {
            const label = name === "nav" ? "净值" : "高水位";
            return [value.toFixed(4), label];
          }}
        />
        <Area
          type="monotone"
          dataKey="nav"
          stroke="#3b82f6"
          fill="#3b82f620"
          strokeWidth={2}
        />
        <Line
          type="monotone"
          dataKey="high_water_mark"
          stroke="#8b5cf6"
          strokeWidth={1.5}
          strokeDasharray="6 3"
          dot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
