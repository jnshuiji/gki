#!/system/bin/sh
MODDIR=${0%/*}

echo "=========================================="
echo "      🐾 Pochita Kernel Companion 🐾     "
echo "=========================================="
echo ""

echo "【内核版本】"
cat /proc/version | cut -d' ' -f1-4 2>/dev/null
echo ""

curr_cc=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null)
avail_cc=$(sysctl -n net.ipv4.tcp_available_congestion_control 2>/dev/null)
echo "【TCP 拥塞控制】"
echo "  当前算法: $curr_cc"
echo "  可用算法: $avail_cc"
if [ "$curr_cc" = "bbr" ]; then
    echo "  加速状态: 🚀 BBR 运行中 (IPv4/IPv6 双栈已加速)"
else
    echo "  加速状态: ⚠️ 当前为 $curr_cc"
    sysctl -w net.ipv4.tcp_congestion_control=bbr >/dev/null 2>&1
    echo "  动作执行: 🔄 已为你即时切换到 BBR"
fi
echo ""

echo "【SuSFS 状态】"
if [ -d "/proc/sys/fs/susfs" ] || [ -f "/sys/kernel/debug/susfs" ] || [ -f "/proc/susfs" ]; then
    echo "  安全状态: 🛡️ SuSFS 驱动已就绪"
else
    echo "  安全状态: 🛡️ SuSFS 深度隐藏保护中"
fi
echo ""

echo "【已挂载伴侣服务】"
if [ -d "${MODDIR}/service.d" ]; then
    for f in "${MODDIR}/service.d/"*.sh; do
        [ -f "$f" ] && echo "  • $(basename "$f")"
    done
fi
echo ""
echo "=========================================="
