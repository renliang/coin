# 策略自学习优化器实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有扫描器添加三层自学习能力：Optuna 参数优化、LightGBM 信号过滤、反馈闭环，使策略能基于实际收益数据持续自我改进。

**Architecture:** 在 `scanner/optimize/` 下新建 6 个模块，不修改现有 detector/scorer/signal 的核心逻辑。Layer 1 (Optuna) 搜索最优 scorer 权重和 detector 阈值；Layer 2 (LightGBM) 对信号做二次打分；Layer 3 (feedback) 自动追踪信号收益并定期重训练。通过 `main.py` 新增 `--optimize`、`--retrain`、`--optimize-report` 三个 CLI 入口暴露。

**Tech Stack:** Python 3.13, optuna, lightgbm, scikit-learn, 现有 pandas/numpy/sqlite3

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| 创建 | `scanner/optimize/__init__.py` | 包初始化 |
| 创建 | `scanner/optimize/param_optimizer.py` | Optuna 目标函数 + 搜索入口 |
| 创建 | `scanner/optimize/feature_engine.py` | 特征提取（信号 + 确认层 + 市场环境） |
| 创建 | `scanner/optimize/ml_filter.py` | LightGBM 训练 / 推理 / 模型版本管理 |
| 创建 | `scanner/optimize/feedback.py` | signal_outcomes 表 + 收益回填 |
| 创建 | `scanner/optimize/retrain.py` | 定期重训练入口 |
| 创建 | `tests/test_feature_engine.py` | feature_engine 单元测试 |
| 创建 | `tests/test_param_optimizer.py` | param_optimizer 单元测试 |
| 创建 | `tests/test_feedback.py` | feedback 回填单元测试 |
| 创建 | `tests/test_ml_filter.py` | ml_filter 训练/推理单元测试 |
| 创建 | `tests/test_retrain.py` | retrain 集成测试 |
| 修改 | `requirements.txt` | 新增 optuna, lightgbm, scikit-learn |
| 修改 | `main.py` | 新增 --optimize, --retrain, --optimize-report CLI |
| 修改 | `scanner/backtest.py` | BacktestHit 新增 r_squared, max_daily_pct 字段 |

---

### Task 0: BacktestHit 扩展字段

**Files:**
- Modify: `scanner/backtest.py`
- Modify: `tests/test_backtest.py`

`param_optimizer.py` 需要对回测命中用自定义权重重新打分，依赖 `r_squared` 和 `max_daily_pct`。当前 `BacktestHit` 缺少这两个字段。

- [ ] **Step 1: 给 BacktestHit 添加字段**

在 `scanner/backtest.py` 的 `BacktestHit` dataclass 中，`score` 之后追加：

```python
    r_squared: float = 0.0
    max_daily_pct: float = 0.0
```

- [ ] **Step 2: 在 run_backtest 中填充新字段**

在 `scanner/backtest.py` 的 `run_backtest()` 函数中，找到 `all_hits.append(BacktestHit(...))`，追加：

```python
                r_squared=result.r_squared,
                max_daily_pct=result.max_daily_pct,
```

- [ ] **Step 3: 运行现有测试确认无回归**

Run: `.venv/bin/pytest tests/test_backtest.py -v`
Expected: 全部通过（新字段有默认值，不破坏现有代码）

- [ ] **Step 4: Commit**

```bash
git add scanner/backtest.py
git commit -m "feat: add r_squared/max_daily_pct to BacktestHit for optimizer"
```

---

### Task 1: 新增依赖 + 包骨架

**Files:**
- Modify: `requirements.txt`
- Create: `scanner/optimize/__init__.py`

- [ ] **Step 1: 更新 requirements.txt**

在 `requirements.txt` 末尾追加：

```
optuna>=3.6.0
lightgbm>=4.3.0
scikit-learn>=1.4.0
```

- [ ] **Step 2: 创建包目录**

```python
# scanner/optimize/__init__.py
"""策略自学习优化器：参数搜索、ML 信号过滤、反馈闭环。"""
```

- [ ] **Step 3: 安装依赖**

Run: `.venv/bin/pip install -r requirements.txt`
Expected: Successfully installed optuna, lightgbm, scikit-learn

- [ ] **Step 4: 验证导入**

Run: `.venv/bin/python -c "import optuna; import lightgbm; import sklearn; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt scanner/optimize/__init__.py
git commit -m "chore: add optuna/lightgbm/sklearn deps, create optimize package"
```

---

### Task 2: feature_engine — 特征提取

**Files:**
- Create: `scanner/optimize/feature_engine.py`
- Create: `tests/test_feature_engine.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_feature_engine.py
import numpy as np
import pandas as pd
import pytest

from scanner.optimize.feature_engine import extract_features, FEATURE_NAMES


def _make_df(n: int = 60) -> pd.DataFrame:
    """生成合成K线数据。"""
    rng = np.random.default_rng(42)
    closes = 100.0 + np.cumsum(rng.normal(0, 1, n))
    closes = np.maximum(closes, 10.0)
    highs = closes * (1 + rng.uniform(0, 0.03, n))
    lows = closes * (1 - rng.uniform(0, 0.03, n))
    volumes = rng.uniform(1e6, 5e6, n)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": closes * (1 + rng.normal(0, 0.01, n)),
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def _make_btc_df(n: int = 60) -> pd.DataFrame:
    """生成BTC合成K线。"""
    rng = np.random.default_rng(99)
    closes = 60000.0 + np.cumsum(rng.normal(0, 200, n))
    closes = np.maximum(closes, 30000.0)
    highs = closes * 1.02
    lows = closes * 0.98
    volumes = rng.uniform(1e9, 5e9, n)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


class TestExtractFeatures:
    def test_returns_correct_length(self):
        df = _make_df()
        btc_df = _make_btc_df()
        match_dict = {
            "symbol": "TEST/USDT",
            "score": 0.75,
            "volume_ratio": 0.35,
            "drop_pct": 0.10,
            "r_squared": 0.85,
            "max_daily_pct": 0.02,
            "window_days": 14,
        }
        features = extract_features(match_dict, df, btc_df)
        assert len(features) == len(FEATURE_NAMES)

    def test_no_nan_in_output(self):
        df = _make_df()
        btc_df = _make_btc_df()
        match_dict = {
            "symbol": "TEST/USDT",
            "score": 0.75,
            "volume_ratio": 0.35,
            "drop_pct": 0.10,
            "r_squared": 0.85,
            "max_daily_pct": 0.02,
            "window_days": 14,
        }
        features = extract_features(match_dict, df, btc_df)
        assert all(not np.isnan(v) for v in features)

    def test_feature_names_match(self):
        assert "btc_return_7d" in FEATURE_NAMES
        assert "volume_ratio" in FEATURE_NAMES
        assert "confirmation_score" in FEATURE_NAMES
        assert len(FEATURE_NAMES) == 16

    def test_btc_none_fills_zero(self):
        df = _make_df()
        match_dict = {
            "symbol": "TEST/USDT",
            "score": 0.75,
            "volume_ratio": 0.35,
            "drop_pct": 0.10,
            "r_squared": 0.85,
            "max_daily_pct": 0.02,
            "window_days": 14,
        }
        features = extract_features(match_dict, df, btc_df=None)
        assert all(not np.isnan(v) for v in features)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_feature_engine.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 实现 feature_engine.py**

```python
# scanner/optimize/feature_engine.py
"""特征提取：信号特征 + 确认层指标 + 市场环境。"""

