from db.models import create_tables, get_session, Order


def test_create_and_query_order(tmp_path):
    db_path = str(tmp_path / "test.db")
    create_tables(db_path)
    with get_session(db_path) as session:
        order = Order(
            symbol="BTC-USDT-SWAP",
            direction="long",
            size=0.01,
            entry_price=50000.0,
            stop_loss=49000.0,
            strategy_id="test_strategy",
        )
        session.add(order)
        session.commit()
        session.refresh(order)
        assert order.id is not None
        assert order.status == "PENDING"
