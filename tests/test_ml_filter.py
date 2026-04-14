"""LightGBM 信号过滤器测试。"""
from __future__ import annotations

import numpy as np
import pytest

from scanner.optimize.feature_engine import FEATURE_NAMES
from scanner.optimize.ml_filter import (
    MIN_TRAINING_SAMPLES,
    ModelInfo,
    compute_final_score,
    load_model,
    predict_proba,
    save_model,
    train_model,
)

N_FEATURES = len(FEATURE_NAMES)


def _make_data(n: int, seed: int = 42):
    rng = np.random.default_rng(seed)
    X = rng.random((n, N_FEATURES)).tolist()
    y = rng.integers(0, 2, size=n).tolist()
    return X, y


# ──────────────────────────────────────────────
# 1. 正常训练
# ──────────────────────────────────────────────
def test_train_returns_model_info():
    X, y = _make_data(150)
    info = train_model(X, y)
    assert isinstance(info, ModelInfo)
    assert info.model is not None
    assert info.sample_count == 150
    assert 0.0 <= info.validation_accuracy <= 1.0
    assert info.feature_names == FEATURE_NAMES


# ──────────────────────────────────────────────
# 2. 数据不足
# ──────────────────────────────────────────────
def test_train_insufficient_data():
    X, y = _make_data(20)
    info = train_model(X, y)
    assert isinstance(info, ModelInfo)
    assert info.model is None
    assert info.sample_count == 20


# ──────────────────────────────────────────────
# 3. 预测返回概率
# ──────────────────────────────────────────────
def test_predict_returns_probability():
    X, y = _make_data(150)
    info = train_model(X, y)
    features = X[0]
    prob = predict_proba(info.model, features)
    assert isinstance(prob, float)
    assert 0.0 <= prob <= 1.0


# ──────────────────────────────────────────────
# 4. model=None 返回 0.5
# ──────────────────────────────────────────────
def test_predict_none_model_returns_half():
    features = [0.5] * N_FEATURES
    prob = predict_proba(None, features)
    assert prob == 0.5


# ──────────────────────────────────────────────
# 5. 加权组合
# ──────────────────────────────────────────────
def test_weighted_combination():
    result = compute_final_score(0.8, 0.9)
    expected = 0.4 * 0.8 + 0.6 * 0.9
    assert abs(result - expected) < 1e-9


# ──────────────────────────────────────────────
# 6. save → load → 预测一致
# ──────────────────────────────────────────────
def test_roundtrip(tmp_path):
    X, y = _make_data(150)
    info = train_model(X, y)
    path = save_model(info, models_dir=str(tmp_path))
    loaded = load_model(path)
    features = X[5]
    p1 = predict_proba(info.model, features)
    p2 = predict_proba(loaded.model, features)
    assert abs(p1 - p2) < 1e-6