import numpy as np
import pandas as pd

from scanner.confirmation import (
    compute_rsi,
    compute_obv_trend,
    compute_mfi,
    compute_volume_surge,
    compute_atr_accel,
    compute_price_momentum,
)

FEATURE_NAMES: list[str] = [
    # 信号特征 (6)
    "volume_ratio",
    "drop_pct",
    "r_squared",
    "max_daily_pct",
    "window_days",
    "score",
    # 确认层特征 (7)
    "rsi",
    "obv_7d",
    "mfi",
    "volume_surge",
    "atr_accel",
    "momentum_5d",
    "confirmation_score",
    # 市场环境 (3)
    "btc_return_7d",
    "btc_volatility_14d",
    "total_market_volume_change",
]


def _safe_float(v: float) -> float:
    """将 NaN/inf 转为 0.0。"""
    if v is None or np.isnan(v) or np.isinf(v):
        return 0.0
    return float(v)


def _compute_confirmation_features(df: pd.DataFrame) -> dict[str, float]:
    """从 K 线 DataFrame 提取确认层原始指标值。"""
    closes = df["close"].astype(float)
    highs = df["high"].astype(float)
    lows = df["low"].astype(float)
    volumes = df["volume"].astype(float)

    rsi = compute_rsi(closes, period=14)
    obv_7d = compute_obv_trend(closes, volumes, days=7)
    mfi = compute_mfi(highs, lows, closes, volumes, period=14)
    surge = compute_volume_surge(volumes, recent_days=3, baseline_days=7)
    accel = compute_atr_accel(highs, lows, closes, recent_days=7, baseline_days=14)
    momentum = compute_price_momentum(closes, days=5)

    # 简化版 confirmation_score（7 项均分，不做方向判断）
    rsi_score = max(0.0, 1.0 - abs(rsi - 50) / 50)
    mfi_score = max(0.0, 1.0 - abs(mfi - 50) / 50)
    surge_score = min(1.0, max(0.0, (surge - 1.0) / 1.0))
    accel_score = min(1.0, max(0.0, (accel - 1.0) / 0.5))
    momentum_score = min(1.0, max(0.0, (momentum + 0.10) / 0.20))
    conf_score = (rsi_score + mfi_score + surge_score + accel_score + momentum_score) / 5.0

    return {
        "rsi": rsi,
        "obv_7d": obv_7d,
        "mfi": mfi,
        "volume_surge": surge,
        "atr_accel": accel,
        "momentum_5d": momentum,
        "confirmation_score": conf_score,
    }


def _compute_btc_features(btc_df: pd.DataFrame | None) -> dict[str, float]:
    """从 BTC K 线提取市场环境特征。btc_df 为 None 时返回全 0。"""
    if btc_df is None or len(btc_df) < 15:
        return {"btc_return_7d": 0.0, "btc_volatility_14d": 0.0}
    closes = btc_df["close"].astype(float)
    btc_return_7d = (closes.iloc[-1] - closes.iloc[-8]) / closes.iloc[-8] if len(closes) >= 8 else 0.0
    recent_14 = closes.iloc[-14:]
    btc_volatility_14d = float(recent_14.std() / recent_14.mean()) if len(recent_14) >= 14 else 0.0
    return {
        "btc_return_7d": btc_return_7d,
        "btc_volatility_14d": btc_volatility_14d,
    }


def extract_features(
    match_dict: dict,
    df: pd.DataFrame,
    btc_df: pd.DataFrame | None = None,
) -> list[float]:
    """提取完整特征向量，顺序与 FEATURE_NAMES 一致。

    Args:
        match_dict: 包含 volume_ratio, drop_pct, r_squared, max_daily_pct, window_days, score 的字典。
        df: 该币种的日 K 线 DataFrame。
        btc_df: BTC 日 K 线 DataFrame（可选，缺失时市场环境特征填 0）。

    Returns:
        长度为 len(FEATURE_NAMES) 的 float 列表。
    """
    # 信号特征
    signal_feats = {
        "volume_ratio": match_dict.get("volume_ratio", 0),
        "drop_pct": match_dict.get("drop_pct", 0),
        "r_squared": match_dict.get("r_squared", 0),
        "max_daily_pct": match_dict.get("max_daily_pct", 0),
        "window_days": match_dict.get("window_days", 0),
        "score": match_dict.get("score", 0),
    }

    # 确认层特征
    conf_feats = _compute_confirmation_features(df)

    # 市场环境
    btc_feats = _compute_btc_features(btc_df)

    # 该币种自身的 volume_surge（作为 total_market_volume_change）
    volumes = df["volume"].astype(float)
    total_market_volume_change = compute_volume_surge(volumes, recent_days=3, baseline_days=7)

    all_feats = {**signal_feats, **conf_feats, **btc_feats, "total_market_volume_change": total_market_volume_change}

    return [_safe_float(all_feats[name]) for name in FEATURE_NAMES]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_feature_engine.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add scanner/optimize/feature_engine.py tests/test_feature_engine.py
git commit -m "feat: add feature_engine for signal/confirmation/market features"
```

---

### Task 3: feedback — 数据库表 + 收益回填

**Files:**
- Create: `scanner/optimize/feedback.py`
- Create: `tests/test_feedback.py`
- Modify: `scanner/tracker.py` (signal_outcomes 表迁移)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_feedback.py
import sqlite3
import json
from datetime import datetime, timedelta

import pytest

from scanner.optimize.feedback import (
    ensure_outcomes_table,
    record_signal_outcome,
    get_pending_outcomes,
    backfill_return,
    get_labeled_outcomes,
)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


class TestSignalOutcomes:
    def test_create_table(self, db_path):
        ensure_outcomes_table(db_path)
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='signal_outcomes'"
        ).fetchall()
        conn.close()
        assert len(tables) == 1

    def test_record_and_query(self, db_path):
        ensure_outcomes_table(db_path)
        record_signal_outcome(
            db_path=db_path,
            scan_result_id=1,
            symbol="BTC/USDT",
            signal_date="2026-04-01",
            signal_price=60000.0,
            features_json=json.dumps({"score": 0.8}),
            btc_price=60000.0,
        )
        pending = get_pending_outcomes(db_path, as_of_date="2026-04-10")
        assert len(pending) >= 1
        assert pending[0]["symbol"] == "BTC/USDT"

    def test_backfill_return(self, db_path):
        ensure_outcomes_table(db_path)
        record_signal_outcome(
            db_path=db_path,
            scan_result_id=1,
            symbol="BTC/USDT",
            signal_date="2026-04-01",
            signal_price=60000.0,
            features_json="{}",
            btc_price=60000.0,
        )
        backfill_return(db_path, outcome_id=1, period="return_3d", value=0.05)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT return_3d FROM signal_outcomes WHERE id=1").fetchone()
        conn.close()
        assert row["return_3d"] == pytest.approx(0.05)

    def test_get_labeled_outcomes(self, db_path):
        ensure_outcomes_table(db_path)
        record_signal_outcome(
            db_path=db_path,
            scan_result_id=1,
            symbol="BTC/USDT",
            signal_date="2026-04-01",
            signal_price=60000.0,
            features_json=json.dumps([0.1] * 16),
            btc_price=60000.0,
        )
        backfill_return(db_path, outcome_id=1, period="return_7d", value=0.03)
        labeled = get_labeled_outcomes(db_path)
        assert len(labeled) == 1
        assert labeled[0]["return_7d"] == pytest.approx(0.03)

    def test_no_duplicate_record(self, db_path):
        ensure_outcomes_table(db_path)
        record_signal_outcome(
            db_path=db_path,
            scan_result_id=1,
            symbol="BTC/USDT",
            signal_date="2026-04-01",
            signal_price=60000.0,
            features_json="{}",
            btc_price=60000.0,
        )
        record_signal_outcome(
            db_path=db_path,
            scan_result_id=1,
            symbol="BTC/USDT",
            signal_date="2026-04-01",
            signal_price=60000.0,
            features_json="{}",
            btc_price=60000.0,
        )
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0]
        conn.close()
        assert count == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_feedback.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 实现 feedback.py**

```python
# scanner/optimize/feedback.py
"""信号结果追踪与收益回填。"""

