"""retrain.py — 模型重训练入口。

导出:
    RetrainReport  — 重训练结果 dataclass
    run_retrain()  — 执行重训练流程
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DEFAULT_DB_PATH = os.environ.get("COIN_DB_PATH", "scanner.db")

from scanner.optimize.feature_engine import FEATURE_NAMES
from scanner.optimize.feedback import get_labeled_outcomes
from scanner.optimize.ml_filter import (
    MIN_TRAINING_SAMPLES,
    ModelInfo,
    load_latest_model,
    save_model,
    train_model,
)

logger = logging.getLogger(__name__)


@dataclass
class RetrainReport:
    timestamp: str
    samples_used: int
    model_path: Optional[str]
    new_accuracy: float
    old_accuracy: Optional[float]
    improved: bool
    report_path: Optional[str]


def run_retrain(
    db_path: str = _DEFAULT_DB_PATH,
    models_dir: str = "scanner/optimize/models",
    results_dir: str = "results",
) -> RetrainReport:
    """执行模型重训练流程。

    流程：
    1. 读取已标注数据（return_7d 不为 NULL）
    2. 样本不足时提前返回空报告
    3. 解析 features_json，构建 X / y
    4. 训练新模型
    5. 对比旧模型；新模型更优时才持久化
    6. 保存 JSON 报告
    7. 返回 RetrainReport

    Returns:
        RetrainReport，包含本次重训练的关键指标。
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n_features = len(FEATURE_NAMES)

    # ── 1. 读取标注数据 ──────────────────────────────────────
    labeled = get_labeled_outcomes(db_path)

    # ── 2. 样本不足 ──────────────────────────────────────────
    if len(labeled) < MIN_TRAINING_SAMPLES:
        return RetrainReport(
            timestamp=timestamp,
            samples_used=len(labeled),
            model_path=None,
            new_accuracy=0.0,
            old_accuracy=None,
            improved=False,
            report_path=None,
        )

    # ── 3. 解析特征 ───────────────────────────────────────────
    X: list[list[float]] = []
    y: list[int] = []

    for row in labeled:
        fj = row.get("features_json")
        if not fj:
            continue
        try:
            features = json.loads(fj)
        except (json.JSONDecodeError, TypeError):
            logger.warning("跳过 features_json 解析失败的记录 id=%s", row.get("id"))
            continue

        if len(features) != n_features:
            logger.warning(
                "跳过特征长度不匹配的记录 id=%s (期望 %d, 实际 %d)",
                row.get("id"),
                n_features,
                len(features),
            )
            continue

        label = 1 if (row.get("return_7d") or 0.0) > 0 else 0
        X.append([float(v) for v in features])
        y.append(label)

    samples_used = len(X)

    # 解析后仍不足
    if samples_used < MIN_TRAINING_SAMPLES:
        return RetrainReport(
            timestamp=timestamp,
            samples_used=samples_used,
            model_path=None,
            new_accuracy=0.0,
            old_accuracy=None,
            improved=False,
            report_path=None,
        )

    # ── 4. 训练新模型 ─────────────────────────────────────────
    new_info: ModelInfo = train_model(X, y)

    # ── 5. 加载旧模型并对比 ───────────────────────────────────
    old_info: Optional[ModelInfo] = load_latest_model(models_dir)
    old_accuracy = old_info.validation_accuracy if old_info is not None else None

    improved = new_info.validation_accuracy > (old_accuracy or 0.0)

    saved_path: Optional[str] = None
    if improved and new_info.model is not None:
        saved_path = save_model(new_info, models_dir)

    # ── 6. 保存 JSON 报告 ─────────────────────────────────────
    report_path: Optional[str] = None
    results_path = Path(results_dir)
    results_path.mkdir(parents=True, exist_ok=True)

    report_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_file = results_path / f"retrain_{report_date}.json"

    report_dict = {
        "timestamp": timestamp,
        "samples_used": samples_used,
        "model_path": saved_path,
        "new_accuracy": float(new_info.validation_accuracy),
        "old_accuracy": float(old_accuracy) if old_accuracy is not None else None,
        "improved": bool(improved),
    }

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, ensure_ascii=False, indent=2)

    report_path = str(report_file.resolve())

    # ── 7. 返回报告 ───────────────────────────────────────────
    return RetrainReport(
        timestamp=timestamp,
        samples_used=samples_used,
        model_path=saved_path,
        new_accuracy=new_info.validation_accuracy,
        old_accuracy=old_accuracy,
        improved=improved,
        report_path=report_path,
    )
