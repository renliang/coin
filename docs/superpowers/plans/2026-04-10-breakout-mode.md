# 天量回踩二攻模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `--mode breakout` 扫描模式，检测天量拉升→缩量回调→放量二攻的强势回调买入信号。

**Architecture:** 新增 `scanner/breakout.py`（BreakoutResult + detect_breakout + score_breakout），在 `main.py` 新增 `run_breakout()` 入口，复用现有确认层、信号生成和跟踪模块。

**Tech Stack:** Python 3.13, pandas, numpy, math（无新增依赖）

---

### Task 1: BreakoutResult 数据类 + detect_breakout 骨架

**Files:**
- Create: `scanner/breakout.py`
- Create: `tests/test_breakout.py`

- [ ] **Step 1: 写 detect_breakout 不命中的测试**

```python
# tests/test_breakout.py
import pandas as pd
import numpy as np
from scanner.breakout import detect_breakout, BreakoutResult


def _make_klines(prices: list[float], volumes: list[float]) -> pd.DataFrame:
    n = len(prices)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": volumes,
    })


def test_no_spike_returns_unmatched():
    """均匀量能无天量 -> 不命中。"""
    prices = [10.0 + i * 0.1 for i in range(30)]
    volumes = [1000.0] * 30
    df = _make_klines(prices, volumes)
    result = detect_breakout(df)
    assert result.matched is False
    assert result.score == 0.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_breakout.py::test_no_spike_returns_unmatched -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现骨架**

```python
# scanner/breakout.py
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BreakoutResult:
    matched: bool
    spike_date: str = ""
    spike_volume_ratio: float = 0.0
    spike_high: float = 0.0
    pullback_low: float = 0.0
    pullback_shrink: float = 0.0
    reattack_date: str = ""
    reattack_volume_ratio: float = 0.0
    reattack_close: float = 0.0
    days_since_spike: int = 0
    score: float = 0.0


def detect_breakout(
    df: pd.DataFrame,
    spike_multiplier: float = 5.0,
    shrink_threshold: float = 0.3,
    reattack_multiplier: float = 2.0,
    max_pullback_days: int = 10,
    freshness_days: int = 3,
) -> BreakoutResult:
    """检测天量→缩量回调→放量二攻模式。"""
    if len(df) < 25:
        return BreakoutResult(matched=False)

    closes = df["close"].astype(float).values
    volumes = df["volume"].astype(float).values
    highs = df["high"].astype(float).values
    lows = df["low"].astype(float).values
    dates = df["timestamp"].values
    n = len(df)

    # Step 1: 找天量日（从最近往前找，取最近一个）
    spike_idx = -1
    for i in range(n - 2, 19, -1):  # 至少需要20日基线
        baseline = np.mean(volumes[max(0, i - 20):i])
        if baseline > 0 and volumes[i] >= baseline * spike_multiplier:
            spike_idx = i
            break

    if spike_idx < 0:
        return BreakoutResult(matched=False)

    # Step 2: 天量日后检查缩量回调
    spike_vol = volumes[spike_idx]
    search_end = min(n, spike_idx + max_pullback_days + 1)

    # 找缩量阶段：至少连续2天量 < 天量 * shrink_threshold
    shrink_start = -1
    for i in range(spike_idx + 1, search_end):
        if volumes[i] < spike_vol * shrink_threshold:
            if shrink_start < 0:
                shrink_start = i
        else:
            if shrink_start >= 0 and i - shrink_start >= 2:
                break
            shrink_start = -1

    if shrink_start < 0:
        return BreakoutResult(matched=False)

    # 回调阶段最低价和最小量
    pullback_end = min(n, spike_idx + max_pullback_days + 1)
    pullback_slice = slice(shrink_start, pullback_end)
    pullback_low = float(np.min(lows[pullback_slice]))
    pullback_min_vol = float(np.min(volumes[pullback_slice]))
    pullback_shrink = pullback_min_vol / spike_vol

    # Step 3: 缩量后找放量二攻
    reattack_idx = -1
    for i in range(shrink_start + 2, min(n, pullback_end)):
        recent_3d_avg = np.mean(volumes[max(shrink_start, i - 3):i])
        if recent_3d_avg > 0 and volumes[i] >= recent_3d_avg * reattack_multiplier:
            reattack_idx = i
            break  # 取第一个二攻日

    if reattack_idx < 0:
        return BreakoutResult(matched=False)

    # Step 4: 新鲜度检查 — 二攻日必须在最近 freshness_days 内
    if (n - 1 - reattack_idx) >= freshness_days:
        return BreakoutResult(matched=False)

    # 构造结果
    spike_date = str(pd.Timestamp(dates[spike_idx]).date())
    reattack_date = str(pd.Timestamp(dates[reattack_idx]).date())
    spike_vol_ratio = float(volumes[spike_idx] / np.mean(volumes[max(0, spike_idx - 20):spike_idx]))
    reattack_recent_avg = float(np.mean(volumes[max(shrink_start, reattack_idx - 3):reattack_idx]))
    reattack_vol_ratio = float(volumes[reattack_idx] / reattack_recent_avg) if reattack_recent_avg > 0 else 0.0
    reattack_close = float(closes[reattack_idx])
    spike_high = float(highs[spike_idx])

    score = _score_breakout(spike_vol_ratio, pullback_shrink, reattack_vol_ratio, reattack_close, spike_high)

    return BreakoutResult(
        matched=True,
        spike_date=spike_date,
        spike_volume_ratio=round(spike_vol_ratio, 1),
        spike_high=round(spike_high, 6),
        pullback_low=round(pullback_low, 6),
        pullback_shrink=round(pullback_shrink, 4),
        reattack_date=reattack_date,
        reattack_volume_ratio=round(reattack_vol_ratio, 1),
        reattack_close=round(reattack_close, 6),
        days_since_spike=int(reattack_idx - spike_idx),
        score=round(score, 4),
    )


