"""E2E test fixtures: temp DB, seed data, FastAPI server, Playwright page."""
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

import pytest
import urllib.request
import urllib.error


# ---------------------------------------------------------------------------
# 1) db_path  — session-scoped temp DB
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db_path():
    """Create a temporary SQLite DB file and export COIN_DB_PATH."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="coin_e2e_")
    os.close(fd)
    os.environ["COIN_DB_PATH"] = path
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 2) seed_db  — populate sentiment + portfolio + scanner tables
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def seed_db(db_path: str):
    """Seed the temp DB with realistic test data."""
    # --- Sentiment items ---
    from sentiment.models import SentimentItem, SentimentSignal
    from sentiment.store import save_items, save_signal

    now = datetime.now()

    items = [
        SentimentItem(source="twitter", symbol="BTC/USDT", score=0.6, confidence=0.8,
                      raw_text="BTC looking strong, breakout imminent", timestamp=now - timedelta(hours=1)),
        SentimentItem(source="news", symbol="ETH/USDT", score=-0.3, confidence=0.7,
                      raw_text="ETH facing regulatory headwinds", timestamp=now - timedelta(hours=2)),
        SentimentItem(source="onchain", symbol="BTC/USDT", score=0.4, confidence=0.9,
                      raw_text="Whale accumulation detected for BTC", timestamp=now - timedelta(hours=3)),
        SentimentItem(source="telegram", symbol="SOL/USDT", score=0.2, confidence=0.6,
                      raw_text="SOL ecosystem growing steadily", timestamp=now - timedelta(hours=4)),
        SentimentItem(source="twitter", symbol="ETH/USDT", score=-0.5, confidence=0.75,
                      raw_text="ETH gas fees remain high, bearish outlook", timestamp=now - timedelta(hours=5)),
    ]
    save_items(items, db_path=db_path)

    # --- Sentiment signals ---
    signals = [
        SentimentSignal(symbol="BTC/USDT", score=0.5, direction="bullish", confidence=0.85),
        SentimentSignal(symbol="ETH/USDT", score=-0.4, direction="bearish", confidence=0.7),
        SentimentSignal(symbol="", score=0.1, direction="neutral", confidence=0.6),
    ]
    for sig in signals:
        save_signal(sig, db_path=db_path)

    # --- Portfolio NAV history (30 days: 10000 -> 11500) ---
    from portfolio.store import save_nav, save_weights, save_risk_event

    today = date.today()
    start_nav = 10000.0
    end_nav = 11500.0
    hwm = start_nav
    for i in range(30):
        d = today - timedelta(days=29 - i)
        nav = start_nav + (end_nav - start_nav) * (i / 29)
        hwm = max(hwm, nav)
        save_nav(d, nav, hwm, db_path=db_path)

    # --- Strategy weights ---
    save_weights(today, {
        "accumulation": 0.35,
        "divergence": 0.40,
        "breakout": 0.25,
    }, db_path=db_path)

    # --- Risk event ---
    save_risk_event(
        level="position",
        strategy_id="divergence",
        event_type="drawdown_warning",
        details="Position drawdown reached 3.5%",
        db_path=db_path,
    )

    # --- Scanner tables (ensure they exist) ---
    from scanner.tracker import _get_conn as _scanner_get_conn
    conn = _scanner_get_conn()
    conn.close()

    yield


# ---------------------------------------------------------------------------
# 3) server_url  — start Flask on a random free port
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_url(seed_db, db_path: str):
    """Start the FastAPI server and yield its base URL."""
    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"

    project_root = os.path.join(os.path.dirname(__file__), "..", "..")
    project_root = os.path.abspath(project_root)

    env = {**os.environ, "COIN_DB_PATH": db_path, "API_PORT": str(port), "API_HOST": "127.0.0.1"}

    proc = subprocess.Popen(
        [sys.executable, "-m", "api"],
        env=env,
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to be ready (poll /api/config)
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(f"{url}/api/config", timeout=2)
            if resp.status == 200:
                break
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.3)
    else:
        proc.terminate()
        stdout = proc.stdout.read().decode() if proc.stdout else ""
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        raise RuntimeError(
            f"FastAPI server failed to start on port {port}.\nstdout: {stdout}\nstderr: {stderr}"
        )

    yield url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# 4) app_page  — navigate to the SPA root and wait for load
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_page(page, server_url: str):
    """Navigate to the SPA dashboard and wait for network idle."""
    page.goto(f"{server_url}/app/")
    page.wait_for_load_state("networkidle")
    return page
