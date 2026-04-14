"""端到端集成测试：optimize pipeline (feature_engine → feedback → retrain → ml_filter)。"""

from __future__ import annotations

import json
import os
import random

import numpy as np
import pandas as pd
import pytest

from scanner.optimize.feature_engine import FEATURE_NAMES, extract_features
from scanner.optimize.feedback import (
    backfill_return,
    ensure_outcomes_table,
    get_labeled_outcomes,
    record_signal_outcome,
)
from scanner.optimize.ml_filter import compute_final_score, load_model, predict_proba
from scanner.optimize.retrain import run_retrain


def _make_klines(n: int = 60, seed: int = 42) -> pd.DataFrame:
    """生成合成 K 线 DataFrame（含 high/low/close/volume 列）。"""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    close = np.abs(close) + 1.0  # 确保价格为正
    high = close * (1 + rng.uniform(0, 0.02, n))
    low = close * (1 - rng.uniform(0, 0.02, n))
    volume = rng.uniform(1e6, 5e6, n)
    return pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})


class TestEndToEnd:
    def test_full_pipeline(self, tmp_path):
        """完整流水线：特征提取 → 记录信号 → 回填收益 → 重训练 → 推理。"""
        db_path = str(tmp_path / "test.db")
        models_dir = str(tmp_path / "models")
        results_dir = str(tmp_path / "results")

        # 1. 建表
        ensure_outcomes_table(db_path)

        # 2. 生成合成 K 线
        df = _make_klines(n=60, seed=0)

        # 3. 循环 120 次模拟信号生命周期
        rng = random.Random(99)
        outcome_ids: list[int] = []

        for i in range(120):
            match_dict = {
                "score": rng.uniform(0.0, 1.0),
                "volume_ratio": rng.uniform(0.5, 3.0),
                "drop_pct": rng.uniform(0.05, 0.4),
                "r_squared": rng.uniform(0.5, 1.0),
                "max_daily_pct": rng.uniform(0.01, 0.1),
                "window_days": rng.randint(7, 60),
            }

            features = extract_features(match_dict, df, btc_df=None)

            # 断言特征数量
            assert len(features) == len(FEATURE_NAMES), (
                f"期望 {len(FEATURE_NAMES)} 个特征，实际 {len(features)}"
            )

            features_json = json.dumps(features)

            row_id = record_signal_outcome(
                db_path=db_path,
                scan_result_id=i,
                symbol=f"SYM{i}/USDT",
                signal_date=f"2026-01-{(i % 28) + 1:02d}",
                signal_price=float(df["close"].iloc[-1]),
                features_json=features_json,
                btc_price=50000.0,
            )

            if row_id is not None:
                outcome_ids.append(row_id)

        # 回填 return_7d
        np_rng = np.random.default_rng(7)
        for oid in outcome_ids:
            ret = float(np_rng.normal(0.01, 0.05))
            backfill_return(db_path, oid, "return_7d", ret)

        # 4. 验证标注数量
        labeled = get_labeled_outcomes(db_path)
        assert len(labeled) == 120, f"期望 120 条已标注记录，实际 {len(labeled)}"

        # 5. 重训练
        report = run_retrain(db_path, models_dir, results_dir)
        assert report.samples_used >= 100, (
            f"samples_used 期望 >= 100，实际 {report.samples_used}"
        )
        assert report.model_path is not None, "期望 model_path 非 None（模型应已保存）"

        # 6. 加载模型并推理
        model_info = load_model(report.model_path)
        sample_features = extract_features(
            {
                "score": 0.7,
                "volume_ratio": 1.5,
                "drop_pct": 0.15,
                "r_squared": 0.8,
                "max_daily_pct": 0.03,
                "window_days": 21,
            },
            df,
            btc_df=None,
        )
        prob = predict_proba(model_info.model, sample_features)
        assert 0.0 <= prob <= 1.0, f"predict_proba 结果超出 [0, 1]：{prob}"

        # 7. 融合分数
        final = compute_final_score(0.8, prob)
        assert 0.0 <= final <= 1.0, f"compute_final_score 结果超出 [0, 1]：{final}"
