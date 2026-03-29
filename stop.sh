#!/bin/bash

# 配置文件名
PID_FILE="monitor.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    echo "🛑 正在停止监控程序 (PID: $PID)..."
    
    # 尝试优雅停止
    kill $PID
    
    # 等待一会儿确认进程结束
    sleep 2
    
    if ps -p $PID > /dev/null; then
        echo "⚠️ 进程未响应，正在强制结束..."
        kill -9 $PID
    fi
    
    # 清理 PID 文件
    rm "$PID_FILE"
    echo "✅ 监控程序已停止。"
else
    echo "ℹ️ 监控程序未在运行 (未找到 $PID_FILE 文件)。"
fi
