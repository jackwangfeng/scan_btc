#!/bin/bash

# 配置文件名
PYTHON_SCRIPT="monitor.py"
PID_FILE="monitor.pid"
LOG_FILE="monitor.log"

# 检查是否已经在运行
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p $PID > /dev/null; then
        echo "⚠️ 监控程序已经在运行中 (PID: $PID)"
        exit 1
    else
        rm "$PID_FILE"
    fi
fi

echo "🚀 正在后台启动 BTC 监控工具..."
nohup python3 $PYTHON_SCRIPT > $LOG_FILE 2>&1 &

echo $! > "$PID_FILE"

echo "✅ 启动成功！"
echo "   - PID: $(cat $PID_FILE)"
echo "   - 日志文件: $LOG_FILE (使用 'tail -f $LOG_FILE' 查看日志)"

if grep -q "ENABLE_WEB_UI=true" .env 2>/dev/null; then
    PORT=$(grep "WEB_UI_PORT=" .env | cut -d= -f2)
    PORT=${PORT:-5000}
    echo "   - Web UI: http://localhost:$PORT"
fi
