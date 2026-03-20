from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel, create_engine, Session


class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str
    direction: str          # long / short
    size: float
    entry_price: float
    exit_price: Optional[float] = None
    stop_loss: float
    take_profit: Optional[float] = None
    status: str = "PENDING"  # PENDING / OPEN / CLOSING / CLOSED
    strategy_id: str
    okx_order_id: Optional[str] = None
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    pnl: Optional[float] = None


class AccountSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    balance: float
    unrealized_pnl: float = 0.0
    daily_pnl: float = 0.0
    snapshot_at: datetime = Field(default_factory=datetime.utcnow)


def get_engine(db_path: str = "coin.db"):
    return create_engine(f"sqlite:///{db_path}")


def create_tables(db_path: str = "coin.db"):
    engine = get_engine(db_path)
    SQLModel.metadata.create_all(engine)


def get_session(db_path: str = "coin.db"):
    engine = get_engine(db_path)
    return Session(engine)
