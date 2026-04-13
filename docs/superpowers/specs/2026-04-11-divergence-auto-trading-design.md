# MACD 底背离自动交易系统设计

> 日期: 2026-04-11
> 状态: 设计中

## 目标

将 MACD 底背离设为主扫描模式，接入币安合约（USDM 永续）实现自动挂单，每天 8:00 定时执行。

## 需求总结

| 项目 | 决策 |
|------|------|
| 主模式 | MACD 底背离（divergence） |
| 交易市场 | 币安 USDM 永续合约 |
| 订单类型 | 限价单 + 30 分钟超时转市价 |
| 止损止盈 | 交易所 TPSL 委托单（下单时同步挂） |
| 杠杆 | 各币种交易所允许的最大杠杆 |
| 仓位 | 按评分动态调（2%~5% 可用余额） |
| 持仓上限 | 最多 N 个同时持仓（默认 5） |
| 调度 | APScheduler 常驻 + PM2 守护 |
| API Key | 环境变量优先，config.yaml 兜底 |

## 架构

```
每天 08:00 (APScheduler + PM2 守护)
    │
    ▼
main.py --serve              # 常驻模式，内嵌调度器
    │
    ├─ run_divergence()       # 底背离扫描（主模式）
    │   └─ 返回 List[TradeSignal]
    │
    ▼
scanner/trader/
    ├─ sizing.py              # 评分 → 仓位%(2~5%) + 杠杆(max)
    ├─ position.py            # 查当前持仓数，过滤已持有，卡上限
    ├─ executor.py            # 开仓：限价单 + TPSL → 记录 DB
    └─ monitor.py             # 每分钟：限价超时(30min) → 转市价或撤单
```

### 数据流

```
信号列表 → position 过滤(已持有/超上限) → sizing 计算仓位
→ executor 下单(限价+TPSL) → tracker 记录 → monitor 超时检查
```

## 模块设计

### sizing.py — 仓位计算

评分区间到仓位百分比（占可用余额）的映射：

| 评分区间 | 仓位百分比 |
|---------|-----------|
| 0.60 ~ 0.69 | 2% |
| 0.70 ~ 0.79 | 3% |
| 0.80 ~ 0.89 | 4% |
| 0.90 ~ 1.00 | 5% |

杠杆：通过 API 查询该币种合约允许的最大杠杆，直接使用最大值。

输入：账户可用余额 + TradeSignal。输出：下单数量(contracts) + 杠杆倍数。

### position.py — 仓位管理

1. 查交易所当前持仓列表（不本地维护，每次直接查交易所，避免不一致）
2. 过滤：信号中已持有的币 → 跳过
3. 卡上限：当前持仓数 >= max_positions → 按评分排序只取空余名额

### executor.py — 下单执行

单笔下单流程：

1. 设置杠杆 → `set_leverage(symbol, max_leverage)`
2. 限价开仓 → `create_order(symbol, 'limit', 'buy', amount, entry_price)`
3. 挂 TPSL：
   - `create_order(symbol, 'TAKE_PROFIT_MARKET', tp_price)`
   - `create_order(symbol, 'STOP_MARKET', sl_price)`
4. 记录到 orders 表（order_id, symbol, status='open', created_at）

方向判断：底背离 → 做多（buy/long），顶背离 → 做空（sell/short），根据 signal_type 自动判断。

### monitor.py — 超时检查

每 1 分钟轮询一次：

1. 查 orders 表中 status='open' 且 created_at 超过 30 分钟的限价单
2. 查交易所订单状态：
   - 已成交 → 更新 status='filled'
   - 未成交且超时 → 撤单 → 市价补单 → 重新挂 TPSL
   - 部分成交 → 撤剩余 → 对已成交部分挂 TPSL
3. 检查 TPSL 是否触发 → 触发则更新持仓状态为 'closed'

## 数据库扩展

在现有 scanner.db 中新增两张表：

### orders 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| order_id | TEXT | 交易所订单 ID |
| symbol | TEXT | 交易对 |
| side | TEXT | buy/sell |
| order_type | TEXT | limit/market |
| price | REAL | 委托价格 |
| amount | REAL | 委托数量 |
| leverage | INTEGER | 杠杆倍数 |
| status | TEXT | open/filled/cancelled/timeout_converted |
| related_order_id | TEXT | 超时转市价时关联原单 ID |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

