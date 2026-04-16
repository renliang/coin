#!/usr/bin/env bash
#
# Coin Quant 一键部署脚本
# 用法: 在服务器上执行
#   curl -fsSL <raw-url>/deploy.sh | bash
#   或: git clone <repo> && cd coin && bash deploy.sh
#
set -euo pipefail

# ── 颜色 ──
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*"; exit 1; }

# ── Step 1: 检查系统 ──
log "检查系统环境..."

if ! command -v docker &>/dev/null; then
    warn "Docker 未安装，正在安装..."
    curl -fsSL https://get.docker.com | sh
    sudo systemctl enable docker
    sudo systemctl start docker
    sudo usermod -aG docker "$USER"
    log "Docker 已安装。如果提示权限问题，请重新登录后再运行此脚本。"
fi

if ! docker compose version &>/dev/null; then
    err "Docker Compose 不可用，请确认 Docker 版本 >= 24.0"
fi

log "Docker $(docker --version | awk '{print $3}') ✓"

# ── Step 2: 配置 ──
if [ ! -f .env.prod ]; then
    warn ".env.prod 不存在，从模板创建..."
    cp .env.prod.example .env.prod
    warn "请编辑 .env.prod 填入你的 API Keys:"
    warn "  nano .env.prod"
    warn "填好后重新运行: bash deploy.sh"
    exit 0
fi

# 检查必填项
source .env.prod
if [ -z "${BINANCE_API_KEY:-}" ] || [ "${BINANCE_API_KEY}" = "your_api_key_here" ]; then
    err ".env.prod 中 BINANCE_API_KEY 未设置，请先编辑: nano .env.prod"
fi

log ".env.prod 配置 ✓"

# ── Step 3: 修改 config.yaml（清空代理） ──
if grep -q "https: http" config.yaml 2>/dev/null; then
    warn "检测到本地代理配置，生产环境不需要代理"
    sed -i 's|https: http://127.0.0.1:[0-9]*|https: ""|g' config.yaml
    log "已清空 config.yaml 中的代理设置"
fi

# ── Step 4: 创建数据目录 ──
mkdir -p data logs results
log "数据目录 ✓"

# ── Step 5: 构建 & 启动 ──
log "开始构建 Docker 镜像（首次需要几分钟）..."
docker compose build --no-cache

log "启动服务..."
docker compose up -d

# ── Step 6: 健康检查 ──
log "等待服务启动..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/api/config >/dev/null 2>&1; then
        log "服务已启动 ✓"
        break
    fi
    if [ "$i" -eq 30 ]; then
        err "服务启动超时，查看日志: docker compose logs"
    fi
    sleep 1
done

# ── Step 7: 验证 ──
echo ""
log "═══════════════════════════════════════"
log "  Coin Quant 部署成功！"
log "═══════════════════════════════════════"
echo ""
echo "  API:      http://$(hostname -I | awk '{print $1}'):8000"
echo "  Web UI:   http://$(hostname -I | awk '{print $1}'):8000/app/"
echo "  API Docs: http://$(hostname -I | awk '{print $1}'):8000/docs"
echo ""
echo "  常用命令:"
echo "    docker compose logs -f          # 查看日志"
echo "    docker compose restart          # 重启"
echo "    docker compose down             # 停止"
echo "    docker compose up -d --build    # 重新构建并启动"
echo ""

# ── Step 8: 测试币安连接 ──
log "测试币安 API 连接..."
BINANCE_TEST=$(curl -sf "https://api.binance.com/api/v3/ping" && echo "ok" || echo "fail")
if [ "$BINANCE_TEST" = "ok" ]; then
    log "币安 API 连接正常 ✓"
else
    warn "币安 API 无法连接。请确认服务器所在地区可以访问 api.binance.com"
fi