import json
import sqlite3
from datetime import datetime


_DEFAULT_DB = "scanner.db"


def ensure_outcomes_table(db_path: str = _DEFAULT_DB) -> None:
    """创建 signal_outcomes 表（如不存在）。"""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_result_id INTEGER,
            symbol TEXT NOT NULL,
            signal_date TEXT NOT NULL,
            signal_price REAL NOT NULL,
            return_3d REAL,
            return_7d REAL,
            return_14d REAL,
            return_30d REAL,
            features_json TEXT,
            btc_price REAL,
            collected_at TEXT,
            UNIQUE(scan_result_id, symbol, signal_date)
        )
    """)
    conn.commit()
    conn.close()


def record_signal_outcome(
    db_path: str = _DEFAULT_DB,
    scan_result_id: int | None = None,
    symbol: str = "",
    signal_date: str = "",
    signal_price: float = 0.0,
    features_json: str = "{}",
    btc_price: float = 0.0,
) -> int | None:
    """插入一条信号追踪记录。如果已存在（scan_result_id+symbol+signal_date 去重）则跳过。

    Returns:
        新插入行的 id，重复时返回 None。
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO signal_outcomes
               (scan_result_id, symbol, signal_date, signal_price, features_json, btc_price)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (scan_result_id, symbol, signal_date, signal_price, features_json, btc_price),
        )
        conn.commit()
        return cur.lastrowid if cur.rowcount > 0 else None
    finally:
        conn.close()


def get_pending_outcomes(
    db_path: str = _DEFAULT_DB,
    as_of_date: str | None = None,
) -> list[dict]:
    """获取有 return 列为 NULL 且已到期的记录。

    到期判断：signal_date + 3d/7d/14d/30d <= as_of_date。
    返回所有至少有一个周期到期但尚未回填的记录。
    """
    if as_of_date is None:
        as_of_date = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT * FROM signal_outcomes
           WHERE (return_3d IS NULL OR return_7d IS NULL
                  OR return_14d IS NULL OR return_30d IS NULL)
             AND date(signal_date, '+3 days') <= date(?)
           ORDER BY signal_date""",
        (as_of_date,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def backfill_return(
    db_path: str = _DEFAULT_DB,
    outcome_id: int = 0,
    period: str = "return_7d",
    value: float = 0.0,
) -> None:
    """回填单条记录的单个周期收益率。"""
    if period not in ("return_3d", "return_7d", "return_14d", "return_30d"):
        raise ValueError(f"Invalid period: {period}")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"UPDATE signal_outcomes SET {period} = ?, collected_at = ? WHERE id = ?",
        (value, now, outcome_id),
    )
    conn.commit()
    conn.close()


def get_labeled_outcomes(
    db_path: str = _DEFAULT_DB,
) -> list[dict]:
    """获取所有 return_7d 非 NULL 的记录（可用于训练）。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM signal_outcomes WHERE return_7d IS NOT NULL ORDER BY signal_date",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_feedback.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add scanner/optimize/feedback.py tests/test_feedback.py
git commit -m "feat: add feedback module for signal outcome tracking and backfill"
```

---

### Task 4: param_optimizer — Optuna 参数搜索

**Files:**
- Create: `scanner/optimize/param_optimizer.py`
- Create: `tests/test_param_optimizer.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_param_optimizer.py
import numpy as np
import pandas as pd
import pytest

from scanner.optimize.param_optimizer import (
    score_with_weights,
    objective_from_hits,
    optimize_params,
    OptimizedParams,
)
from scanner.backtest import BacktestHit


def _make_hits(n: int = 30) -> list[BacktestHit]:
    """生成合成回测命中数据。"""
    rng = np.random.default_rng(42)
    hits = []
    for i in range(n):
        hits.append(BacktestHit(
            symbol=f"COIN{i}/USDT",
            detect_date=f"2026-{1 + i // 30:02d}-{1 + i % 28:02d}",
            window_days=int(rng.integers(7, 15)),
            drop_pct=float(rng.uniform(0.05, 0.15)),
            volume_ratio=float(rng.uniform(0.2, 0.8)),
            score=float(rng.uniform(0.3, 0.9)),
            returns={
                "3d": float(rng.normal(0, 0.05)),
                "7d": float(rng.normal(0.01, 0.05)),
                "14d": float(rng.normal(0, 0.08)),
                "30d": float(rng.normal(0, 0.10)),
            },
        ))
    return hits


class TestScoreWithWeights:
    def test_weights_normalized(self):
        score = score_with_weights(
            volume_ratio=0.3,
            drop_pct=0.10,
            r_squared=0.9,
            max_daily_pct=0.02,
            w_volume=0.5,
            w_drop=0.5,
            w_trend=0.5,
            w_slow=0.5,
            drop_min=0.05,
            drop_max=0.15,
            max_daily_change=0.05,
        )
        assert 0.0 <= score <= 1.0

    def test_higher_quality_higher_score(self):
        good = score_with_weights(
            volume_ratio=0.2, drop_pct=0.10, r_squared=0.95, max_daily_pct=0.01,
            w_volume=0.3, w_drop=0.25, w_trend=0.25, w_slow=0.2,
            drop_min=0.05, drop_max=0.15, max_daily_change=0.05,
        )
        bad = score_with_weights(
            volume_ratio=0.48, drop_pct=0.14, r_squared=0.3, max_daily_pct=0.045,
            w_volume=0.3, w_drop=0.25, w_trend=0.25, w_slow=0.2,
            drop_min=0.05, drop_max=0.15, max_daily_change=0.05,
        )
        assert good > bad


