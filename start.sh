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
        # 如果 PID 文件存在但进程不在，清理掉
        rm "$PID_FILE"
    fi
fi

# 启动程序
echo "🚀 正在后台启动 BTC 监控工具..."
nohup python3 $PYTHON_SCRIPT > $LOG_FILE 2>&1 &

# 保存 PID
echo $! > "$PID_FILE"

echo "✅ 启动成功！"
echo "   - PID: $(cat $PID_FILE)"
echo "   - 日志文件: $LOG_FILE (使用 'tail -f $LOG_FILE' 查看日志)"
