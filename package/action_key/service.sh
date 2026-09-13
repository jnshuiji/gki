#!/system/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Action Key Assistant - Service Boot Script for KernelSU

MODDIR=${0%/*}

# 1. 加载内核模块 (若尚未加载)
if [ ! -d "/sys/module/action_key" ]; then
    insmod "$MODDIR/action_key.ko"
fi

# 2. 挂接硬件闪光灯至 action_key_torch 触发器
for led in /sys/class/leds/*flash*/trigger; do
    if [ -f "$led" ]; then
        echo "action_key_torch" > "$led" 2>/dev/null || true
    fi
done

# 3. 单例启动用户态守护进程
if ! pgrep -f "$MODDIR/bin/action_key_daemon run" > /dev/null 2>&1; then
    "$MODDIR/bin/action_key_daemon" run >> "$MODDIR/daemon.log" 2>&1 &
fi
