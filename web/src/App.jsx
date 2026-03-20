import { useEffect, useState } from "react"
import axios from "axios"
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"

const API = "http://localhost:8080"

function StatCard({ title, value, sub }) {
  return (
    <div className="bg-gray-800 rounded-xl p-4 flex flex-col gap-1">
      <div className="text-gray-400 text-sm">{title}</div>
      <div className="text-white text-2xl font-bold">{value}</div>
      {sub && <div className="text-gray-500 text-xs">{sub}</div>}
    </div>
  )
}

function PositionRow({ pos }) {
  const isLong = pos.direction === "long"
  return (
    <tr className="border-t border-gray-700">
      <td className="py-2 text-white">{pos.symbol}</td>
      <td className={`py-2 font-semibold ${isLong ? "text-green-400" : "text-red-400"}`}>
        {isLong ? "多" : "空"}
      </td>
      <td className="py-2 text-gray-300">{pos.size}</td>
      <td className="py-2 text-gray-300">{pos.entry_price?.toFixed(2)}</td>
      <td className="py-2 text-red-400">{pos.stop_loss?.toFixed(2)}</td>
    </tr>
  )
}

export default function App() {
  const [account, setAccount] = useState({ balance: 0, available: 0, daily_pnl: 0 })
  const [positions, setPositions] = useState([])
  const [orders, setOrders] = useState([])
  const [strategies, setStrategies] = useState([])

  const fetchData = async () => {
    try {
      const [acc, pos, ord, strat] = await Promise.all([
        axios.get(`${API}/api/account`),
        axios.get(`${API}/api/positions`),
        axios.get(`${API}/api/orders`),
        axios.get(`${API}/api/strategies`),
      ])
      setAccount(acc.data)
      setPositions(pos.data)
      setOrders(ord.data)
      setStrategies(strat.data)
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 5000)
    return () => clearInterval(interval)
  }, [])

  const pnlData = orders
    .filter(o => o.pnl !== null)
    .slice(0, 30)
    .reverse()
    .map((o, i) => ({ i, pnl: o.pnl }))

  const cumPnl = pnlData.reduce((acc, d, i) => {
    const prev = i === 0 ? 0 : acc[i - 1].cum
    return [...acc, { i: d.i, cum: prev + d.pnl }]
  }, [])

  const dailyPnlColor = (account.daily_pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"

  return (
    <div className="min-h-screen bg-gray-900 text-white p-6">
      <h1 className="text-2xl font-bold mb-6">币圈量化 Dashboard</h1>

      {/* 账户总览 */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <StatCard title="账户余额" value={`${(account.balance ?? 0).toFixed(2)} USDT`} />
        <StatCard title="可用余额" value={`${(account.available ?? 0).toFixed(2)} USDT`} />
        <StatCard
          title="今日盈亏"
          value={<span className={dailyPnlColor}>{(account.daily_pnl ?? 0) >= 0 ? "+" : ""}{(account.daily_pnl ?? 0).toFixed(2)} USDT</span>}
        />
        <StatCard title="持仓数" value={positions.length} sub={`策略数: ${strategies.length}`} />
      </div>

      <div className="grid grid-cols-2 gap-6 mb-6">
        {/* 当前持仓 */}
        <div className="bg-gray-800 rounded-xl p-4">
          <h2 className="font-semibold mb-3">当前持仓</h2>
          {positions.length === 0 ? (
            <div className="text-gray-500 text-sm">暂无持仓</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 text-left">
                  <th className="pb-2">品种</th><th>方向</th><th>张数</th><th>入场价</th><th>止损</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p, i) => <PositionRow key={i} pos={p} />)}
              </tbody>
            </table>
          )}
        </div>

        {/* 收益曲线 */}
        <div className="bg-gray-800 rounded-xl p-4">
          <h2 className="font-semibold mb-3">累计收益曲线</h2>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={cumPnl}>
              <XAxis dataKey="i" hide />
              <YAxis />
              <Tooltip formatter={(v) => [`${v.toFixed(2)} USDT`]} />
              <Line type="monotone" dataKey="cum" stroke="#22c55e" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 策略状态 */}
      <div className="bg-gray-800 rounded-xl p-4 mb-6">
        <h2 className="font-semibold mb-3">策略状态</h2>
        <div className="flex flex-wrap gap-3">
          {strategies.map(s => (
            <div key={s.id} className="bg-gray-700 rounded-lg px-3 py-2 flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${s.enabled ? "bg-green-400" : "bg-red-400"}`} />
              <span className="text-sm">{s.id}</span>
              <span className="text-gray-400 text-xs">{s.symbol} {s.timeframe}</span>
            </div>
          ))}
          {strategies.length === 0 && <div className="text-gray-500 text-sm">暂无策略</div>}
        </div>
      </div>

      {/* 历史订单 */}
      <div className="bg-gray-800 rounded-xl p-4">
        <h2 className="font-semibold mb-3">历史订单（最近100笔）</h2>
        {orders.length === 0 ? (
          <div className="text-gray-500 text-sm">暂无订单记录</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-400 text-left">
                <th className="pb-2">品种</th><th>方向</th><th>张数</th><th>入场</th><th>出场</th><th>盈亏</th><th>状态</th>
              </tr>
            </thead>
            <tbody>
              {orders.map(o => (
                <tr key={o.id} className="border-t border-gray-700">
                  <td className="py-1 text-white">{o.symbol}</td>
                  <td className={`py-1 ${o.direction === "long" ? "text-green-400" : "text-red-400"}`}>{o.direction === "long" ? "多" : "空"}</td>
                  <td className="py-1 text-gray-300">{o.size}</td>
                  <td className="py-1 text-gray-300">{o.entry_price?.toFixed(2)}</td>
                  <td className="py-1 text-gray-300">{o.exit_price?.toFixed(2) ?? "-"}</td>
                  <td className={`py-1 font-semibold ${(o.pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {o.pnl != null ? `${o.pnl >= 0 ? "+" : ""}${o.pnl.toFixed(2)}` : "-"}
                  </td>
                  <td className="py-1 text-gray-400 text-xs">{o.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
