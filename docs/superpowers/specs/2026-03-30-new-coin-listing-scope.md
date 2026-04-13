# 新币数据来源与边界（Listing Scope）

## 目的

定义 `--mode new` 新币观察清单使用的数据源与职责边界，避免与全量小市值翻页（`fetch_small_cap_coins`）混用，便于限速与合规排查。

## 宇宙

- **交集**：与主扫描一致，**Binance U 本位 USDT 永续**（`binanceusdm` swap）基础币种 ∩ **Binance 现货** `BASE/USDT` 可交易对。K 线与现货 ticker 仍用现货端；**上架参考日**亦为现货首根日 K（与合约上架日可能不同，以现货为 operational 定义）。
- **「新」的定义**：以 **Binance 现货该交易对首根日 K 时间戳** 为上线参考（`fetch_ohlcv(..., since=2017-01-01, limit=1)`）。若未来交易所元数据提供统一 `launchTime`，可在实现中优先采用再回退 K 线。

## 流动性

- **24h 成交额**：Binance `fetch_ticker` 的 `quoteVolume`（USDT）。
- **7 日平均**（可选）：近 7 根日 K 的 `sum(close * volume)` 作为报价币成交额近似；仅在对输出行 enrichment 或配置阈值 `min_avg_volume_7d > 0` 时使用。

## CoinGecko（与主扫描分离）

- **仅使用**：`fetch_market_caps` 分页映射（与命中列表交集），用于可选 **市值上限过滤** 与 **展示列**。
- **不使用**：`fetch_small_cap_coins` 全市场多页拉取（属于另一条数据流水线）。

## 信息收集总览

`--mode new` 产出的是**观察清单**，不是交易信号。一次运行收集的是：**交易所能直接给出的可机读事实**（上架参考时间、报价成交额、最新价、24h 涨跌幅等）+ **少量 CoinGecko 分页映射得到的市值代理** + **便于人工继续 DD 的入口链接**。

**不收集**：上所公告全文、日历事件、链上 TGE/新池、团队与融资尽调结论——这些仍属人工或其它管线。

## 采集管线（分阶段）

与实现 `scanner/new_coin.py` 中 `screen_new_listings` 一致，分为四段：

| 阶段 | 动作 | 数据源 |
| --- | --- | --- |
| 0 | 构造候选 `symbol` 列表（`BASE/USDT`） | Binance USDM `load_markets`（USDT swap）∩ Binance 现货；[`fetch_futures_symbols`](../../../scanner/kline.py) |
| 1 | 逐交易对：上架参考时间、24h 报价成交额、现价、24h 涨跌（若有） | Binance `fetch_ohlcv`（首根日 K）、`fetch_ticker` |
| 2 | 按 `sort_by` 排序；若 `max_market_cap_usd > 0` 则对**当前候选全集**拉市值并过滤 | [`fetch_market_caps`](../../../scanner/coingecko.py) |
| 3 | 截断 `top_n` 后 **enrichment**：写入市值列；若 `enrich_avg_volume_7d` 且此前未算 `avg_quote_volume_7d`，再拉日 K 补算 | CoinGecko 分页；Binance 日 K（[`fetch_klines`](../../../scanner/kline.py)） |

**请求节奏**：Binance 侧间隔由 `config.yaml` → `new_coin.request_delay` 控制；CoinGecko 由 `new_coin.coingecko_page_delay` 控制；全局 HTTPS 代理由根键 `proxy.https` 注入（见 [`main.py`](../../../main.py) `load_config`）。

## 输出字段清单（`results/new_listings_*.json`）

文件根对象为 **`{ "meta", "rows" }`**：

- **`meta`**：`collected_at`（UTC ISO8601）、`schema_version`（整数，当前为 `1`）、`mode`（`new_listings`）、`result_count`。
- **`rows`**：`screen_new_listings` 返回的列表；元素为下表字段构成的对象（`json.dump` 后 `None` 表现为 JSON `null`）。

