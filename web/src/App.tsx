import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import DashboardV2 from "./pages/DashboardV2";
import Signals from "./pages/Signals";
import Positions from "./pages/Positions";
import CoinDetail from "./pages/CoinDetail";
import Performance from "./pages/Performance";
import SentimentPage from "./pages/SentimentPage";
import PortfolioPage from "./pages/PortfolioPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardV2 />} />
        <Route path="signals" element={<Signals />} />
        <Route path="positions" element={<Positions />} />
        <Route path="coin/:symbol" element={<CoinDetail />} />
        <Route path="performance" element={<Performance />} />
        <Route path="sentiment" element={<SentimentPage />} />
        <Route path="portfolio" element={<PortfolioPage />} />
      </Route>
    </Routes>
  );
}
