#!/system/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Action Key Assistant - Service Boot Script for KernelSU

MODDIR=${0%/*}

# 1. 加载内核模块 (若尚未加载)
if [ ! -d "/sys/module/action_key" ]; then
    insmod "$MODDIR/action_key.ko"
fi

# 2. 检查守护进程状态，避免重复启动
if ! pgrep -f "$MODDIR/bin/action_key_daemon run" > /dev/null 2>&1; then
    # 以守护进程模式后台启动，日志重定向到 daemon.log
    "$MODDIR/bin/action_key_daemon" run >> "$MODDIR/daemon.log" 2>&1 &
fi
