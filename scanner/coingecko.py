import time

import requests


COINGECKO_BASE = "https://api.coingecko.com/api/v3"


def fetch_small_cap_coins(max_market_cap: float = 100_000_000) -> list[dict]:
    """从CoinGecko拉取市值低于阈值的币种列表。

    Returns:
        list of dict, each with keys:
            - id: CoinGecko币种ID
            - symbol: 币种符号（大写）
            - name: 币种名称
            - market_cap: 市值（美元）
    """
    coins = []
    page = 1
    while True:
        resp = requests.get(
            f"{COINGECKO_BASE}/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 250,
                "page": page,
                "sparkline": "false",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break

        for coin in data:
            mc = coin.get("market_cap") or 0
            if mc <= 0:
                continue
            if mc > max_market_cap:
                continue
            coins.append({
                "id": coin["id"],
                "symbol": coin["symbol"].upper(),
                "name": coin["name"],
                "market_cap": mc,
            })

        # 如果本页不足250条，说明到头了
        if len(data) < 250:
            break

        page += 1
        time.sleep(2)  # CoinGecko限速：30次/分钟

    return coins
