"""LightGBM 信号过滤器：训练、推理、保存/加载。

导出:
    ModelInfo         — 模型元数据 dataclass
    MIN_TRAINING_SAMPLES — 最小训练样本数（100）
    train_model()     — 训练 LightGBM 二分类模型
    predict_proba()   — 推理单条特征，返回 [0,1] 概率
    compute_final_score() — 加权融合原始分与 ML 概率
    save_model()      — pickle 序列化到文件
    load_model()      — pickle 反序列化
    load_latest_model() — 加载 models_dir 下最新模型
"""
from __future__ import annotations

import os
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import lightgbm as lgb

from scanner.optimize.feature_engine import FEATURE_NAMES

# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────
MIN_TRAINING_SAMPLES: int = 100


# ──────────────────────────────────────────────
# 数据类
# ──────────────────────────────────────────────
@dataclass
class ModelInfo:
    model: object | None          # lightgbm.Booster 或 None
    trained_at: str
    sample_count: int
    validation_accuracy: float
    feature_names: list[str] = field(default_factory=lambda: list(FEATURE_NAMES))


# ──────────────────────────────────────────────
# 训练
# ──────────────────────────────────────────────
def train_model(
    X: list[list[float]],
    y: list[int],
    test_ratio: float = 0.2,
) -> ModelInfo:
    """训练 LightGBM 二分类模型。

    - 样本数 < MIN_TRAINING_SAMPLES 时返回 model=None 的 ModelInfo。
    - 使用时间序列分割（尾部 test_ratio 为验证集）。
    """
    n = len(X)
    now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if n < MIN_TRAINING_SAMPLES:
        return ModelInfo(
            model=None,
            trained_at=now_str,
            sample_count=n,
            validation_accuracy=0.0,
            feature_names=list(FEATURE_NAMES),
        )

    # 时间序列分割
    split = int(n * (1 - test_ratio))
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]

    X_train_arr = np.array(X_train, dtype=np.float64)
    X_val_arr = np.array(X_val, dtype=np.float64)

    dtrain = lgb.Dataset(X_train_arr, label=y_train, feature_name=FEATURE_NAMES, free_raw_data=False)
    dval = lgb.Dataset(X_val_arr, label=y_val, reference=dtrain, free_raw_data=False)

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

    callbacks = [lgb.early_stopping(stopping_rounds=20, verbose=False)]
    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=200,
        valid_sets=[dval],
        callbacks=callbacks,
    )

    # 验证准确率
    preds = booster.predict(X_val_arr)
    correct = sum((p >= 0.5) == bool(label) for p, label in zip(preds, y_val))
    val_acc = correct / len(y_val) if y_val else 0.0

    return ModelInfo(
        model=booster,
        trained_at=now_str,
        sample_count=n,
        validation_accuracy=val_acc,
        feature_names=list(FEATURE_NAMES),
    )


# ──────────────────────────────────────────────
# 推理
# ──────────────────────────────────────────────
def predict_proba(model: object | None, features: list[float]) -> float:
    """推理单条特征向量，返回 [0, 1] 概率。

    model 为 None 时返回 0.5。
    """
    if model is None:
        return 0.5
    arr = np.array([features], dtype=np.float64)
    result = model.predict(arr)
    return float(result[0])


# ──────────────────────────────────────────────
# 分数融合
# ──────────────────────────────────────────────
def compute_final_score(
    original_score: float,
    ml_proba: float | None,
    original_weight: float = 0.4,
    ml_weight: float = 0.6,
) -> float:
    """加权融合原始分与 ML 概率。

    ml_proba 为 None 时直接返回 original_score。
    """
    if ml_proba is None:
        return original_score
    return original_weight * original_score + ml_weight * ml_proba


# ──────────────────────────────────────────────
# 序列化
# ──────────────────────────────────────────────
def save_model(info: ModelInfo, models_dir: str = "scanner/optimize/models") -> str:
    """pickle 序列化 ModelInfo，文件名 lgbm_YYYYMMDD_HHMMSS.pkl。

    返回保存的文件路径（绝对路径字符串）。
    """
    dir_path = Path(models_dir)
    dir_path.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"lgbm_{ts}.pkl"
    file_path = dir_path / filename

    with open(file_path, "wb") as f:
        pickle.dump(info, f)

    return str(file_path.resolve())


def load_model(path: str) -> ModelInfo:
    """从 pickle 文件加载 ModelInfo。"""
    with open(path, "rb") as f:
        return pickle.load(f)


def load_latest_model(models_dir: str = "scanner/optimize/models") -> Optional[ModelInfo]:
    """加载 models_dir 下最新（按文件名排序）的模型。

    目录不存在或为空时返回 None。
    """
    dir_path = Path(models_dir)
    if not dir_path.exists():
        return None

    pkl_files = sorted(dir_path.glob("lgbm_*.pkl"))
    if not pkl_files:
        return None

    return load_model(str(pkl_files[-1]))
