#!/system/bin/sh
MODDIR=${0%/*}
LOGFILE="${MODDIR}/daemon.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOGFILE"
}

# 1. 监听 Android 系统开机完成事件 (sys.boot_completed=1)
log "Pochita Companion service starting..."
until [ "$(getprop sys.boot_completed)" = "1" ]; do
    sleep 1
done
log "Android boot completed detected."

# 2. 读取配置文件
if [ -f "${MODDIR}/config/pochita.conf" ]; then
    . "${MODDIR}/config/pochita.conf"
    log "Configuration loaded."
fi

# 3. 动态遍历执行 service.d/ 下的所有子服务脚本
if [ -d "${MODDIR}/service.d" ]; then
    for s in "${MODDIR}/service.d/"*.sh; do
        if [ -f "$s" ]; then
            log "Running subservice: $(basename "$s")"
            sh "$s" "$MODDIR" >> "$LOGFILE" 2>&1
        fi
    done
fi

log "Pochita Companion service completed."
