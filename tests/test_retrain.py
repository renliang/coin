"""tests/test_retrain.py — retrain module 测试。"""

from __future__ import annotations

import json
import os
import random
import tempfile

import pytest

from scanner.optimize.feedback import (
    backfill_return,
    ensure_outcomes_table,
    record_signal_outcome,
)
from scanner.optimize.feature_engine import FEATURE_NAMES
from scanner.optimize.retrain import RetrainReport, run_retrain


class TestRetrainProducesReport:
    """有足够标注数据时，run_retrain 应训练并保存模型。"""

    def test_retrain_produces_report(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        models_dir = str(tmp_path / "models")
        results_dir = str(tmp_path / "results")

        ensure_outcomes_table(db_path)

        rng = random.Random(42)
        for i in range(120):
            features = [rng.uniform(-1.0, 1.0) for _ in FEATURE_NAMES]
            features_json = json.dumps(features)
            row_id = record_signal_outcome(
                db_path=db_path,
                scan_result_id=i,
                symbol=f"TOKEN{i}/USDT",
                signal_date="2026-01-01",
                signal_price=1.0,
                features_json=features_json,
                btc_price=50000.0,
            )
            # 回填 return_7d，正负交替
            return_val = 0.05 if i % 2 == 0 else -0.03
            backfill_return(db_path, row_id, "return_7d", return_val)

        report = run_retrain(
            db_path=db_path,
            models_dir=models_dir,
            results_dir=results_dir,
        )

        assert isinstance(report, RetrainReport)
        assert report.samples_used >= 100
        assert report.model_path is not None


class TestRetrainInsufficientData:
    """空 DB 时，run_retrain 应返回空报告。"""

    def test_retrain_insufficient_data(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        models_dir = str(tmp_path / "models")
        results_dir = str(tmp_path / "results")

        ensure_outcomes_table(db_path)

        report = run_retrain(
            db_path=db_path,
            models_dir=models_dir,
            results_dir=results_dir,
        )

        assert isinstance(report, RetrainReport)
        assert report.model_path is None
        assert report.samples_used == 0
