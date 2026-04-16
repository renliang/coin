import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  Radio,
  Briefcase,
  TrendingUp,
} from "lucide-react";

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "首页" },
  { to: "/signals", icon: Radio, label: "信号" },
  { to: "/positions", icon: Briefcase, label: "持仓" },
  { to: "/performance", icon: TrendingUp, label: "绩效" },
] as const;

export default function Layout() {
  return (
    <div className="min-h-screen bg-[var(--color-bg)] text-slate-100">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex fixed left-0 top-0 bottom-0 w-56 flex-col border-r border-slate-800 bg-slate-950 z-40">
        <div className="px-5 py-5">
          <h1 className="text-lg font-bold tracking-tight">
            <span className="text-blue-400">Coin</span> Quant
          </h1>
        </div>
        <nav className="flex-1 px-3 space-y-1">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  isActive
                    ? "bg-blue-500/15 text-blue-400 font-medium"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <main className="md:ml-56 pb-20 md:pb-6">
        <div className="max-w-7xl mx-auto px-4 py-6">
          <Outlet />
        </div>
      </main>

      {/* Mobile bottom nav */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-slate-950 border-t border-slate-800 z-40">
        <div className="flex justify-around py-2">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex flex-col items-center gap-0.5 px-3 py-1 text-xs transition-colors ${
                  isActive ? "text-blue-400" : "text-slate-500"
                }`
              }
            >
              <Icon size={20} />
              {label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
