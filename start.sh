#!/usr/bin/env bash

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "========================================"
echo "  A股自选股智能分析系统 - 一键启动"
echo "========================================"

if [ ! -d "venv" ]; then
    echo "[ERROR] 虚拟环境不存在，请先运行: python3 -m venv venv"
    exit 1
fi

echo "[INFO] 激活虚拟环境..."
source venv/bin/activate

echo "[INFO] 启动后端服务..."
echo "[INFO] 服务地址: http://127.0.0.1:8000"
echo "[INFO] 按 Ctrl+C 停止服务"
echo ""

python main.py --serve