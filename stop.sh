#!/usr/bin/env bash

echo "========================================"
echo "  A股自选股智能分析系统 - 一键停止"
echo "========================================"

PIDS=$(lsof -ti:8000 2>/dev/null)

if [ -z "$PIDS" ]; then
    echo "[INFO] 未找到运行中的服务进程"
    exit 0
fi

echo "[INFO] 找到服务进程: PIDs=$PIDS"
echo "[INFO] 正在停止服务..."

for PID in $PIDS; do
    echo "[INFO] 停止进程: $PID"
    kill -TERM "$PID" 2>/dev/null || kill -KILL "$PID" 2>/dev/null
done

sleep 2

PIDS=$(lsof -ti:8000 2>/dev/null)
if [ -z "$PIDS" ]; then
    echo "[SUCCESS] 服务已停止"
    exit 0
else
    echo "[ERROR] 部分进程停止失败，正在强制终止..."
    for PID in $PIDS; do
        echo "[INFO] 强制终止进程: $PID"
        kill -9 "$PID" 2>/dev/null
    done
    sleep 1
    PIDS=$(lsof -ti:8000 2>/dev/null)
    if [ -z "$PIDS" ]; then
        echo "[SUCCESS] 服务已强制停止"
        exit 0
    else
        echo "[ERROR] 服务仍在运行，PIDs=$PIDS"
        exit 1
    fi
fi