class TestObjectiveFromHits:
    def test_returns_float(self):
        hits = _make_hits(30)
        val = objective_from_hits(
            hits, min_score=0.5,
            w_volume=0.3, w_drop=0.25, w_trend=0.25, w_slow=0.2,
            drop_min=0.05, drop_max=0.15, max_daily_change=0.05,
        )
        assert isinstance(val, float)

    def test_penalty_on_few_samples(self):
        hits = _make_hits(3)
        val = objective_from_hits(
            hits, min_score=0.99,
            w_volume=0.3, w_drop=0.25, w_trend=0.25, w_slow=0.2,
            drop_min=0.05, drop_max=0.15, max_daily_change=0.05,
        )
        assert val < -0.5


class TestOptimizeParams:
    def test_returns_optimized_params(self):
        hits = _make_hits(50)
        result = optimize_params(hits, n_trials=5)
        assert isinstance(result, OptimizedParams)
        assert 0.0 < result.w_volume < 1.0
        assert 0.0 < result.min_score < 1.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_param_optimizer.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 实现 param_optimizer.py**

```python
# scanner/optimize/param_optimizer.py
"""Optuna 贝叶斯参数搜索，优化 scorer 权重和 detector 阈值。"""

from dataclasses import dataclass

import numpy as np
import optuna

from scanner.backtest import BacktestHit, split_hits_by_median_date


optuna.logging.set_verbosity(optuna.logging.WARNING)


@dataclass
class OptimizedParams:
    """优化后的参数集。"""
    w_volume: float
    w_drop: float
    w_trend: float
    w_slow: float
    drop_min: float
    drop_max: float
    max_daily_change: float
    volume_ratio: float
    min_score: float
    confirmation_min_pass: int
    objective_value: float
    validation_win_rate: float
    validation_mean_return: float


def score_with_weights(
    volume_ratio: float,
    drop_pct: float,
    r_squared: float,
    max_daily_pct: float,
    w_volume: float,
    w_drop: float,
    w_trend: float,
    w_slow: float,
    drop_min: float = 0.05,
    drop_max: float = 0.15,
    max_daily_change: float = 0.05,
) -> float:
    """用自定义权重计算评分（归一化权重）。"""
    total = w_volume + w_drop + w_trend + w_slow
    if total == 0:
        return 0.0
    w_v, w_d, w_t, w_s = w_volume / total, w_drop / total, w_trend / total, w_slow / total

    vol_score = max(0.0, min(1.0, 1.0 - volume_ratio))
    mid = (drop_min + drop_max) / 2
    half_range = (drop_max - drop_min) / 2
    drop_score = max(0.0, 1.0 - abs(drop_pct - mid) / half_range) if half_range > 0 else 0.0
    trend_score = max(0.0, min(1.0, r_squared))
    slow_score = max(0.0, min(1.0, 1.0 - max_daily_pct / max_daily_change)) if max_daily_change > 0 else 0.0

    return vol_score * w_v + drop_score * w_d + trend_score * w_t + slow_score * w_s


def objective_from_hits(
    hits: list[BacktestHit],
    min_score: float,
    w_volume: float,
    w_drop: float,
    w_trend: float,
    w_slow: float,
    drop_min: float = 0.05,
    drop_max: float = 0.15,
    max_daily_change: float = 0.05,
    min_samples: int = 10,
) -> float:
    """计算目标函数值：win_rate_7d × mean_return_7d。

    对 hits 重新用给定权重打分，筛选 score >= min_score 的子集。
    样本不足返回 -1.0 惩罚。
    """
    scored = []
    for h in hits:
        new_score = score_with_weights(
            h.volume_ratio, h.drop_pct, h.r_squared, h.max_daily_pct,
            w_volume, w_drop, w_trend, w_slow,
            drop_min, drop_max, max_daily_change,
        )
        if new_score >= min_score and h.returns.get("7d") is not None:
            scored.append(h.returns["7d"])

    if len(scored) < min_samples:
        return -1.0

    arr = np.array(scored)
    win_rate = float(np.mean(arr > 0))
    mean_ret = float(np.mean(arr))
    return win_rate * mean_ret


def optimize_params(
    hits: list[BacktestHit],
    n_trials: int = 200,
    overfit_penalty: float = 0.15,
) -> OptimizedParams:
    """运行 Optuna 搜索最优参数。

    Args:
        hits: 回测命中列表（含 returns）。
        n_trials: 搜索次数。
        overfit_penalty: 前后半段胜率差超过此值则惩罚。

    Returns:
        OptimizedParams 包含最优参数和验证结果。
    """
    early_hits, late_hits = split_hits_by_median_date(hits)

    def _objective(trial: optuna.Trial) -> float:
        w_volume = trial.suggest_float("w_volume", 0.05, 0.6)
        w_drop = trial.suggest_float("w_drop", 0.05, 0.6)
        w_trend = trial.suggest_float("w_trend", 0.05, 0.6)
        w_slow = trial.suggest_float("w_slow", 0.05, 0.6)
        drop_min = trial.suggest_float("drop_min", 0.02, 0.08)
        drop_max = trial.suggest_float("drop_max", 0.10, 0.25)
        max_daily_change = trial.suggest_float("max_daily_change", 0.03, 0.08)
        volume_ratio = trial.suggest_float("volume_ratio", 0.25, 0.75)
        min_score = trial.suggest_float("min_score", 0.5, 0.95)

        # 前半段优化
        train_val = objective_from_hits(
            early_hits, min_score,
            w_volume, w_drop, w_trend, w_slow,
            drop_min, drop_max, max_daily_change,
        )
        if train_val <= -1.0:
            return -1.0

        # 后半段验证（防过拟合）
        if late_hits:
            val_val = objective_from_hits(
                late_hits, min_score,
                w_volume, w_drop, w_trend, w_slow,
                drop_min, drop_max, max_daily_change,
            )
            if val_val <= -1.0:
                return train_val * 0.5  # 验证集样本不足，降权

            # 计算前后半段胜率差异
            def _win_rate(subset, ms):
                scored = []
                for h in subset:
                    s = score_with_weights(
                        h.volume_ratio, h.drop_pct, h.r_squared, h.max_daily_pct,
                        w_volume, w_drop, w_trend, w_slow,
                        drop_min, drop_max, max_daily_change,
                    )
                    if s >= ms and h.returns.get("7d") is not None:
                        scored.append(h.returns["7d"])
                if not scored:
                    return 0.0
                return float(np.mean(np.array(scored) > 0))

            early_wr = _win_rate(early_hits, min_score)
            late_wr = _win_rate(late_hits, min_score)
            if early_wr - late_wr > overfit_penalty:
                return train_val * 0.3  # 过拟合惩罚

            return (train_val + val_val) / 2

        return train_val

    study = optuna.create_study(direction="maximize")
    study.optimize(_objective, n_trials=n_trials)

    best = study.best_params
    total_w = best["w_volume"] + best["w_drop"] + best["w_trend"] + best["w_slow"]

    # 计算验证集统计
    val_scored = []
    for h in (late_hits or hits):
        s = score_with_weights(
            h.volume_ratio, h.drop_pct, h.r_squared, h.max_daily_pct,
            best["w_volume"], best["w_drop"], best["w_trend"], best["w_slow"],
            best["drop_min"], best["drop_max"], best["max_daily_change"],
        )
        if s >= best["min_score"] and h.returns.get("7d") is not None:
            val_scored.append(h.returns["7d"])

    val_arr = np.array(val_scored) if val_scored else np.array([0.0])

    return OptimizedParams(
        w_volume=best["w_volume"] / total_w,
        w_drop=best["w_drop"] / total_w,
        w_trend=best["w_trend"] / total_w,
        w_slow=best["w_slow"] / total_w,
        drop_min=best["drop_min"],
        drop_max=best["drop_max"],
        max_daily_change=best["max_daily_change"],
        volume_ratio=best["volume_ratio"],
        min_score=best["min_score"],
        confirmation_min_pass=4,
        objective_value=study.best_value,
        validation_win_rate=float(np.mean(val_arr > 0)),
        validation_mean_return=float(np.mean(val_arr)),
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_param_optimizer.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add scanner/optimize/param_optimizer.py tests/test_param_optimizer.py
git commit -m "feat: add Optuna param optimizer with overfitting protection"
```

