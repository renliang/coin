import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

const COLORS = ["#3b82f6", "#8b5cf6", "#f97316", "#10b981", "#ef4444"];

interface Props {
  weights: Record<string, number>;
}

export default function WeightsPieChart({ weights }: Props) {
  const entries = Object.entries(weights);

  if (entries.length === 0) {
    return (
      <p className="text-sm text-slate-600 py-8 text-center">暂无权重数据</p>
    );
  }

  const data = entries.map(([name, value]) => ({
    name,
    value: Math.round(value * 1000) / 10,
  }));

  return (
    <ResponsiveContainer width="100%" height={240}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={50}
          outerRadius={90}
          dataKey="value"
          label={({ name, value }: { name: string; value: number }) =>
            `${name} ${value}%`
          }
          labelLine={false}
        >
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            backgroundColor: "#1e293b",
            border: "1px solid #334155",
            borderRadius: "8px",
            fontSize: "12px",
          }}
          formatter={(value: number) => [`${value}%`, "权重"]}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
