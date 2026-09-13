#!/sbin/sh
# SPDX-License-Identifier: GPL-2.0
# Action Key Assistant - Installation Script

SKIPUNZIP=0

ui_print "************************************************"
ui_print "*             Action Key Assistant             *"
ui_print "*    Kernel Netlink IPC, Rust Daemon & WebUI   *"
ui_print "*          Target: Linux 6.12 GKI             *"
ui_print "************************************************"

ui_print "- 配置可执行权限..."
set_perm_recursive "$MODPATH/bin" 0 0 0755 0755
set_perm "$MODPATH/service.sh" 0 0 0755
set_perm "$MODPATH/action.sh" 0 0 0755
set_perm "$MODPATH/action_key.ko" 0 0 0644

ui_print "- 初始化默认手势配置文件 (单击 / 双击 / 长按)..."
"$MODPATH/bin/action_key_daemon" config get > "$MODPATH/config.json" 2>/dev/null || true

ui_print "- 安装成功！请在 KernelSU 管理器中重启手机以生效。"
