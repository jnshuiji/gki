#!/sbin/sh
SKIPUNZIP=0

ui_print "************************************************"
ui_print "*          Pochita Kernel Companion            *"
ui_print "*       Extensible GKI Companion Service       *"
ui_print "************************************************"

ui_print "- 正在配置伴侣服务权限..."
set_perm_recursive "$MODPATH/service.d" 0 0 0755 0755
set_perm_recursive "$MODPATH/config" 0 0 0755 0644
set_perm "$MODPATH/service.sh" 0 0 0755
set_perm "$MODPATH/action.sh" 0 0 0755

ui_print "- Pochita 伴侣模块安装成功！"
