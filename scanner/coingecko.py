import logging
import time

import requests

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

_proxies = {}


def set_proxy(proxy: str):
    global _proxies
    if proxy:
        _proxies = {"https": proxy, "http": proxy}


def fetch_small_cap_coins(
    max_market_cap: float = 100_000_000,
    max_coins: int = 99999,
    max_pages: int = 100,
    page_delay: float = 30,
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
                logger.warning("CoinGecko限速，等待%d秒...", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            logger.warning("CoinGecko持续限速，使用已收集的数据继续。")
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

        logger.info("第%d页完成，已收集%d个小市值币种", page, len(coins))

        if len(coins) >= max_coins:
            coins = coins[:max_coins]
            break

        if len(data) < 250:
            break

        page += 1
        time.sleep(page_delay)

    return coins


def fetch_market_caps(symbols: list[str], page_delay: float = 8) -> dict[str, float]:
    """批量查询币种市值。

    Args:
        symbols: 币种符号列表（大写），如 ["XNO", "ZIL"]
        page_delay: 请求间隔秒数

    Returns:
        dict mapping symbol(大写) -> market_cap(美元)
    """
    # CoinGecko /coins/markets 支持按 symbol 搜索，但不支持直接用symbol查
    # 用 /search 太慢，还是用 /coins/markets 分页但一次查很多
    # 最高效：用 ids 参数，但我们没有 coingecko id
    # 折中方案：拉前几页，建立 symbol -> market_cap 映射
    result = {}
    symbols_set = {s.upper() for s in symbols}
    page = 1
    while symbols_set - result.keys() and page <= 60:
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
                logger.warning("CoinGecko限速，等待%d秒...", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            break

        data = resp.json()
        if not data:
            break

        for coin in data:
            sym = coin.get("symbol", "").upper()
            mc = coin.get("market_cap") or 0
            if sym in symbols_set and mc > 0:
                result[sym] = mc

        remaining = len(symbols_set - result.keys())
        logger.info("市值查询第%d页，已找到%d个，剩余%d个", page, len(result), remaining)

        if remaining == 0 or len(data) < 250:
            break

        page += 1
        time.sleep(page_delay)

    return result
