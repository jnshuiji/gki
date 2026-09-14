#!/system/bin/sh
MODDIR="$1"
[ -z "$MODDIR" ] && MODDIR="${0%/*}/.."

[ -f "${MODDIR}/config/pochita.conf" ] && . "${MODDIR}/config/pochita.conf"

if [ "${ENABLE_TTL:-0}" = "1" ]; then
    TTL="${TTL_VALUE:-64}"
    iptables -t mangle -D POSTROUTING -j TTL --ttl-set "$TTL" >/dev/null 2>&1
    iptables -t mangle -A POSTROUTING -j TTL --ttl-set "$TTL" >/dev/null 2>&1
    ip6tables -t mangle -D POSTROUTING -j HL --hl-set "$TTL" >/dev/null 2>&1
    ip6tables -t mangle -A POSTROUTING -j HL --hl-set "$TTL" >/dev/null 2>&1
    echo "[TTL] Outgoing packet TTL/HL set to $TTL"
else
    echo "[TTL] TTL spoofing disabled in configuration"
fi