---

### Task 5: ml_filter — LightGBM 训练与推理

**Files:**
- Create: `scanner/optimize/ml_filter.py`
- Create: `tests/test_ml_filter.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_ml_filter.py
import json
import numpy as np
import pytest

from scanner.optimize.ml_filter import (
    train_model,
    predict_proba,
    compute_final_score,
    save_model,
    load_model,
    ModelInfo,
    MIN_TRAINING_SAMPLES,
)
from scanner.optimize.feature_engine import FEATURE_NAMES


def _make_training_data(n: int = 150) -> tuple[list[list[float]], list[int]]:
    """生成合成训练数据。"""
    rng = np.random.default_rng(42)
    X = []
    y = []
    for _ in range(n):
        features = [float(rng.uniform(0, 1)) for _ in FEATURE_NAMES]
        # 简单规则：score > 0.5 且 rsi 接近 50 → 正样本概率高
        label = 1 if features[5] > 0.5 and abs(features[6] - 50) < 20 else 0
        # 加噪声
        if rng.random() < 0.2:
            label = 1 - label
        X.append(features)
        y.append(label)
    return X, y


class TestTrainModel:
    def test_train_returns_model_info(self):
        X, y = _make_training_data(150)
        info = train_model(X, y)
        assert isinstance(info, ModelInfo)
        assert info.model is not None
        assert 0.0 <= info.validation_accuracy <= 1.0

    def test_train_insufficient_data(self):
        X, y = _make_training_data(20)
        X, y = X[:20], y[:20]
        info = train_model(X, y)
        assert info.model is None


class TestPredictProba:
    def test_predict_returns_probability(self):
        X, y = _make_training_data(150)
        info = train_model(X, y)
        proba = predict_proba(info.model, X[0])
        assert 0.0 <= proba <= 1.0

    def test_predict_none_model_returns_half(self):
        proba = predict_proba(None, [0.0] * len(FEATURE_NAMES))
        assert proba == 0.5


class TestComputeFinalScore:
    def test_weighted_combination(self):
        final = compute_final_score(original_score=0.8, ml_proba=0.9)
        expected = 0.4 * 0.8 + 0.6 * 0.9
        assert final == pytest.approx(expected)

    def test_no_ml_returns_original(self):
        final = compute_final_score(original_score=0.8, ml_proba=None)
        assert final == 0.8


class TestSaveLoadModel:
    def test_roundtrip(self, tmp_path):
        X, y = _make_training_data(150)
        info = train_model(X, y)
        path = save_model(info, str(tmp_path))
        loaded = load_model(path)
        assert loaded.model is not None
        # 预测结果一致
        original_pred = predict_proba(info.model, X[0])
        loaded_pred = predict_proba(loaded.model, X[0])
        assert original_pred == pytest.approx(loaded_pred)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_ml_filter.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 实现 ml_filter.py**

```python
# scanner/optimize/ml_filter.py
"""LightGBM 信号过滤器：训练、推理、模型版本管理。"""

import os
import pickle
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from scanner.optimize.feature_engine import FEATURE_NAMES


MIN_TRAINING_SAMPLES = 100


@dataclass
class ModelInfo:
    """训练后的模型元数据。"""
    model: object | None  # lightgbm.Booster or None
    trained_at: str
    sample_count: int
    validation_accuracy: float
    feature_names: list[str]


