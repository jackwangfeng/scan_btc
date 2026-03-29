#!/bin/bash

# 配置文件名
PID_FILE="monitor.pid"
LOG_FILE="monitor.log"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p $PID > /dev/null; then
        echo "✅ 监控程序运行中 (PID: $PID)"
        echo "--- 最近 5 行日志 ($LOG_FILE): ---"
        tail -n 5 "$LOG_FILE"
        echo "----------------------------"
    else
        echo "⚠️ PID 文件存在但进程 $PID 未在运行。"
    fi
else
    echo "ℹ️ 监控程序未在后台运行。"
fi
