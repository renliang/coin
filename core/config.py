from pathlib import Path
from pydantic import BaseModel
import yaml


class ExchangeConfig(BaseModel):
    id: str = "okx"
    api_key: str = ""
    secret: str = ""
    password: str = ""
    sandbox: bool = True


class RiskConfig(BaseModel):
    max_risk_per_trade: float = 0.01
    max_open_positions: int = 3
    daily_loss_limit: float = 0.05
    max_leverage: float = 5.0


class StrategyConfig(BaseModel):
    name: str
    class_name: str
    symbol: str
    timeframe: str
    params: dict = {}


class WebConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class DatabaseConfig(BaseModel):
    path: str = "coin.db"


class AppConfig(BaseModel):
    exchange: ExchangeConfig = ExchangeConfig()
    risk: RiskConfig = RiskConfig()
    strategies: list[StrategyConfig] = []
    web: WebConfig = WebConfig()
    database: DatabaseConfig = DatabaseConfig()


def load_config(path: str = "config.yaml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        return AppConfig()
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    return AppConfig(**data)