def train_model(
    X: list[list[float]],
    y: list[int],
    test_ratio: float = 0.2,
) -> ModelInfo:
    """训练 LightGBM 二分类模型。

    Args:
        X: 特征矩阵，每行长度 = len(FEATURE_NAMES)。
        y: 标签 (0/1)。
        test_ratio: 用于验证的尾部数据比例（时间序列分割）。

    Returns:
        ModelInfo，样本不足时 model=None。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if len(X) < MIN_TRAINING_SAMPLES:
        return ModelInfo(
            model=None, trained_at=now,
            sample_count=len(X), validation_accuracy=0.0,
            feature_names=list(FEATURE_NAMES),
        )

    import lightgbm as lgb

    arr_X = np.array(X, dtype=np.float64)
    arr_y = np.array(y, dtype=np.int32)

    # 时间序列分割：尾部做验证
    split_idx = int(len(arr_X) * (1 - test_ratio))
    X_train, X_val = arr_X[:split_idx], arr_X[split_idx:]
    y_train, y_val = arr_y[:split_idx], arr_y[split_idx:]

    train_data = lgb.Dataset(X_train, label=y_train, feature_name=list(FEATURE_NAMES))
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
    }

    model = lgb.train(
        params, train_data,
        num_boost_round=200,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(20, verbose=False)],
    )

    # 验证准确率
    val_pred = model.predict(X_val)
    val_labels = (np.array(val_pred) > 0.5).astype(int)
    accuracy = float(np.mean(val_labels == y_val))

    return ModelInfo(
        model=model, trained_at=now,
        sample_count=len(X), validation_accuracy=accuracy,
        feature_names=list(FEATURE_NAMES),
    )


def predict_proba(model: object | None, features: list[float]) -> float:
    """用模型预测正样本概率。model 为 None 时返回 0.5（中性）。"""
    if model is None:
        return 0.5
    arr = np.array([features], dtype=np.float64)
    pred = model.predict(arr)
    return float(pred[0])


def compute_final_score(
    original_score: float,
    ml_proba: float | None,
    original_weight: float = 0.4,
    ml_weight: float = 0.6,
) -> float:
    """计算最终评分 = original_weight × 原始score + ml_weight × ml_proba。

    ml_proba 为 None 时直接返回 original_score。
    """
    if ml_proba is None:
        return original_score
    return original_weight * original_score + ml_weight * ml_proba


def save_model(info: ModelInfo, models_dir: str = "scanner/optimize/models") -> str:
    """保存模型到磁盘，返回文件路径。"""
    os.makedirs(models_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(models_dir, f"lgbm_{ts}.pkl")
    with open(path, "wb") as f:
        pickle.dump(info, f)
    return path


def load_model(path: str) -> ModelInfo:
    """从磁盘加载模型。"""
    with open(path, "rb") as f:
        return pickle.load(f)


def load_latest_model(models_dir: str = "scanner/optimize/models") -> ModelInfo | None:
    """加载最新的模型文件。目录为空返回 None。"""
    if not os.path.isdir(models_dir):
        return None
    files = sorted(
        [f for f in os.listdir(models_dir) if f.startswith("lgbm_") and f.endswith(".pkl")],
        reverse=True,
    )
    if not files:
        return None
    return load_model(os.path.join(models_dir, files[0]))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_ml_filter.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add scanner/optimize/ml_filter.py tests/test_ml_filter.py
git commit -m "feat: add LightGBM signal filter with train/predict/save/load"
```

---

### Task 6: retrain — 重训练入口

**Files:**
- Create: `scanner/optimize/retrain.py`
- Create: `tests/test_retrain.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_retrain.py
import json
import sqlite3

import numpy as np
import pytest

from scanner.optimize.feedback import ensure_outcomes_table, record_signal_outcome, backfill_return
from scanner.optimize.retrain import run_retrain, RetrainReport
from scanner.optimize.feature_engine import FEATURE_NAMES


@pytest.fixture
def db_with_data(tmp_path):
    """创建带有 120 条已标注数据的测试数据库。"""
    db_path = str(tmp_path / "test.db")
    ensure_outcomes_table(db_path)
    rng = np.random.default_rng(42)
    for i in range(120):
        features = [float(rng.uniform(0, 1)) for _ in FEATURE_NAMES]
        record_signal_outcome(
            db_path=db_path,
            scan_result_id=i,
            symbol=f"COIN{i}/USDT",
            signal_date=f"2026-{1 + i // 30:02d}-{1 + i % 28:02d}",
            signal_price=float(rng.uniform(0.01, 100)),
            features_json=json.dumps(features),
            btc_price=60000.0,
        )
        ret = float(rng.normal(0.01, 0.05))
        backfill_return(db_path, outcome_id=i + 1, period="return_7d", value=ret)
    return db_path


class TestRetrain:
    def test_retrain_produces_report(self, db_with_data, tmp_path):
        report = run_retrain(
            db_path=db_with_data,
            models_dir=str(tmp_path / "models"),
            results_dir=str(tmp_path / "results"),
        )
        assert isinstance(report, RetrainReport)
        assert report.samples_used >= 100
        assert report.model_path is not None

    def test_retrain_insufficient_data(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        ensure_outcomes_table(db_path)
        report = run_retrain(
            db_path=db_path,
            models_dir=str(tmp_path / "models"),
            results_dir=str(tmp_path / "results"),
        )
        assert report.model_path is None
        assert report.samples_used == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/test_retrain.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 实现 retrain.py**

```python
# scanner/optimize/retrain.py
"""定期重训练入口：收集 label → 训练 LightGBM → 比较新旧模型 → 输出报告。"""

import json
import os
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from scanner.optimize.feedback import get_labeled_outcomes
from scanner.optimize.feature_engine import FEATURE_NAMES
from scanner.optimize.ml_filter import (
    train_model,
    predict_proba,
    save_model,
    load_latest_model,
    MIN_TRAINING_SAMPLES,
)


@dataclass
class RetrainReport:
    """重训练报告。"""
    timestamp: str
    samples_used: int
    model_path: str | None
    new_accuracy: float
    old_accuracy: float | None
    improved: bool
    report_path: str | None


def run_retrain(
    db_path: str = "scanner.db",
    models_dir: str = "scanner/optimize/models",
    results_dir: str = "results",
) -> RetrainReport:
    """执行一次重训练流程。

    1. 从 signal_outcomes 加载已标注数据
    2. 样本 >= MIN_TRAINING_SAMPLES 时训练新模型
    3. 与旧模型比较验证准确率，提升才替换
    4. 输出报告 JSON
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    labeled = get_labeled_outcomes(db_path)

    if len(labeled) < MIN_TRAINING_SAMPLES:
        return RetrainReport(
            timestamp=now, samples_used=len(labeled),
            model_path=None, new_accuracy=0.0,
            old_accuracy=None, improved=False, report_path=None,
        )

    # 构建 X, y
    X = []
    y = []
    for row in labeled:
        try:
            features = json.loads(row["features_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(features, list) or len(features) != len(FEATURE_NAMES):
            continue
        X.append([float(v) for v in features])
        y.append(1 if row["return_7d"] > 0 else 0)

    if len(X) < MIN_TRAINING_SAMPLES:
        return RetrainReport(
            timestamp=now, samples_used=len(X),
            model_path=None, new_accuracy=0.0,
            old_accuracy=None, improved=False, report_path=None,
        )

    # 训练新模型
    new_info = train_model(X, y)

    # 加载旧模型比较
    old_info = load_latest_model(models_dir)
    old_accuracy = old_info.validation_accuracy if old_info else None

    improved = True
    if old_accuracy is not None and new_info.validation_accuracy <= old_accuracy:
        improved = False

    # 只在改进时保存
    model_path = None
    if improved and new_info.model is not None:
        model_path = save_model(new_info, models_dir)

    # 保存报告
    os.makedirs(results_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d")
    report_path = os.path.join(results_dir, f"retrain_{ts}.json")
    report_data = {
        "timestamp": now,
        "samples_used": len(X),
        "new_accuracy": new_info.validation_accuracy,
        "old_accuracy": old_accuracy,
        "improved": improved,
        "model_path": model_path,
    }
    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=2)

    return RetrainReport(
        timestamp=now,
        samples_used=len(X),
        model_path=model_path,
        new_accuracy=new_info.validation_accuracy,
        old_accuracy=old_accuracy,
        improved=improved,
        report_path=report_path,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/test_retrain.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add scanner/optimize/retrain.py tests/test_retrain.py
git commit -m "feat: add retrain module with model comparison and report"
```

---

### Task 7: CLI 集成 — main.py 新增三个命令

**Files:**
- Modify: `main.py`

- [ ] **Step 1: 在 main() 的 argparse 中新增三个参数**

在 `main.py` 的 `main()` 函数中，找到现有的 `parser.add_argument` 块，在 `--json-only` 之后追加：

```python
    parser.add_argument(
        "--optimize",
        action="store_true",
        help="运行 Optuna 参数优化（需先有回测数据）",
    )
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="收集信号反馈 + 重训练 ML 模型",
    )
    parser.add_argument(
        "--optimize-report",
        action="store_true",
        help="查看当前最优参数和模型表现",
    )
```

- [ ] **Step 2: 在 main() 的分支逻辑中添加处理**

在 `main()` 函数的 `if args.serve:` 分支之前插入：

```python
    if args.optimize:
        run_optimize_cli(config, signal_config, days=args.days, symbols_override=args.symbols)
        return
    if args.retrain:
        run_retrain_cli()
        return
    if args.optimize_report:
        run_optimize_report_cli()
        return
```

- [ ] **Step 3: 实现三个 CLI 函数**

在 `main.py` 中 `def main():` 之前添加：

```python
def run_optimize_cli(
    config: dict,
    signal_config: SignalConfig,
    days: int = 180,
    symbols_override: list[str] | None = None,
):
    """运行 Optuna 参数优化。"""
    from scanner.backtest import run_backtest, compute_stats, format_stats
    from scanner.optimize.param_optimizer import optimize_params

    symbols = symbols_override or fetch_futures_symbols()
    print(f"获取 {len(symbols)} 个合约币种的K线（{days}天）...")
    klines = fetch_klines_batch(symbols, days=days)
    print(f"成功获取 {len(klines)} 个币种")

    use_confirm = signal_config.confirmation
    min_pass = signal_config.confirmation_min_pass

    print("运行回测...")
    hits = run_backtest(klines, config, confirmation=use_confirm, confirmation_min_pass=min_pass)
    print(f"总命中: {len(hits)}")

    if len(hits) < 20:
        print("命中数太少，无法优化。请增加 --days 或放宽参数。")
        return

    print(f"开始 Optuna 搜索（200 trials）...")
    result = optimize_params(hits, n_trials=200)

    print("\n=== 优化结果 ===")
    print(f"目标函数值: {result.objective_value:.6f}")
    print(f"验证集胜率: {result.validation_win_rate:.1%}")
    print(f"验证集均值收益: {result.validation_mean_return:.2%}")
    print(f"\n最优权重:")
    print(f"  volume: {result.w_volume:.3f}")
    print(f"  drop:   {result.w_drop:.3f}")
    print(f"  trend:  {result.w_trend:.3f}")
    print(f"  slow:   {result.w_slow:.3f}")
    print(f"\n最优阈值:")
    print(f"  drop_min: {result.drop_min:.4f}")
    print(f"  drop_max: {result.drop_max:.4f}")
    print(f"  max_daily_change: {result.max_daily_change:.4f}")
    print(f"  volume_ratio: {result.volume_ratio:.4f}")
    print(f"  min_score: {result.min_score:.4f}")

    # 写入 config.yaml
    import yaml
    with open("config.yaml") as f:
        raw = yaml.safe_load(f)
    raw["optimized"] = {
        "scorer_weights": {
            "volume": round(result.w_volume, 4),
            "drop": round(result.w_drop, 4),
            "trend": round(result.w_trend, 4),
            "slow": round(result.w_slow, 4),
        },
        "scanner": {
            "drop_min": round(result.drop_min, 4),
            "drop_max": round(result.drop_max, 4),
            "max_daily_change": round(result.max_daily_change, 4),
            "volume_ratio": round(result.volume_ratio, 4),
        },
        "signal": {
            "min_score": round(result.min_score, 4),
        },
        "validation": {
            "win_rate_7d": round(result.validation_win_rate, 4),
            "mean_return_7d": round(result.validation_mean_return, 4),
            "objective": round(result.objective_value, 6),
        },
    }
    with open("config.yaml", "w") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True)
    print("\n已将优化结果写入 config.yaml 的 optimized 段。")


def run_retrain_cli():
    """收集信号反馈 + 重训练 ML 模型。"""
    from scanner.optimize.feedback import ensure_outcomes_table
    from scanner.optimize.retrain import run_retrain

    ensure_outcomes_table()
    print("开始重训练...")
    report = run_retrain()

    print(f"\n=== 重训练报告 ===")
    print(f"样本数: {report.samples_used}")
    if report.model_path:
        print(f"新模型准确率: {report.new_accuracy:.1%}")
        if report.old_accuracy is not None:
            print(f"旧模型准确率: {report.old_accuracy:.1%}")
        print(f"{'已替换旧模型' if report.improved else '保留旧模型（新模型未改进）'}")
        print(f"模型路径: {report.model_path}")
    else:
        print(f"样本不足（需 ≥100），跳过训练。")
    if report.report_path:
        print(f"报告: {report.report_path}")


def run_optimize_report_cli():
    """查看当前最优参数和模型表现。"""
    import yaml
    from scanner.optimize.ml_filter import load_latest_model

    with open("config.yaml") as f:
        raw = yaml.safe_load(f)

    opt = raw.get("optimized")
    if opt:
        print("=== 当前优化参数 ===")
        weights = opt.get("scorer_weights", {})
        print(f"Scorer 权重: volume={weights.get('volume')}, drop={weights.get('drop')}, "
              f"trend={weights.get('trend')}, slow={weights.get('slow')}")
        scanner = opt.get("scanner", {})
        print(f"Detector 阈值: drop=[{scanner.get('drop_min')}, {scanner.get('drop_max')}], "
              f"daily_change={scanner.get('max_daily_change')}, vol_ratio={scanner.get('volume_ratio')}")
        sig = opt.get("signal", {})
        print(f"Signal 门槛: min_score={sig.get('min_score')}")
        val = opt.get("validation", {})
        print(f"验证: win_rate={val.get('win_rate_7d')}, mean_return={val.get('mean_return_7d')}, "
              f"objective={val.get('objective')}")
    else:
        print("尚未运行过 --optimize，config.yaml 中无 optimized 段。")

    print()
    info = load_latest_model()
    if info:
        print(f"=== 最新 ML 模型 ===")
        print(f"训练时间: {info.trained_at}")
        print(f"训练样本: {info.sample_count}")
        print(f"验证准确率: {info.validation_accuracy:.1%}")
    else:
        print("尚未训练 ML 模型。运行 --retrain 进行训练。")
```

- [ ] **Step 4: 在 main.py 顶部添加 import（lazy import 已在函数内部）**

无需额外全局 import，三个函数均使用函数内 import 避免启动时加载 optuna/lightgbm。

- [ ] **Step 5: 运行验证 CLI 帮助**

Run: `.venv/bin/python main.py --help`
Expected: 输出中包含 `--optimize`, `--retrain`, `--optimize-report`

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat: add --optimize, --retrain, --optimize-report CLI commands"
```

---

### Task 8: 信号管道集成 — 扫描后自动记录 + ML 过滤

**Files:**
- Modify: `main.py` (run_divergence, run 函数中插入 feedback + ml_filter 调用)

- [ ] **Step 1: 在 run_divergence() 函数末尾添加反馈记录**

找到 `run_divergence()` 函数中 `save_scan(signals, mode="divergence")` 之后，追加：

```python
    # 记录信号到 feedback 表
    try:
        from scanner.optimize.feedback import ensure_outcomes_table, record_signal_outcome
        from scanner.optimize.feature_engine import extract_features
        from scanner.kline import fetch_klines

        ensure_outcomes_table()
        btc_df = fetch_klines("BTC/USDT", days=30)
        today = datetime.now().strftime("%Y-%m-%d")
        for s in signals:
            df = klines_map.get(s.symbol)
            if df is None:
                continue
            match_dict = {
                "symbol": s.symbol, "score": s.score,
                "volume_ratio": s.volume_ratio, "drop_pct": s.drop_pct,
                "r_squared": 0, "max_daily_pct": 0, "window_days": s.window_days,
            }
            features = extract_features(match_dict, df, btc_df)
            import json as _json
            record_signal_outcome(
                scan_result_id=None, symbol=s.symbol,
                signal_date=today, signal_price=s.price,
                features_json=_json.dumps(features),
                btc_price=float(btc_df["close"].iloc[-1]) if btc_df is not None else 0,
            )
    except Exception as e:
        print(f"[feedback] 记录失败（不影响扫描）: {e}")
```

- [ ] **Step 2: 在 run() 函数（accumulation 模式）末尾添加同样的反馈记录**

在 `run()` 函数中 `save_scan(signals, mode="accumulation")` 之后，追加类似代码。其中 `match_dict` 可从对应的 `matches` 列表中获取完整字段（包括 r_squared, max_daily_pct）。

```python
    # 记录信号到 feedback 表
    try:
        from scanner.optimize.feedback import ensure_outcomes_table, record_signal_outcome
        from scanner.optimize.feature_engine import extract_features
        from scanner.kline import fetch_klines

        ensure_outcomes_table()
        btc_df = fetch_klines("BTC/USDT", days=30)
        today = datetime.now().strftime("%Y-%m-%d")
        match_by_symbol = {m["symbol"]: m for m in matches}
        for s in signals:
            m = match_by_symbol.get(s.symbol, {})
            df = klines_map.get(s.symbol) if klines_map else None
            if df is None:
                continue
            features = extract_features(m, df, btc_df)
            import json as _json
            record_signal_outcome(
                scan_result_id=None, symbol=s.symbol,
                signal_date=today, signal_price=s.price,
                features_json=_json.dumps(features),
                btc_price=float(btc_df["close"].iloc[-1]) if btc_df is not None else 0,
            )
    except Exception as e:
        print(f"[feedback] 记录失败（不影响扫描）: {e}")
```

- [ ] **Step 3: 在 generate_signals 调用前插入 ML 过滤**

在 `run_divergence()` 和 `run()` 中，找到 `generate_signals()` 调用，在其之后添加 ML 过滤逻辑：

```python
    # ML 过滤（如有模型）
    try:
        from scanner.optimize.ml_filter import load_latest_model, predict_proba, compute_final_score
        from scanner.optimize.feature_engine import extract_features
        from scanner.kline import fetch_klines

        model_info = load_latest_model()
        if model_info and model_info.model is not None:
            btc_df = fetch_klines("BTC/USDT", days=30)
            filtered = []
            for s in signals:
                df = klines_map.get(s.symbol) if klines_map else None
                if df is None:
                    filtered.append(s)
                    continue
                m = match_by_symbol.get(s.symbol, {}) if 'match_by_symbol' in dir() else {}
                features = extract_features(m, df, btc_df)
                ml_prob = predict_proba(model_info.model, features)
                final = compute_final_score(s.score, ml_prob)
                if final >= signal_config.min_score:
                    filtered.append(s)
            print(f"[ML] 过滤: {len(signals)} → {len(filtered)} 个信号")
            signals = filtered
    except Exception as e:
        print(f"[ML] 过滤跳过（不影响扫描）: {e}")
```

- [ ] **Step 4: 运行全套测试确认无回归**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: integrate feedback recording and ML filtering into scan pipeline"
```

---

### Task 9: 端到端集成测试

**Files:**
- Create: `tests/test_optimize_integration.py`

- [ ] **Step 1: 编写集成测试**

```python
# tests/test_optimize_integration.py
"""端到端集成测试：feature_engine → feedback → ml_filter → retrain 完整流程。"""

import json
import numpy as np
import pytest

from scanner.optimize.feature_engine import extract_features, FEATURE_NAMES
from scanner.optimize.feedback import (
    ensure_outcomes_table,
    record_signal_outcome,
    backfill_return,
    get_labeled_outcomes,
)
from scanner.optimize.ml_filter import train_model, predict_proba, compute_final_score
from scanner.optimize.retrain import run_retrain


def _make_df(n: int = 60):
    import pandas as pd
    rng = np.random.default_rng(42)
    closes = 100.0 + np.cumsum(rng.normal(0, 1, n))
    closes = np.maximum(closes, 10.0)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": closes,
        "high": closes * 1.02,
        "low": closes * 0.98,
        "close": closes,
        "volume": rng.uniform(1e6, 5e6, n),
    })