def _score_breakout(
    spike_vol_ratio: float,
    pullback_shrink: float,
    reattack_vol_ratio: float,
    reattack_close: float,
    spike_high: float,
) -> float:
    """计算天量回踩二攻评分 [0, 1]。"""
    # 天量倍数分 (0.3): 对数缩放 5x=0.3, 10x=0.6, 50x+=1.0
    spike_score = min(1.0, math.log(spike_vol_ratio / 5.0 + 1) / math.log(11))

    # 缩量质量分 (0.2): 缩到10%=1.0, 30%=0.5, 50%+=0
    shrink_score = max(0.0, 1.0 - pullback_shrink / 0.5)

    # 二攻力度分 (0.3): 对数缩放 2x=0.3, 5x=0.7, 10x+=1.0
    reattack_score = min(1.0, math.log(reattack_vol_ratio / 2.0 + 1) / math.log(6))

    # 价格位置分 (0.2): 收盘 vs 天量高点
    position_score = min(1.0, reattack_close / spike_high) if spike_high > 0 else 0.0

    return spike_score * 0.3 + shrink_score * 0.2 + reattack_score * 0.3 + position_score * 0.2


- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_breakout.py -v`
Expected: 1 passed

- [ ] **Step 5: 提交**

```bash
git add scanner/breakout.py tests/test_breakout.py
git commit -m "feat: add breakout detection skeleton — BreakoutResult + detect_breakout"
```

---

### Task 2: detect_breakout 命中场景测试

**Files:**
- Modify: `tests/test_breakout.py`

- [ ] **Step 1: 写 ONG 模式的命中测试**

在 `tests/test_breakout.py` 末尾追加：

```python
def _make_ong_like_data() -> pd.DataFrame:
    """模拟 ONG 模式：20日平盘 → 天量拉升 → 5日缩量回调 → 放量二攻。"""
    # 20日基线：价格10, 量100
    base_prices = [10.0] * 20
    base_volumes = [100.0] * 20
    # 天量日：价格拉升到15，量1100（11x）
    spike_prices = [15.0]
    spike_volumes = [1100.0]
    # 5日缩量回调：价格跌到12，量缩到20-50
    pullback_prices = [14.0, 13.5, 13.0, 12.5, 12.0]
    pullback_volumes = [50.0, 30.0, 20.0, 25.0, 20.0]
    # 二攻日：量回升到80（近3日均量21.7的3.7x），价格回到13.5
    reattack_prices = [13.5]
    reattack_volumes = [80.0]

    prices = base_prices + spike_prices + pullback_prices + reattack_prices
    volumes = base_volumes + spike_volumes + pullback_volumes + reattack_volumes
    return _make_klines(prices, volumes)


def test_ong_like_pattern_matches():
    """ONG 模式应命中。"""
    df = _make_ong_like_data()
    result = detect_breakout(df, freshness_days=5)
    assert result.matched is True
    assert result.spike_volume_ratio >= 10.0
    assert result.pullback_shrink < 0.3
    assert result.reattack_volume_ratio >= 2.0
    assert result.score > 0.5


