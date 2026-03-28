import time

import requests


COINGECKO_BASE = "https://api.coingecko.com/api/v3"

_proxies = {}


def set_proxy(proxy: str):
    global _proxies
    if proxy:
        _proxies = {"https": proxy, "http": proxy}


def fetch_small_cap_coins(
    max_market_cap: float = 100_000_000,
    max_coins: int = 500,
    max_pages: int = 10,
) -> list[dict]:
    """从CoinGecko拉取市值低于阈值的币种列表。

    Args:
        max_market_cap: 市值上限（美元）
        max_coins: 最多返回多少个币种
        max_pages: 最多翻多少页（每页250条）

    Returns:
        list of dict, each with keys:
            - id: CoinGecko币种ID
            - symbol: 币种符号（大写）
            - name: 币种名称
            - market_cap: 市值（美元）
    """
    coins = []
    page = 1
    while page <= max_pages:
        # 重试逻辑：429限速时指数退避
        for attempt in range(4):
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
                proxies=_proxies or None,
            )
            if resp.status_code == 429:
                wait = 2 ** attempt * 15
                print(f"       CoinGecko限速，等待{wait}秒...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            print("       CoinGecko持续限速，使用已收集的数据继续。")
            break

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

        print(f"       第{page}页完成，已收集{len(coins)}个小市值币种")

        if len(coins) >= max_coins:
            coins = coins[:max_coins]
            break

        if len(data) < 250:
            break

        page += 1
        time.sleep(8)  # CoinGecko免费版需要保守间隔

    return coins
