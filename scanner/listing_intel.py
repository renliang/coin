"""新币观察清单 L2 增强：公告（L2a）、链上池近似（L2b）、尽调规则分（L2c）。

与 `scanner/new_coin.py` 解耦：在 L0 JSON 产出后按行 enrich，失败不清空主清单字段。
"""

from __future__ import annotations

import csv
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

LISTING_INTEL_SCHEMA_VERSION = 2

BINANCE_CMS_URL = (
    "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
)
DEXSCREENER_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search?q="

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_LISTING_TITLE_PAT = re.compile(
    r"(list|listing|上线|上幣|上币|將上市|将上市|will list|new trading pair)",
    re.IGNORECASE,
)


@dataclass
class ListingIntelConfig:
    """listing_intel 配置段；各子项可单独关闭。"""

    enabled: bool = False
    l2a_binance_announcements: bool = True
    l2b_dexscreener: bool = True
    l2c_dd_score: bool = True
    l2a_catalog_id: int = 48
    l2a_page_size: int = 50
    l2a_max_pages: int = 2
    request_delay: float = 0.35
    dexscreener_delay: float = 0.35
    user_agent: str = DEFAULT_USER_AGENT
    manual_overlay_csv: str | None = None
    trust_tier_high_min: int = 75
    trust_tier_mid_min: int = 55
    proxy_https: str | None = None

    @classmethod
    def from_mapping(cls, d: dict | None, *, proxy_https: str | None = None) -> ListingIntelConfig:
        root_p = (proxy_https or "").strip() or None
        if not d:
            return cls(proxy_https=root_p)
        local_p = (str(d.get("proxy_https") or "").strip() or None)
        return cls(
            enabled=bool(d.get("enabled", False)),
            l2a_binance_announcements=bool(d.get("l2a_binance_announcements", True)),
            l2b_dexscreener=bool(d.get("l2b_dexscreener", True)),
            l2c_dd_score=bool(d.get("l2c_dd_score", True)),
            l2a_catalog_id=int(d.get("l2a_catalog_id", 48)),
            l2a_page_size=int(d.get("l2a_page_size", 50)),
            l2a_max_pages=int(d.get("l2a_max_pages", 2)),
            request_delay=float(d.get("request_delay", 0.35)),
            dexscreener_delay=float(d.get("dexscreener_delay", 0.35)),
            user_agent=str(d.get("user_agent", DEFAULT_USER_AGENT)),
            manual_overlay_csv=(d.get("manual_overlay_csv") or None),
            trust_tier_high_min=int(d.get("trust_tier_high_min", 75)),
            trust_tier_mid_min=int(d.get("trust_tier_mid_min", 55)),
            proxy_https=root_p or local_p,
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_opener(proxy_https: str | None) -> urllib.request.OpenerDirector:
    if proxy_https:
        handler = urllib.request.ProxyHandler({"https": proxy_https, "http": proxy_https})
        return urllib.request.build_opener(handler)
    return urllib.request.build_opener()


def http_post_json(
    url: str,
    body: dict,
    *,
    cfg: ListingIntelConfig,
    timeout: float = 25.0,
) -> tuple[dict | list | None, str | None]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", cfg.user_agent)
    req.add_header("Accept", "application/json")
    opener = _build_opener(cfg.proxy_https)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return None, f"http_{e.code}"
    except urllib.error.URLError as e:
        return None, f"url_{e.reason!s}"[:120]
    except TimeoutError:
        return None, "timeout"
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        return None, "invalid_json"


def http_get_json(
    url: str,
    *,
    cfg: ListingIntelConfig,
    timeout: float = 25.0,
) -> tuple[Any, str | None]:
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", cfg.user_agent)
    req.add_header("Accept", "application/json")
    opener = _build_opener(cfg.proxy_https)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return None, f"http_{e.code}"
    except urllib.error.URLError as e:
        return None, f"url_{e.reason!s}"[:120]
    except TimeoutError:
        return None, "timeout"
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        return None, "invalid_json"


def fetch_binance_listing_articles(cfg: ListingIntelConfig) -> tuple[list[dict], list[str]]:
    """拉取 Binance CMS 新币上架类文章标题列表（可能被 WAF/403，需代理）。"""
    errors: list[str] = []
    out: list[dict] = []
    catalog = cfg.l2a_catalog_id
    for page in range(1, cfg.l2a_max_pages + 1):
        body = {
            "type": 1,
            "catalogId": catalog,
            "pageNo": page,
            "pageSize": cfg.l2a_page_size,
        }
        parsed, err = http_post_json(BINANCE_CMS_URL, body, cfg=cfg)
        if err:
            errors.append(f"l2a_page{page}:{err}")
            break
        if not isinstance(parsed, dict):
            errors.append(f"l2a_page{page}:unexpected_shape")
            break
        data = parsed.get("data")
        if not isinstance(data, dict):
            errors.append(f"l2a_page{page}:no_data")
            break
        articles = data.get("articles") or data.get("catalogs")
        if articles is None:
            # 不同字段兼容
            articles = data.get("rows")
        if not isinstance(articles, list):
            errors.append(f"l2a_page{page}:no_articles")
            break
        for a in articles:
            if isinstance(a, dict):
                out.append(a)
        time.sleep(cfg.request_delay)
    return out, errors


def _article_title(a: dict) -> str:
    return str(a.get("title") or a.get("articleTitle") or "")


def _article_url(a: dict) -> str:
    code = a.get("code") or a.get("articleCode")
    if code:
        return f"https://www.binance.com/en/support/announceDetail/{code}"
    if u := a.get("url"):
        return str(u)
    return ""


def _parse_claimed_listing_ms(a: dict) -> int | None:
    for key in ("releaseDate", "publishDate", "publicTime", "createTime"):
        v = a.get(key)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            ms = int(v)
            return ms if ms > 1_000_000_000_000 else ms * 1000
        if isinstance(v, str):
            s = v.strip()
            if s.isdigit():
                ms = int(s)
                return ms if ms > 1_000_000_000_000 else ms * 1000
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                return int(dt.timestamp() * 1000)
            except ValueError:
                continue
    body = _article_title(a)
    m = re.search(
        r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(UTC)?",
        body,
    )
    if m:
        y, mo, d, h, mi, s, utc = m.groups()
        sec = int(s) if s else 0
        try:
            tz = timezone.utc if utc else ZoneInfo("Asia/Shanghai")
            dt = datetime(
                int(y), int(mo), int(d), int(h), int(mi), sec, tzinfo=tz,
            )
            us = dt.astimezone(timezone.utc)
            return int(us.timestamp() * 1000)
        except (ValueError, OSError):
            pass
    return None


def _title_matches_base(title: str, base: str) -> bool:
    u_base = base.upper().strip()
    if not u_base:
        return False
    t = title.upper()
    if u_base not in t:
        return False
    return bool(_LISTING_TITLE_PAT.search(title))


def pick_announcement_for_base(
    base: str,
    articles: list[dict],
    *,
    detected_at: str,
) -> dict[str, Any]:
    """为单个 base 选一篇最相关公告（仅标题匹配，不保证唯一）。"""
    best: dict | None = None
    best_ms: int = 0
    for a in articles:
        title = _article_title(a)
        if not _title_matches_base(title, base):
            continue
        ms = _parse_claimed_listing_ms(a) or 0
        cand = a
        if ms > best_ms:
            best_ms = ms
            best = cand
    if not best:
        return {
            "announcement_detected_at": None,
            "announcement_title_snippet": None,
            "announcement_url": None,
            "claimed_listing_at": None,
            "announcement_source": None,
            "announcement_confidence": None,
        }
    title_full = _article_title(best)
    snippet = title_full[:240] + ("…" if len(title_full) > 240 else "")
    claimed_ms = _parse_claimed_listing_ms(best)
    claimed_iso = (
        datetime.fromtimestamp(claimed_ms / 1000.0, tz=timezone.utc).isoformat()
        if claimed_ms
        else None
    )
    conf = "high" if claimed_ms and _title_matches_base(title_full, base) else "medium"
    if len(base) <= 2:
        conf = "low"
    return {
        "announcement_detected_at": detected_at,
        "announcement_title_snippet": snippet,
        "announcement_url": _article_url(best) or None,
        "claimed_listing_at": claimed_iso,
        "announcement_source": "binance_official",
        "announcement_confidence": conf,
    }


def load_manual_overlay(path: str) -> dict[str, dict[str, str]]:
    """CSV: base,announcement_title_snippet,announcement_url,claimed_listing_at,announcement_confidence."""
    by_base: dict[str, dict[str, str]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            b = (row.get("base") or "").strip().upper()
            if not b:
                continue
            by_base[b] = {k: (row.get(k) or "").strip() for k in row}
    return by_base


def merge_l2a_manual(overlay: dict[str, dict[str, str]], row: dict[str, Any]) -> None:
    base = str(row.get("base") or "").upper()
    o = overlay.get(base)
    if not o:
        return
    if o.get("announcement_title_snippet"):
        row["announcement_title_snippet"] = o["announcement_title_snippet"][:240]
    if o.get("announcement_url"):
        row["announcement_url"] = o["announcement_url"]
    if o.get("claimed_listing_at"):
        row["claimed_listing_at"] = o["claimed_listing_at"]
    row["announcement_source"] = o.get("announcement_source") or "manual"
    row["announcement_confidence"] = o.get("announcement_confidence") or "high"
    row["announcement_detected_at"] = _now_iso()


def enrich_l2b_dexscreener(row: dict[str, Any], cfg: ListingIntelConfig) -> None:
    base = str(row.get("base") or "").strip()
    if not base:
        return
    url = DEXSCREENER_SEARCH_URL + urllib.parse.quote(base)
    parsed, err = http_get_json(url, cfg=cfg)
    time.sleep(cfg.dexscreener_delay)
    if err or not isinstance(parsed, dict):
        row.setdefault("_intel_errors", []).append(f"l2b_dex:{err or 'bad_body'}")
        return
    pairs = parsed.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        return
    best_ts: int | None = None
    best_p: dict | None = None
    u_base = base.upper()
    for p in pairs:
        if not isinstance(p, dict):
            continue
        bt = p.get("baseToken")
        if not isinstance(bt, dict):
            continue
        sym = str(bt.get("symbol") or "").upper()
        if sym != u_base:
            continue
        pc = p.get("pairCreatedAt")
        if not isinstance(pc, (int, float)):
            continue
        ts = int(pc)
        if best_ts is None or ts < best_ts:
            best_ts = ts
            best_p = p
    if not best_p or best_ts is None:
        return
    bt = best_p.get("baseToken")
    addr = ""
    if isinstance(bt, dict):
        addr = str(bt.get("address") or "")
    row["onchain_chain"] = str(best_p.get("chainId") or "")
    row["onchain_first_pool_ts_ms"] = best_ts
    row["onchain_pair_address"] = str(best_p.get("pairAddress") or "")
    row["onchain_dex"] = str(best_p.get("dexId") or "")
    row["onchain_token_contract"] = addr or None
    row["onchain_source"] = "dexscreener"
    row["onchain_confidence"] = "medium"


def _volume_points(qv: float) -> float:
    if qv <= 0:
        return 0.0
    return min(35.0, math.log10(qv + 1.0) * 7.0)


def _mcap_points(mcap: float) -> float:
    if mcap <= 0:
        return 5.0
    return min(28.0, math.log10(mcap + 1.0) * 4.5)


def compute_l2c_dd_score(row: dict[str, Any], cfg: ListingIntelConfig) -> None:
    qv = float(row.get("quote_volume_24h") or 0.0)
    mcap = float(row.get("market_cap_usd") or 0.0)
    days = int(row.get("listing_days") or 0)
    vol_p = _volume_points(qv)
    mc_p = _mcap_points(mcap)
    age_p = min(15.0, float(days) * 0.5)
    l2a_p = 0.0
    conf = row.get("announcement_confidence")
    if row.get("announcement_url"):
        if conf == "high":
            l2a_p = 14.0
        elif conf == "medium":
            l2a_p = 8.0
        elif conf == "low":
            l2a_p = 4.0
    l2b_p = 10.0 if row.get("onchain_first_pool_ts_ms") else 0.0
    raw = vol_p + mc_p + age_p + l2a_p + l2b_p
    score = int(round(max(0.0, min(100.0, raw))))
    tier = "tier_3"
    if score >= cfg.trust_tier_high_min:
        tier = "tier_1"
    elif score >= cfg.trust_tier_mid_min:
        tier = "tier_2"
    row["dd_score"] = score
    row["trust_tier"] = tier
    row["score_components"] = {
        "volume_pts": round(vol_p, 2),
        "mcap_pts": round(mc_p, 2),
        "listing_age_pts": round(age_p, 2),
        "l2a_pts": round(l2a_p, 2),
        "l2b_pts": round(l2b_p, 2),
    }


def _delta_ms_claimed_vs_spot(row: dict[str, Any]) -> int | None:
    first = row.get("listing_first_ts_ms")
    claimed = row.get("claimed_listing_at")
    if first is None or not claimed:
        return None
    if isinstance(claimed, str):
        try:
            dt = datetime.fromisoformat(claimed.replace("Z", "+00:00"))
            cms = int(dt.timestamp() * 1000)
        except ValueError:
            return None
    else:
        return None
    return cms - int(first)


def enrich_new_listings_payload(
    payload: dict[str, Any],
    cfg: ListingIntelConfig,
) -> dict[str, Any]:
    if not cfg.enabled:
        return payload
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("payload.rows must be a list")
    if not (
        cfg.l2a_binance_announcements
        or cfg.manual_overlay_csv
        or cfg.l2b_dexscreener
        or cfg.l2c_dd_score
    ):
        return payload
    meta = dict(payload.get("meta") or {})
    extends: list[str] = []
    if cfg.l2a_binance_announcements or cfg.manual_overlay_csv:
        extends.append("l2a")
    if cfg.l2b_dexscreener:
        extends.append("l2b")
    if cfg.l2c_dd_score:
        extends.append("l2c")
    out_rows: list[dict[str, Any]] = []
    stats: dict[str, Any] = {
        "rows_attempted": len(rows),
        "l2a_matched": 0,
        "l2b_matched": 0,
        "l2c_scored": 0,
        "source_errors": [],
    }
    articles: list[dict] = []
    if cfg.enabled and cfg.l2a_binance_announcements:
        articles, errs = fetch_binance_listing_articles(cfg)
        stats["source_errors"].extend(errs)
    detected_at = _now_iso()
    overlay: dict[str, dict[str, str]] = {}
    if cfg.enabled and cfg.manual_overlay_csv:
        try:
            overlay = load_manual_overlay(cfg.manual_overlay_csv)
        except OSError as e:
            stats["source_errors"].append(f"manual_csv:{e}")

    for r in rows:
        if not isinstance(r, dict):
            continue
        row = dict(r)
        row.pop("_intel_errors", None)
        errs: list[str] = []
        if cfg.enabled and cfg.l2a_binance_announcements and articles:
            l2a = pick_announcement_for_base(row.get("base") or "", articles, detected_at=detected_at)
            for k, v in l2a.items():
                if v is not None:
                    row[k] = v
        if cfg.enabled and cfg.manual_overlay_csv:
            merge_l2a_manual(overlay, row)
        if cfg.enabled and (
            cfg.l2a_binance_announcements or cfg.manual_overlay_csv
        ) and row.get("announcement_url"):
            stats["l2a_matched"] += 1
        if cfg.enabled and cfg.l2b_dexscreener:
            enrich_l2b_dexscreener(row, cfg)
            if row.get("onchain_first_pool_ts_ms"):
                stats["l2b_matched"] += 1
            if row.get("_intel_errors"):
                errs.extend(row.pop("_intel_errors", []))
        if cfg.enabled and cfg.l2c_dd_score:
            compute_l2c_dd_score(row, cfg)
            stats["l2c_scored"] += 1
        dlt = _delta_ms_claimed_vs_spot(row)
        if dlt is not None:
            row["listing_announcement_delta_ms"] = dlt
        if errs:
            stats["source_errors"].extend(errs)
        out_rows.append(row)

    meta.update({
        "schema_version": LISTING_INTEL_SCHEMA_VERSION,
        "extends": extends,
        "intel_stats": stats,
    })
    return {"meta": meta, "rows": out_rows}