def test_no_reattack_returns_unmatched():
    """天量后缩量但无二攻 -> 不命中（类似 FIDA）。"""
    base_prices = [10.0] * 20
    base_volumes = [100.0] * 20
    spike_prices = [15.0]
    spike_volumes = [1100.0]
    # 持续缩量，没有二攻
    pullback_prices = [14.0, 13.5, 13.0, 12.5, 12.0, 11.8, 11.5, 11.3]
    pullback_volumes = [50.0, 30.0, 20.0, 15.0, 12.0, 10.0, 10.0, 10.0]

    prices = base_prices + spike_prices + pullback_prices
    volumes = base_volumes + spike_volumes + pullback_volumes
    df = _make_klines(prices, volumes)
    result = detect_breakout(df, freshness_days=5)
    assert result.matched is False


def test_stale_reattack_returns_unmatched():
    """二攻日太旧（超过 freshness_days）-> 不命中。"""
    df = _make_ong_like_data()
    # freshness_days=0 意味着二攻日必须是最后一天
    # 由于 _make_ong_like_data 的二攻日就是最后一天，用 index 偏移模拟旧数据
    # 追加5天平盘让二攻日变旧
    extra_prices = [13.5] * 5
    extra_volumes = [20.0] * 5
    prices = [float(df["close"].iloc[i]) for i in range(len(df))] + extra_prices
    volumes = [float(df["volume"].iloc[i]) for i in range(len(df))] + extra_volumes
    df2 = _make_klines(prices, volumes)
    result = detect_breakout(df2, freshness_days=3)
    assert result.matched is False
```

- [ ] **Step 2: 运行测试**

Run: `.venv/bin/pytest tests/test_breakout.py -v`
Expected: 4 passed

- [ ] **Step 3: 如果有测试失败，调整 detect_breakout 逻辑**

可能需要调整缩量检测的边界条件。修复后重跑直到全部通过。

- [ ] **Step 4: 提交**

```bash
git add tests/test_breakout.py scanner/breakout.py
git commit -m "test: add breakout detection scenario tests — ONG pattern, FIDA exclusion, staleness"
```

---

### Task 3: _score_breakout 评分测试

**Files:**
- Modify: `tests/test_breakout.py`

- [ ] **Step 1: 写评分测试**

在 `tests/test_breakout.py` 末尾追加：

```python
from scanner.breakout import _score_breakout


def test_score_strong_breakout():
    """强势模式（高天量+深缩量+强二攻+高位收盘）应高分。"""
    score = _score_breakout(
        spike_vol_ratio=20.0,
        pullback_shrink=0.05,
        reattack_vol_ratio=8.0,
        reattack_close=14.0,
        spike_high=15.0,
    )
    assert score > 0.7


def test_score_weak_breakout():
    """弱模式（刚过阈值）应低分。"""
    score = _score_breakout(
        spike_vol_ratio=5.0,
        pullback_shrink=0.45,
        reattack_vol_ratio=2.0,
        reattack_close=10.0,
        spike_high=15.0,
    )
    assert score < 0.4


def test_score_range():
    """评分应在 [0, 1] 范围内。"""
    for svr in [5, 10, 50, 100]:
        for ps in [0.01, 0.1, 0.3, 0.5]:
            for rvr in [2, 5, 10]:
                score = _score_breakout(svr, ps, rvr, 12.0, 15.0)
                assert 0.0 <= score <= 1.0
```

- [ ] **Step 2: 运行测试**

Run: `.venv/bin/pytest tests/test_breakout.py -v`
Expected: 7 passed

- [ ] **Step 3: 提交**

```bash
git add tests/test_breakout.py
git commit -m "test: add breakout scoring tests — strong, weak, range validation"
```

---

### Task 4: config.yaml + main.py 集成

**Files:**
- Modify: `config.yaml`
- Modify: `main.py:0-18` (imports)
- Modify: `main.py:612-685` (argparse + main)

- [ ] **Step 1: 在 config.yaml 末尾追加 breakout 配置段**

```yaml

# 天量回踩二攻模式（--mode breakout）
breakout:
  spike_multiplier: 5.0       # 天量倍数阈值（单日量 >= 20日均量 × N）
  shrink_threshold: 0.3       # 缩量需低于天量的 30%
  reattack_multiplier: 2.0    # 二攻量 >= 近3日均量 × N
  max_pullback_days: 10       # 天量后最多等10天出现二攻
  freshness_days: 3           # 二攻日必须在最近N天内
  top_n: 20
