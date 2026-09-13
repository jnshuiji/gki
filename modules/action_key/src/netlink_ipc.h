// SPDX-License-Identifier: GPL-2.0
/*
 * Action Key Assistant - Dedicated Netlink IPC Protocol Header
 *
 * 定义内核模块与用户态守护进程 (Root Daemon) 通信的数据包协议结构与常量。
 * Shared between action_key.ko and userspace action_key_daemon.
 */

#ifndef _ACTION_KEY_NETLINK_IPC_H
#define _ACTION_KEY_NETLINK_IPC_H

#include <linux/types.h>

/**
 * 自定义 Netlink 协议号 (0 ~ 31 内可用协议号)
 * NETLINK_USERSOCK 为 2，31 为最大空闲扩展协议号
 */
#define NETLINK_ACTION_KEY          31

/**
 * 多播组号 (Multicast Group 1，掩码为 1 << 0)
 * 用户态通过 setsockopt(..., NETLINK_ADD_MEMBERSHIP, 1) 或 bind(groups = 1) 订阅
 */
#define ACTION_KEY_NL_GROUP         1

/**
 * 协议版本号 (用于跨版本协议兼容)
 */
#define ACTION_KEY_PROTO_VERSION    1

/**
 * 手势动作枚举
 */
enum action_key_gesture_type {
    ACTION_KEY_GESTURE_NONE        = 0,
    ACTION_KEY_GESTURE_SHORT_PRESS = 1, /* 单击 / 短按 */
    ACTION_KEY_GESTURE_LONG_PRESS  = 2, /* 长按 */
    ACTION_KEY_GESTURE_DOUBLE_TAP  = 3, /* 双击 (未来扩展) */
};

/**
 * 广播给用户态守护进程的事件数据包载荷 (24 字节对齐)
 */
struct action_key_event {
    __u32 version;       /* 协议版本 (ACTION_KEY_PROTO_VERSION) */
    __u32 gesture;       /* 手势类型 (enum action_key_gesture_type) */
    __s64 duration_ms;   /* 按键持续按压时间 (毫秒) */
    __s64 timestamp_ms;  /* 触发时的内核单调时间戳 (ktime ms) */
};

#ifdef __KERNEL__

/**
 * action_key_netlink_init() - 初始化并创建 Netlink 内核套接字
 *
 * Return: 0 表示成功，负数表示 errno 错误码。
 */
int action_key_netlink_init(void);

/**
 * action_key_netlink_exit() - 安全销毁 Netlink 套接字
 */
void action_key_netlink_exit(void);

/**
 * action_key_netlink_send() - 向用户态多播组广播手势事件
 * @gesture: 手势类型 ID (1: ShortPress, 2: LongPress, etc.)
 * @duration_ms: 按键按压时长（毫秒）
 * @timestamp_ms: 内核时间戳（毫秒）
 *
 * Return: 0 表示成功，负数表示 errno。(-ESRCH 表示当前尚无用户态监听者，属正常情况)
 */
int action_key_netlink_send(__u32 gesture, __s64 duration_ms, __s64 timestamp_ms);

#endif /* __KERNEL__ */

#endif /* _ACTION_KEY_NETLINK_IPC_H */
