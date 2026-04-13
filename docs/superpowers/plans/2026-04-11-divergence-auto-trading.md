# MACD 底背离自动交易系统 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将底背离设为主模式，接入币安合约自动挂单，每天8点定时执行

**Architecture:** 新建 scanner/trader/ 子包处理交易执行，APScheduler 内嵌调度，PM2 守护进程

**Tech Stack:** Python 3.13, ccxt (合约下单), APScheduler (调度), SQLite (订单/持仓记录)

---

### Task 1: 新增依赖 + 默认模式改为 divergence

**Files:**
- Modify: `requirements.txt`
- Modify: `main.py:792-793`

- [ ] Step 1: requirements.txt 添加 apscheduler
- [ ] Step 2: main.py argparse default 改为 "divergence"
- [ ] Step 3: 验证 `python main.py --help` 显示 default=divergence

---

### Task 2: config.yaml 新增 trading + schedule 配置

**Files:**
- Modify: `config.yaml`
- Modify: `main.py` (load_config 解析新字段)

- [ ] Step 1: config.yaml 添加 trading 和 schedule 段
- [ ] Step 2: main.py load_config() 解析 trading/schedule 配置并返回

---

### Task 3: kline.py 新增认证交易所实例

**Files:**
- Modify: `scanner/kline.py`
- Test: `tests/test_kline_auth.py`

- [ ] Step 1: 写测试 — 验证 get_authed_usdm() 带 apiKey/secret
- [ ] Step 2: kline.py 新增 get_authed_usdm(api_key, api_secret, proxy) 函数
- [ ] Step 3: 运行测试验证通过

---

### Task 4: tracker.py 新增 orders + positions 表

**Files:**
- Modify: `scanner/tracker.py`
- Test: `tests/test_tracker_trading.py`

- [ ] Step 1: 写测试 — save_order / update_order_status / save_position / get_open_positions / get_pending_orders
- [ ] Step 2: tracker.py 新增建表 + CRUD 函数
- [ ] Step 3: 运行测试验证通过

---

### Task 5: scanner/trader/sizing.py — 仓位计算

**Files:**
- Create: `scanner/trader/__init__.py`
- Create: `scanner/trader/sizing.py`
- Test: `tests/test_sizing.py`

- [ ] Step 1: 写测试 — 评分→仓位%映射 + 下单数量计算
- [ ] Step 2: 实现 calculate_position_size(balance, signal, score_sizing) 和 get_max_leverage(exchange, symbol)
- [ ] Step 3: 运行测试验证通过

---

### Task 6: scanner/trader/position.py — 仓位管理

**Files:**
- Create: `scanner/trader/position.py`
- Test: `tests/test_position.py`

- [ ] Step 1: 写测试 — 过滤已持有 + 卡上限 + 按评分排序
- [ ] Step 2: 实现 filter_signals(exchange, signals, max_positions)
- [ ] Step 3: 运行测试验证通过

---

### Task 7: scanner/trader/executor.py — 下单执行

**Files:**
- Create: `scanner/trader/executor.py`
- Test: `tests/test_executor.py`

- [ ] Step 1: 写测试 — 下单流程（set_leverage → limit → TPSL）+ TPSL 失败撤主单
- [ ] Step 2: 实现 execute_trade(exchange, signal, size, leverage, db_path) 含异常处理
- [ ] Step 3: 运行测试验证通过

---

### Task 8: scanner/trader/monitor.py — 超时检查

**Files:**
- Create: `scanner/trader/monitor.py`
- Test: `tests/test_monitor.py`

- [ ] Step 1: 写测试 — 超时转市价 + 已成交更新 + TPSL 触发检查
- [ ] Step 2: 实现 check_orders(exchange, timeout_minutes, db_path)
- [ ] Step 3: 运行测试验证通过

---

### Task 9: main.py --serve 模式 + APScheduler

**Files:**
- Modify: `main.py`

- [ ] Step 1: 新增 run_serve() 函数 — 初始化 APScheduler，注册定时任务
- [ ] Step 2: argparse 新增 --serve flag
- [ ] Step 3: 整合：扫描完成后如果 trading.enabled → 调用 trader 管线
- [ ] Step 4: 手动测试 --serve 启动和调度

---

### Task 10: PM2 配置 + 日志

**Files:**
- Create: `ecosystem.config.js`
- Modify: `main.py` (print → logging)

- [ ] Step 1: 创建 ecosystem.config.js
- [ ] Step 2: main.py 核心路径加 logging（trader 部分）
- [ ] Step 3: 验证 pm2 start ecosystem.config.js