```

- [ ] **Step 2: 在 main.py 顶部添加 import**

在 `from scanner.confirmation import confirm_signal` 之后添加：

```python
from scanner.breakout import detect_breakout
```

- [ ] **Step 3: 在 main.py 添加 run_breakout 函数**

在 `run_divergence()` 函数之后（约 360 行），`show_tracking()` 之前，添加：

```python
def run_breakout(config: dict, signal_config: SignalConfig, top_n: int | None = None, symbols_override: list[str] | None = None):
    breakout_cfg = config.get("breakout", {})
    top_n = top_n or breakout_cfg.get("top_n", 20)
    max_market_cap = config.get("max_market_cap", 100_000_000)

    # Step 1: 获取交易对列表
    if symbols_override:
        symbols = symbols_override
        print(f"[1/4] 使用指定的 {len(symbols)} 个交易对")
    else:
        print("[1/4] 获取Binance U本位永续与现货交集列表...")
        symbols = fetch_futures_symbols()
        print(f"       共 {len(symbols)} 个合约交易对")

    if not symbols:
        print("没有找到交易对。")
        return

    # Step 2: 拉K线（30天）
    print(f"[2/4] 从Binance拉取K线数据（{len(symbols)}个交易对，30天）...")
    klines = fetch_klines_batch(symbols, days=30, delay=0.5)
    print(f"       成功获取 {len(klines)} 个交易对的K线")

    # Step 3: 天量回踩检测
    print("[3/4] 天量回踩二攻检测中...")
    matches = []
    for symbol, df in klines.items():
        result = detect_breakout(
            df,
            spike_multiplier=breakout_cfg.get("spike_multiplier", 5.0),
            shrink_threshold=breakout_cfg.get("shrink_threshold", 0.3),
            reattack_multiplier=breakout_cfg.get("reattack_multiplier", 2.0),
            max_pullback_days=breakout_cfg.get("max_pullback_days", 10),
            freshness_days=breakout_cfg.get("freshness_days", 3),
        )
        if not result.matched:
            continue
        matches.append({
            "symbol": symbol,
            "price": result.reattack_close,
            "drop_pct": 0,
            "volume_ratio": 0,
            "window_days": result.days_since_spike,
            "score": result.score,
            "signal_type": "天量回踩",
            "mode": "breakout",
            "spike_date": result.spike_date,
            "spike_vol_ratio": result.spike_volume_ratio,
            "pullback_low": result.pullback_low,
            "spike_high": result.spike_high,
        })

    print(f"       命中 {len(matches)} 个")

    if not matches:
        print("\n未找到天量回踩二攻模式的币种。")
        return

    # Step 4: 市值过滤
    skip_cap = config.get("skip_market_cap_filter", False)
    if not symbols_override and not skip_cap:
        base_symbols = [m["symbol"].split("/")[0] for m in matches]
        print(f"[4/4] 查询 {len(base_symbols)} 个命中币种的市值...")
        market_caps = fetch_market_caps(base_symbols, page_delay=config.get("page_delay", 30))
        for m in matches:
            base = m["symbol"].split("/")[0]
            m["market_cap_m"] = market_caps.get(base, 0) / 1e6
        before = len(matches)
        matches = [m for m in matches if 0 < m["market_cap_m"] <= max_market_cap / 1e6]
        print(f"       市值过滤: {before} -> {len(matches)} 个 (< ${max_market_cap / 1e6:.0f}M)")
    else:
        print("[4/4] 跳过市值过滤")
        for m in matches:
            m["market_cap_m"] = 0

    if not matches:
        print("\n过滤后没有符合条件的币种。")
        return

    ranked = rank_results(matches, top_n=top_n)

    # 确认层过滤 + 加分
    if signal_config.confirmation:
        confirmed = []
        filtered_names = []
        for m in ranked:
            result = confirm_signal(klines[m["symbol"]], "long", signal_config.confirmation_min_pass)
            if result.passed:
                m["base_score"] = m["score"]
                m["confirm_bonus"] = result.bonus
                m["score"] = round(m["base_score"] + result.bonus, 4)
                confirmed.append(m)
            else:
                filtered_names.append(m["symbol"])
        if filtered_names:
            print(f"[确认] {len(ranked)} -> {len(confirmed)} 个 (过滤: {', '.join(filtered_names[:5])}{'...' if len(filtered_names) > 5 else ''})")
        ranked = confirmed
        ranked.sort(key=lambda x: x["score"], reverse=True)

    if not ranked:
        print("\n确认层过滤后没有剩余信号。")
        return

    # 保存到数据库
    scan_id = save_scan(ranked, mode="breakout")
    print(f"\n[跟踪] 本次扫描ID: {scan_id}，已记录 {len(ranked)} 个币种及价格")

    # 信号过滤
    signals = generate_signals(ranked, signal_config)
    print(f"[信号] 评分≥{signal_config.min_score} 过滤: {len(ranked)} -> {len(signals)} 个")

    if not signals:
        print("\n没有达到信号门槛的币种。")
        return

    # 重算止损止盈（用天量回踩特有的位置）
    for s in signals:
        m = next(r for r in ranked if r["symbol"] == s.symbol)
        s.stop_loss_price = round(m["pullback_low"] * 0.97, 6)
        s.take_profit_price = round(m["spike_high"], 6)

    # 输出表格
    table_data = []
    for i, s in enumerate(signals, 1):
        m = next(r for r in ranked if r["symbol"] == s.symbol)
        table_data.append([
            i,
            s.symbol,
            s.signal_type,
            f"{s.price:.4f}",
            f"{s.score:.2f}",
            f"{m.get('spike_date', '')}",
            f"{m.get('spike_vol_ratio', 0):.0f}x",
            f"{s.entry_price:.4f}",
            f"{s.stop_loss_price:.4f}",
            f"{s.take_profit_price:.4f}",
        ])

    headers = ["排名", "币种", "类型", "价格", "评分", "天量日", "倍数", "入场", "止损", "止盈"]
    print(f"\n找到 {len(signals)} 个交易信号:\n")
    print(tabulate(table_data, headers=headers, tablefmt="simple"))

    # 保存文件
    os.makedirs("results", exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_data = [
        {
            "symbol": s.symbol,
            "signal_type": s.signal_type,
            "price": s.price,
            "score": s.score,
            "spike_date": next(r for r in ranked if r["symbol"] == s.symbol).get("spike_date", ""),
            "spike_vol_ratio": next(r for r in ranked if r["symbol"] == s.symbol).get("spike_vol_ratio", 0),
            "entry_price": s.entry_price,
            "stop_loss_price": s.stop_loss_price,
            "take_profit_price": s.take_profit_price,
        }
        for s in signals
    ]
    json_path = f"results/breakout_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    txt_path = f"results/breakout_{ts}.txt"
    with open(txt_path, "w") as f:
        f.write(f"扫描时间: {ts}\n")
        f.write(f"模式: 天量回踩二攻\n")
        f.write(f"找到 {len(signals)} 个交易信号:\n\n")
        f.write(tabulate(table_data, headers=headers, tablefmt="simple"))
        f.write("\n")
    print(f"结果已保存到 {json_path} 和 {txt_path}")
```

- [ ] **Step 4: 更新 argparse 和 main 路由**

在 `main.py` 的 `main()` 函数中：

a) `--mode` 的 `choices` 列表加上 `"breakout"`：

```python
    parser.add_argument(
        "--mode",
        choices=["accumulation", "divergence", "new", "breakout"],
        default="accumulation",
        help="扫描模式: accumulation=底部蓄力, divergence=MACD背离, new=新币观察清单, breakout=天量回踩",
    )
```

b) 在 `elif args.mode == "divergence":` 之前添加：

```python
    elif args.mode == "breakout":
        run_breakout(config, signal_config, top_n=args.top, symbols_override=args.symbols)
```

- [ ] **Step 5: 运行全量测试**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add config.yaml main.py
git commit -m "feat: add --mode breakout CLI with run_breakout() integration"
```

---

### Task 5: 端到端验证

**Files:**
- 无新增文件

- [ ] **Step 1: 运行 breakout 模式**

Run: `.venv/bin/python main.py --mode breakout`
Expected: 输出命中数和信号表格，含天量日、倍数列

- [ ] **Step 2: 运行 breakout + --no-confirm**

Run: `.venv/bin/python main.py --mode breakout --no-confirm`
Expected: 无 `[确认]` 行，信号数 >= 有确认时

- [ ] **Step 3: 验证其他模式未受影响**

Run: `.venv/bin/python main.py --mode divergence --no-confirm`
Expected: 正常输出，与之前一致

- [ ] **Step 4: 全量测试**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全部通过