| 键 | 来源 | 说明 |
| --- | --- | --- |
| `symbol` | 程序内 | 如 `BTC/USDT` |
| `base` | 派生自 `symbol` | 基础资产大写符号 |
| `listing_first_ts_ms` | Binance 日 K | 首根日 K 开盘时间戳（毫秒），作「上架参考」 |
| `listing_days` | 派生 | 相对运行时刻估算的上架后天数 |
| `price` | Binance ticker | `last` 或 `close` |
| `quote_volume_24h` | Binance ticker | USDT 计价的 24h 成交额 |
| `avg_quote_volume_7d` | Binance 日 K（可选） | 近 7 根日 K 的 `sum(close * volume)` 近似；筛选阶段仅当 `min_avg_volume_7d > 0` 时必算；否则可能为 `null`，在阶段 3 按配置补算 |
| `change_24h_pct` | Binance ticker | `percentage`/`100`；交易所未给时为 `null` |
| `coingecko_search_url` | 派生 | CoinGecko 搜索入口（非官方 id 链接） |
| `binance_spot_url` | 派生 | Binance 现货交易页深链 |
| `market_cap_usd` | CoinGecko | 写入前默认为 `0`；`enrich_market_cap` 时用分页映射填充；**未命中映射则为 `0`**（见下节） |

CLI 表格列是上述字段的子集映射，以终端可读性为准。

## 已知局限（歧义与失败）

- **首根日 K vs 公告上线日**：运营上的「上新」以交易所首根日 K 为 **operational 定义**，与新闻稿/公告时刻可能不一致（迁移、极少数接口边界情况）。
- **CoinGecko `symbol → market_cap`**：`fetch_market_caps` 按大写 `symbol` 在分页结果中匹配；**同名符号多项目**时可能错配或漏配。字段 `market_cap_usd` 为 `0` 表示「本轮分页未解析到」，**不得**解读为真实市值为零。
- **429 / 网络 / 单币失败**：实现对单笔请求失败多采取跳过（`continue`），不中断整次扫描；结果偏少时应检查代理、`request_delay`、CoinGecko 限速。

## L0 / L1 产品对齐（当前 vs 后续）

- **L0（当前实现）**：上表所列字段 + CoinGecko **搜索 URL**（非 `coins/{id}`）+ Binance 现货深链 + 分页 **市值代理**。
- **L1（未实现）**：若需 `public_interest`、分类、`atl_date` 或官网/社交等，需引入 **CoinGecko `id` 消歧**（或其它权威 id），并单独评估 API 成本与字段表格；**本 spec 不包含已实现 L1 字段列表**，避免与代码不同步。

## 未覆盖（计划外）

以下能力**不在 L0/L1 `--mode new` 的实现范围内**，但在此给出**产品与数据设计**，便于后续单独立项、与观察清单对接，避免与 `screen_new_listings` 混线。

### 分层与边界

| 代号 | 能力 | 与 `new_listings` 关系 |
| --- | --- | --- |
| **L2a** | 上所公告 / 上市日历 | 平行数据管线；可按 `base` 或 `symbol` 与 `rows` **左连接** enrich |
| **L2b** | 链上 TGE / 新池 / 首发池 | 平行管线；时间轴与「现货首根日 K」可能不一致，**不得**覆盖 `listing_first_ts_ms` 语义 |
| **L2c** | 项目可信度 / 实力分 | 派生指标；输入为 L0+L1+L2a/L2b 的聚合与可选人工标注 |

**原则**：L0 清单继续只产出交易所可机读事实 + 可选 CoinGecko 分页市值；L2 只通过 **enrichment 层** 或 **二次产物** 扩展，不扩大单次 Binance/CoinGecko 必需调用集。

### L2a：上所公告 / 日历

- **要回答的问题**：该交易对是否有官方「将上线/已上线」记录？公告时间与首根日 K 差多少？
- **候选数据源（择一并评估合规）**：
  - **交易所官方**：RSS/HTML 公告列表、状态页、API（若有）；需独立爬虫或轮询任务，与 `scanner/new_coin.py` **不同进程/不同配置节**（如 `listing_intel.exchange_announcements`）。
  - **聚合日历**：第三方加密日历站点（多为非官方二次分发）；仅作**交叉验证**，不作为唯一真理源。
