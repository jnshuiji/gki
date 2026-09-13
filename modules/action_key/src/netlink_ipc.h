/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Action Key Assistant - Dedicated Netlink IPC Protocol Header
 *
 * Full-duplex bidirectional IPC between Linux kernel and userspace daemon:
 *   - Uplink   (Kernel -> Userspace): Gesture events & hardware torch state
 *   - Downlink (Userspace -> Kernel): Runtime configuration & manual torch commands
 */

#ifndef _ACTION_KEY_NETLINK_IPC_H
#define _ACTION_KEY_NETLINK_IPC_H

#ifdef __KERNEL__
#include <linux/types.h>
#else
#include <stdint.h>
typedef uint32_t __u32;
typedef int64_t  __s64;
typedef uint8_t  __u8;
#endif

/* Netlink protocol unit (Generic userspace protocol slot) */
#define NETLINK_ACTION_KEY          31

/* Multicast group index (Group 1, mask 1 << 0) */
#define ACTION_KEY_NL_GROUP         1

/* Protocol specification */
#define ACTION_KEY_PROTO_VERSION    2
#define ACTION_KEY_MAGIC            0x414B4559 /* 'AKEY' */

/* Uplink event types (Kernel -> Userspace) */
enum action_key_gesture_type {
    ACTION_KEY_GESTURE_NONE        = 0,
    ACTION_KEY_GESTURE_SHORT_PRESS = 1,
    ACTION_KEY_GESTURE_LONG_PRESS  = 2,
    ACTION_KEY_GESTURE_DOUBLE_TAP  = 3,
    ACTION_KEY_EVENT_TORCH_STATE   = 10, /* duration_ms carries 0 (OFF) or 1 (ON) */
};

/* Downlink command types (Userspace -> Kernel) */
enum action_key_cmd_type {
    AK_CMD_SET_CONFIG   = 10,
    AK_CMD_TOGGLE_TORCH = 11,
    AK_CMD_SET_TORCH    = 12,
};

/* Long press action policy */
enum action_key_long_press_action {
    AK_LP_ACTION_TORCH_KERNEL  = 0, /* Hardware direct drive (0ms latency) */
    AK_LP_ACTION_DISPATCH_USER = 1, /* Report to userspace daemon only */
};

/* Downlink configuration payload */
struct action_key_config_data {
    __u32 long_press_ms;     /* Long press threshold in milliseconds (default: 500) */
    __u32 long_press_action; /* enum action_key_long_press_action (default: 0) */
    __u32 torch_brightness;  /* Flashlight brightness 1..255 (default: 200) */
} __attribute__((aligned(4)));

/* Uplink event payload (24 bytes aligned) */
struct action_key_event {
    __u32 version;       /* ACTION_KEY_PROTO_VERSION */
    __u32 gesture;       /* enum action_key_gesture_type */
    __s64 duration_ms;   /* Press duration in ms (or 0/1 for torch state) */
    __s64 timestamp_ms;  /* Monotonic kernel timestamp in ms */
} __attribute__((aligned(8)));

/* Downlink command payload (48 bytes fixed size) */
struct action_key_cmd {
    __u32 magic;         /* ACTION_KEY_MAGIC */
    __u32 version;       /* ACTION_KEY_PROTO_VERSION */
    __u32 cmd_type;      /* enum action_key_cmd_type */
    __u32 reserved;
    union {
        struct action_key_config_data config;
        struct {
            __u32 state; /* 0: OFF, 1: ON */
        } torch;
        __u8 raw[32];
    } payload;
} __attribute__((aligned(8)));

#ifdef __KERNEL__

int action_key_netlink_init(void);
void action_key_netlink_exit(void);
int action_key_netlink_send(__u32 gesture, __s64 duration_ms, __s64 timestamp_ms);

void action_key_torch_toggle(void);
void action_key_torch_set(bool on);
bool action_key_torch_get(void);
void action_key_set_config(const struct action_key_config_data *cfg);

#endif /* __KERNEL__ */

#endif /* _ACTION_KEY_NETLINK_IPC_H */
