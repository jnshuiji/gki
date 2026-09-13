#!/system/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Action Key Assistant - Action button trigger for KernelSU Manager

MODDIR=${0%/*}

# 执行一次模拟单击测试
"$MODDIR/bin/action_key_daemon" test short