- **建议最小 schema（enrichment 行，按 `base` join）**：
  - `announcement_detected_at`（我方采集时间，UTC ISO8601）
  - `announcement_title_snippet`（截断明文，避免存全文版权风险）
  - `announcement_url`（官方链接优先）
  - `claimed_listing_at`（若公告能解析出「上线时刻」；解析失败为 `null`）
  - `source`（`binance_official` / `aggregator` / `manual`）
  - `confidence`（`high` / `medium` / `low`，解析模糊或仅标题命中时为 `low`）
- **与 L0 对齐**：`listing_first_ts_ms` 仍为 operational 定义；L2a 仅在输出或单独 JSON 中增加 **△公告 vs 首 K** 等派生列，避免混用为排序主键。

### L2b：链上 TGE / 新池

- **要回答的问题**：代币生成事件、首发池创建、主要 DEX 首池时间；与 CEX 现货可能有时差或多所顺序。
- **候选数据源**：
  - **索引服务**：The Graph 子图、Dune/Flipside 等查询、区块浏览器标签 API；成本与延迟高于 REST。
  - **第三方「新池」聚合**：需评估误报（同名钓鱼池、迁移后旧池）。
- **建议最小 schema（按 `base` 或合约地址 join，二选一作为主键）**：
  - `chain`（如 `eth`, `bsc`, `base`）
  - `tge_tx` / `pool_created_tx`（可辨别的交易哈希或事件 id）
  - `tge_ts_ms` / `first_pool_ts_ms`
  - `dex_or_protocol`
  - `token_contract`（若与 `base` 映射需维护(symbol, chain) → 地址表）
- **约束**：链上时间**不写入** `listing_first_ts_ms`；如需展示，用新键如 `onchain_first_liquidity_ts_ms`，并在 `meta` 或行内标注 `cex_spot_listing_ts_ms` 并存。

### L2c：项目方实力 / 可信度分

- **要回答的问题**：在同等流动性下，是否更值得人工深查（非买卖建议）。
- **输入（.machine-readable）**：L0 字段 + `market_cap_usd`（已警示同名错配）+ 可选 L2a/L2b + CoinGecko `id` 消歧后的少量公开字段（团队链接、分类）——**对齐 L1 spec 中「需 id 消歧」前提**。
- **输出形态**：**禁止**在 L0 单独跑通路径上隐式改排序；建议：
  - `trust_tier`：`unscored` | `tier_1` …（产品命名待定），或
  - `dd_score`：0–100 整数 + `score_components` 对象（可解释性）
- **治理**：规则引擎（YAML/JSON 阈值）优先于黑盒模型；若引入 ML，须独立版本化与审计字段。

### 集成模式（实现时三选一或组合）

1. **离线 enrich**：批处理读取 `results/new_listings_*.json` 的 `rows`，写出 `results/new_listings_enriched_*.json`（根结构可复用 `meta` + `rows`，`meta.schema_version` 递增并写 `extends: ["l2a"]`）。
2. **配置开关子命令**：如 `python main.py --mode new --intel announcements` 仅在单独 PR 中接入，且默认关闭。
3. **人工 overlay**：CSV/表格按 `base` 合并（用例：内部备忘录、临时标记），不进入主 repo 流水线。

### 合规与运维（计划外共性）

- ** robots / ToS**：爬虫与第三方 API 须在配置中可切换关闭；默认不抓取全文公告，仅标题+链接+时间。
- **限速与失败**：与 `new_coin.request_delay` 分离；失败策略为「该 enrich 字段为空」，不拖累主清单为空。
- **可观测性**：enrichment 任务应记录 `rows_attempted` / `rows_matched` / `source_errors`，便于发现 429 或解析退化。

## CLI

- `python main.py --mode new` 读取 `config.yaml` 的 `new_coin` 段。
- 不产生 `TradeSignal` / 止损止盈列；结果写入 `results/new_listings_*.json`（根为 `meta` + `rows`，解析时请读 `rows`；旧版仅数组的脚本需迁移）。
