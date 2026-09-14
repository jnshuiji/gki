#!/system/bin/sh
MODDIR="$1"
[ -z "$MODDIR" ] && MODDIR="${0%/*}/.."

[ -f "${MODDIR}/config/pochita.conf" ] && . "${MODDIR}/config/pochita.conf"

if [ "${ENABLE_BBR:-1}" = "1" ]; then
    if grep -q "bbr" /proc/sys/net/ipv4/tcp_available_congestion_control 2>/dev/null; then
        sysctl -w net.ipv4.tcp_congestion_control=bbr >/dev/null 2>&1
        echo "[BBR] TCP congestion control successfully set to BBR"
    else
        echo "[BBR] Warning: bbr not listed in tcp_available_congestion_control"
    fi
else
    echo "[BBR] BBR optimization disabled in configuration"
fi