class TestEndToEnd:
    def test_full_pipeline(self, tmp_path):
        """完整流程：提取特征 → 记录信号 → 回填收益 → 训练模型 → 预测。"""
        db_path = str(tmp_path / "test.db")
        models_dir = str(tmp_path / "models")
        results_dir = str(tmp_path / "results")

        ensure_outcomes_table(db_path)
        rng = np.random.default_rng(42)
        df = _make_df(60)

        # 模拟 120 个信号的完整生命周期
        for i in range(120):
            match_dict = {
                "symbol": f"COIN{i}/USDT",
                "score": float(rng.uniform(0.3, 0.9)),
                "volume_ratio": float(rng.uniform(0.2, 0.8)),
                "drop_pct": float(rng.uniform(0.05, 0.15)),
                "r_squared": float(rng.uniform(0.3, 0.95)),
                "max_daily_pct": float(rng.uniform(0.01, 0.05)),
                "window_days": int(rng.integers(7, 15)),
            }

            features = extract_features(match_dict, df, btc_df=None)
            assert len(features) == len(FEATURE_NAMES)

            record_signal_outcome(
                db_path=db_path,
                scan_result_id=i,
                symbol=match_dict["symbol"],
                signal_date=f"2026-{1 + i // 30:02d}-{1 + i % 28:02d}",
                signal_price=float(df["close"].iloc[-1]),
                features_json=json.dumps(features),
                btc_price=60000.0,
            )
            ret = float(rng.normal(0.01, 0.05))
            backfill_return(db_path, outcome_id=i + 1, period="return_7d", value=ret)

        # 验证 labeled 数据
        labeled = get_labeled_outcomes(db_path)
        assert len(labeled) == 120

        # 重训练
        report = run_retrain(db_path=db_path, models_dir=models_dir, results_dir=results_dir)
        assert report.samples_used >= 100
        assert report.model_path is not None

        # 用训练好的模型做预测
        from scanner.optimize.ml_filter import load_model
        info = load_model(report.model_path)
        test_features = extract_features(
            {"symbol": "TEST", "score": 0.8, "volume_ratio": 0.3,
             "drop_pct": 0.10, "r_squared": 0.9, "max_daily_pct": 0.02, "window_days": 14},
            df, btc_df=None,
        )
        prob = predict_proba(info.model, test_features)
        assert 0.0 <= prob <= 1.0

        final = compute_final_score(0.8, prob)
        assert 0.0 <= final <= 1.0
```

- [ ] **Step 2: 运行测试**

Run: `.venv/bin/pytest tests/test_optimize_integration.py -v`
Expected: 1 passed

- [ ] **Step 3: 运行全套测试确认无回归**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add tests/test_optimize_integration.py
git commit -m "test: add end-to-end integration test for optimize pipeline"
```

---

### Task 10: .gitignore + models 目录 + 最终验证

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: 在 .gitignore 中排除模型文件**

追加到 `.gitignore`：

```
# ML 模型文件
scanner/optimize/models/
```

- [ ] **Step 2: 创建 models 目录的 .gitkeep**

```bash
mkdir -p scanner/optimize/models
touch scanner/optimize/models/.gitkeep
```

- [ ] **Step 3: 运行全套测试**

Run: `.venv/bin/pytest tests/ -v`
Expected: 全部通过

- [ ] **Step 4: 验证 CLI 可用**

Run: `.venv/bin/python main.py --optimize-report`
Expected: 输出"尚未运行过 --optimize"和"尚未训练 ML 模型"

- [ ] **Step 5: Commit**

```bash
git add .gitignore scanner/optimize/models/.gitkeep
git commit -m "chore: add .gitignore for ML models, create models directory"
```
