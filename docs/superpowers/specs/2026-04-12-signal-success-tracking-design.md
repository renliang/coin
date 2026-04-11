# 信号成功率追踪设计

## 背景

当前系统在 `--serve` 模式下自动下单后，`positions` 表仅记录 `closed_at` 时间戳，缺少退出价格、盈亏和退出原因。无法分析信号的实际表现和成功率。

## 目标

1. 关仓时自动记录退出价格、盈亏、退出原因
2. 提供多维度成功率分析：按模式、评分区间、时间
3. CLI 表格输出 + JSON 导出

## 数据层改动

### positions 表新增列

| 列 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `exit_price` | REAL | NULL | 退出价格 |
| `pnl` | REAL | NULL | 绝对盈亏 (USDT) |
| `pnl_pct` | REAL | NULL | 百分比盈亏（如 0.05 = +5%） |
| `exit_reason` | TEXT | NULL | `tp` / `sl` / `manual` |
| `mode` | TEXT | '' | `accumulation` / `divergence` / `breakout` |

### 迁移策略

在 `tracker.py` 的 `_init_db()` 中用 `ALTER TABLE ADD COLUMN IF NOT EXISTS` 逐列添加，兼容已有数据库。

### mode 字段来源

`save_position()` 调用时从 `TradeSignal.mode` 传入。现有 `execute_trade()` 已持有 signal 对象，直接传递。

## 关仓逻辑改动（monitor.py）

### check_positions() 变更

当检测到仓位关闭（交易所无对应持仓）时：

1. 查询 TP 订单状态（`tp_order_id`）：
   - 若 `status='filled'` → `exit_reason='tp'`，`exit_price` = 该订单的 TP 价格（从 positions 表的关联信号中获取，或从订单表取 price 字段）
2. 否则查询 SL 订单状态（`sl_order_id`）：
   - 若 `status='filled'` → `exit_reason='sl'`，`exit_price` = SL 价格
3. 两者都未 filled → `exit_reason='manual'`，`exit_price` = 当前市价（`fetch_ticker`）
4. 计算 PnL：
   - Long: `pnl_pct = (exit_price - entry_price) / entry_price`
   - Short: `pnl_pct = (entry_price - exit_price) / entry_price`
   - `pnl = pnl_pct * entry_price * size`
5. 调用 `close_position()` 时写入 `exit_price`, `pnl`, `pnl_pct`, `exit_reason`

### TP/SL 订单状态同步

`check_orders()` 已有逻辑同步订单状态（查交易所、更新 filled/cancelled）。`check_positions()` 在其之后运行，可直接读取已更新的订单状态。若订单状态尚未同步，通过 `order_id` 直接查交易所确认。

## 分析模块（新建 scanner/stats.py）

### 函数设计

```python
def compute_stats(trades: list[dict]) -> dict:
    """从已关仓交易列表计算统计指标。"""
    # 返回: total, wins, win_rate, avg_pnl_pct, profit_factor, max_gain, max_loss

def compute_stats_by_mode(trades: list[dict]) -> dict[str, dict]:
    """按 mode 分组计算统计。"""

def compute_stats_by_score_tier(trades: list[dict]) -> dict[str, dict]:
    """按评分区间分组: 0.6-0.7, 0.7-0.8, 0.8+。"""

def compute_stats_by_month(trades: list[dict]) -> dict[str, dict]:
    """按 YYYY-MM 分组计算统计。"""

def get_closed_trades() -> list[dict]:
    """从 positions 表查询所有 status='closed' 且 pnl_pct IS NOT NULL 的记录。"""

def format_stats_report(overall, by_mode, by_score, by_month) -> str:
    """格式化为终端表格字符串。"""

def export_stats_json(overall, by_mode, by_score, by_month) -> str:
    """导出为 JSON 并写入 results/ 目录，返回文件路径。"""
```

### 统计指标

每个分组包含：

| 指标 | 说明 |
|---|---|
| `total` | 总交易数 |
| `wins` | 盈利交易数（pnl_pct > 0） |
| `win_rate` | 胜率 (wins / total) |
| `avg_pnl_pct` | 平均百分比盈亏 |
| `profit_factor` | 总盈利 / 总亏损的绝对值 |
| `max_gain` | 最大单笔盈利 % |
| `max_loss` | 最大单笔亏损 % |

## CLI 接口

### 命令

```bash
python main.py --stats              # 打印统计表格 + 导出 JSON
python main.py --stats --json-only  # 仅导出 JSON，不打印
```

### 输出格式

```
=== 信号成功率统计 ===
总交易: 47  |  胜率: 63.8%  |  平均盈亏: +2.1%  |  盈亏比: 1.52

[按模式]
模式            交易数    胜率     平均盈亏    盈亏比
divergence        28    67.9%    +2.8%      1.68
accumulation      15    60.0%    +1.5%      1.35
breakout           4    50.0%    +0.8%      1.10

[按评分]
评分区间        交易数    胜率     平均盈亏    盈亏比
0.8+              12    75.0%    +3.2%      2.10
0.7-0.8           20    65.0%    +2.1%      1.55
0.6-0.7           15    53.3%    +0.8%      1.05

[按月份]
月份          交易数    胜率     平均盈亏    盈亏比
2026-04         23    65.2%    +2.3%      1.60
2026-03         24    62.5%    +1.9%      1.45

[导出] results/stats_20260412_120000.json
```

### JSON 格式

```json
{
  "generated_at": "2026-04-12 12:00:00",
  "overall": {
    "total": 47, "wins": 30, "win_rate": 0.638,
    "avg_pnl_pct": 0.021, "profit_factor": 1.52,
    "max_gain": 0.089, "max_loss": -0.048
  },
  "by_mode": {
    "divergence": { ... },
    "accumulation": { ... },
    "breakout": { ... }
  },
  "by_score_tier": {
    "0.8+": { ... },
    "0.7-0.8": { ... },
    "0.6-0.7": { ... }
  },
  "by_month": {
    "2026-04": { ... },
    "2026-03": { ... }
  },
  "trades": [
    {
      "symbol": "ETH/USDT", "mode": "divergence", "side": "long",
      "score": 0.75, "entry_price": 3200.0, "exit_price": 3456.0,
      "pnl_pct": 0.08, "pnl": 25.6, "exit_reason": "tp",
      "opened_at": "2026-04-01 08:10:00", "closed_at": "2026-04-03 14:22:00"
    }
  ]
}
```

## 文件改动清单

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `scanner/tracker.py` | 修改 | positions 表加 5 列；`close_position()` 接受 exit 参数；`get_closed_trades()` 查询 |
| `scanner/trader/executor.py` | 修改 | `save_position()` 传入 mode 字段 |
| `scanner/trader/monitor.py` | 修改 | `check_positions()` 关仓时推断 exit_reason/price，算 PnL |
| `scanner/stats.py` | 新建 | 统计计算 + 格式化 + JSON 导出 |
| `main.py` | 修改 | 加 `--stats` argparse 入口 |
| `tests/test_stats.py` | 新建 | stats 模块单元测试 |
| `tests/test_trader_db.py` | 修改 | close_position 新参数测试 |
| `config.yaml` | 不改 | 无新配置项 |