### positions 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| symbol | TEXT | 交易对 |
| side | TEXT | long/short |
| entry_price | REAL | 入场价 |
| size | REAL | 持仓量 |
| leverage | INTEGER | 杠杆倍数 |
| score | REAL | 信号评分 |
| tp_order_id | TEXT | 止盈订单 ID |
| sl_order_id | TEXT | 止损订单 ID |
| status | TEXT | open/closed |
| opened_at | TEXT | 开仓时间 |
| closed_at | TEXT | 平仓时间 |

## config.yaml 新增

```yaml
trading:
  enabled: true                       # 总开关，false 只扫描不下单
  api_key_env: BINANCE_API_KEY        # 环境变量名
  api_secret_env: BINANCE_API_SECRET
  max_positions: 5                    # 最大同时持仓数
  order_timeout_minutes: 30           # 限价单超时时间
  score_sizing:                       # 评分 → 仓位百分比映射
    0.6: 0.02
    0.7: 0.03
    0.8: 0.04
    0.9: 0.05

schedule:
  scan_time: "08:00"                  # 每日扫描时间
  monitor_interval: 60                # 订单监控间隔(秒)
```

## main.py 改动

1. `--mode` 默认值改为 `divergence`
2. 新增 `--serve` 模式：启动 APScheduler 常驻进程
   - 每天 scan_time → run_divergence() → 自动下单
   - 每 monitor_interval 秒 → monitor 检查订单
3. 信号生成后，如果 trading.enabled=true → 走 trader 管线

## 异常处理

| 异常场景 | 处理方式 |
|---------|---------|
| API 连接失败 | 重试 3 次，间隔 5s，全失败记日志跳过 |
| 余额不足 | 跳过该信号，记日志，继续下一个 |
| 杠杆设置失败 | 降到交易所返回的最大允许值重试 |
| 限价单下单失败 | 记日志，不挂 TPSL，跳过 |
| TPSL 挂单失败 | 重试 2 次，仍失败则撤主单，记日志告警 |
| 超时转市价失败 | 记日志，保留原限价单不动 |
| 持仓查询失败 | 本轮不下单，等下次调度 |

### 关键原则

- **宁可不开仓，也不开裸仓**：没有 TPSL 的仓位不允许存在
- TPSL 挂失败 → 必须撤掉主单
- 所有下单操作记录到 DB，方便事后审计

## 日志

```
logs/
├── scanner.log     # 扫描日志（现有 print 改为 logging）
└── trader.log      # 交易日志（下单、撤单、成交、异常）
```

Python logging 模块，按天轮转，保留 30 天。

## PM2 部署

```javascript
// ecosystem.config.js
module.exports = {
  apps: [{
    name: "coin-scanner",
    script: ".venv/bin/python",
    args: "main.py --serve",
    autorestart: true,
    max_restarts: 10,
    restart_delay: 5000
  }]
}
```

PM2 职责：保活 + 崩溃重启。APScheduler 职责：定时扫描 + 订单监控。

## 依赖新增

```
apscheduler>=3.10.0    # 定时调度
```

ccxt 已有，无需额外安装即可支持合约下单。

## 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新增 | scanner/trader/__init__.py | 包初始化 |
| 新增 | scanner/trader/sizing.py | 评分→仓位/杠杆计算 |
| 新增 | scanner/trader/position.py | 持仓查询与过滤 |
| 新增 | scanner/trader/executor.py | 下单执行（限价+TPSL） |
| 新增 | scanner/trader/monitor.py | 订单超时检查与转换 |
| 修改 | scanner/tracker.py | 新增 orders + positions 表 |
| 修改 | scanner/kline.py | 新增认证交易所实例（带 API Key） |
| 修改 | main.py | 默认 divergence + --serve 模式 |
| 修改 | config.yaml | 新增 trading + schedule 配置段 |
| 修改 | requirements.txt | 新增 apscheduler |
| 新增 | ecosystem.config.js | PM2 配置 |
