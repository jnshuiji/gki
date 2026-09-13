// SPDX-License-Identifier: GPL-2.0
/*
 * Action Key Assistant - Dedicated Netlink IPC Subsystem
 *
 * 本源文件独立负责 Linux Netlink 套接字的生命周期维护与事件广播。
 * 完全解耦于 input_bridge.c（输入子系统挂钩），专注处理内核到用户态通信。
 *
 * Architecture:
 *   Rust dispatch_gesture() -> action_key_netlink_send() -> netlink_broadcast() -> Daemon
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/netlink.h>
#include <linux/skbuff.h>
#include <net/sock.h>
#include <net/netlink.h>

#include "netlink_ipc.h"

/* 内核 Netlink 套接字指针 */
static struct sock *action_key_nl_sock = NULL;

/**
 * action_key_netlink_init() - 初始化并创建 Netlink 内核套接字
 *
 * 在模块加载阶段由 Rust init() 调用。
 * 创建协议号为 NETLINK_ACTION_KEY (31) 的套接字，并声明支持多播组。
 */
int action_key_netlink_init(void)
{
    struct netlink_kernel_cfg cfg = {
        .groups = 1, /* 支持 1 个多播组 (ACTION_KEY_NL_GROUP) */
    };

    if (action_key_nl_sock) {
        pr_warn("[ActionKey-NL] 套接字已存在，无需重复创建\n");
        return 0;
    }

    /* 使用当前主网络命名空间 init_net 创建套接字 */
    action_key_nl_sock = netlink_kernel_create(&init_net, NETLINK_ACTION_KEY, &cfg);
    if (!action_key_nl_sock) {
        pr_warn("[ActionKey-NL] 致命错误: 创建 Netlink 套接字失败 (unit=%d)\n", NETLINK_ACTION_KEY);
        return -ENOMEM;
    }

    pr_warn("[ActionKey-NL] Netlink IPC 管道已建立 (Protocol: %d, Group: %d)\n",
            NETLINK_ACTION_KEY, ACTION_KEY_NL_GROUP);
    return 0;
}

/**
 * action_key_netlink_exit() - 安全注销 Netlink 套接字
 *
 * 在模块卸载阶段由 Rust drop() 调用。
 */
void action_key_netlink_exit(void)
{
    if (action_key_nl_sock) {
        netlink_kernel_release(action_key_nl_sock);
        action_key_nl_sock = NULL;
        pr_warn("[ActionKey-NL] Netlink IPC 管道已安全关闭。\n");
    }
}

/**
 * action_key_netlink_send() - 向用户态守护进程多播手势事件
 * @gesture: 手势类型 ID (1: 短按, 2: 长按, 3: 双击)
 * @duration_ms: 按键按压持续时长 (毫秒)
 * @timestamp_ms: 触发时内核时间戳 (毫秒)
 *
 * 采用多播（Multicast）广播机制：
 * 只要用户态 Daemon 绑定了组 1，即可瞬间收到事件；
 * 如果 Daemon 尚未启动或正在重启，返回 -ESRCH，内核安全丢弃，不阻塞。
 */
int action_key_netlink_send(__u32 gesture, __s64 duration_ms, __s64 timestamp_ms)
{
    struct sk_buff *skb;
    struct nlmsghdr *nlh;
    struct action_key_event *ev;
    size_t payload_len = sizeof(struct action_key_event);
    int ret;

    if (!action_key_nl_sock) {
        return -ENODEV;
    }

    /*
     * 分配 Netlink 数据包缓冲区 (sk_buff)。
     * 因按键处于中断底半部上下文，使用 GFP_ATOMIC 保证非阻塞内存分配。
     */
    skb = nlmsg_new(payload_len, GFP_ATOMIC);
    if (!skb) {
        pr_warn("[ActionKey-NL] 内存不足: 无法分配 skb 广播缓冲区\n");
        return -ENOMEM;
    }

    /* 填充 Netlink 头部信息 */
    nlh = nlmsg_put(skb, 0, 0, NLMSG_DONE, payload_len, 0);
    if (!nlh) {
        kfree_skb(skb);
        return -EMSGSIZE;
    }

    /* 填充自定义手势数据载荷 */
    ev = (struct action_key_event *)nlmsg_data(nlh);
    ev->version = ACTION_KEY_PROTO_VERSION;
    ev->gesture = gesture;
    ev->duration_ms = duration_ms;
    ev->timestamp_ms = timestamp_ms;

    /* 设置多播目标组掩码: group 1 对应掩码 1 << 0 = 1 */
    NETLINK_CB(skb).dst_group = 1;

    /*
     * netlink_broadcast() 内部无论成功与否，都会负责释放 skb 所有权。
     * 因此调用方严禁再次调用 kfree_skb(skb)。
     */
    ret = netlink_broadcast(action_key_nl_sock, skb, 0, 1, GFP_ATOMIC);
    if (ret < 0) {
        if (ret == -ESRCH) {
            /* -ESRCH 表示当前没有用户态进程监听组 1，属于正常闲置状态 */
            return 0;
        }
        pr_warn("[ActionKey-NL] 多播事件广播失败, errno: %d\n", ret);
        return ret;
    }

    return 0;
}
