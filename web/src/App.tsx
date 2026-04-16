import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Signals from "./pages/Signals";
import Positions from "./pages/Positions";
import CoinDetail from "./pages/CoinDetail";
import Performance from "./pages/Performance";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="signals" element={<Signals />} />
        <Route path="positions" element={<Positions />} />
        <Route path="coin/:symbol" element={<CoinDetail />} />
        <Route path="performance" element={<Performance />} />
      </Route>
    </Routes>
  );
}
