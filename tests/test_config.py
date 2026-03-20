from core.config import load_config, AppConfig


def test_load_default_config(tmp_path):
    config = load_config("nonexistent.yaml")
    assert isinstance(config, AppConfig)
    assert config.risk.max_risk_per_trade == 0.01


def test_load_config_from_file(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("risk:\n  max_risk_per_trade: 0.02\n")
    config = load_config(str(cfg_file))
    assert config.risk.max_risk_per_trade == 0.02
