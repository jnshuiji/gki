// SPDX-License-Identifier: GPL-2.0
/*
 * Action Key Assistant - Dedicated Netlink IPC Subsystem
 *
 * Full-duplex Netlink communication between Linux kernel and userspace daemon.
 */

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/netlink.h>
#include <linux/skbuff.h>
#include <net/sock.h>
#include <net/netlink.h>

#include "netlink_ipc.h"

static struct sock *action_key_nl_sock = NULL;

/**
 * action_key_nl_recv() - Handle downlink commands from userspace daemon
 * @skb: Received socket buffer
 */
static void action_key_nl_recv(struct sk_buff *skb)
{
    struct nlmsghdr *nlh;
    struct action_key_cmd *cmd;
    void *data;
    int len;

    if (!skb)
        return;

    nlh = nlmsg_hdr(skb);
    if (!nlh || skb->len < sizeof(struct nlmsghdr))
        return;

    data = nlmsg_data(nlh);
    len = nlmsg_len(nlh);

    if (len < sizeof(struct action_key_cmd)) {
        pr_warn("Invalid command size: %d bytes (expected: %zu)\n",
                len, sizeof(struct action_key_cmd));
        return;
    }

    cmd = (struct action_key_cmd *)data;
    if (cmd->magic != ACTION_KEY_MAGIC) {
        pr_warn("Command magic mismatch: 0x%08X (expected: 0x%08X)\n",
                cmd->magic, ACTION_KEY_MAGIC);
        return;
    }

    if (cmd->version != ACTION_KEY_PROTO_VERSION) {
        pr_warn("Command version mismatch: %u (expected: %u)\n",
                cmd->version, ACTION_KEY_PROTO_VERSION);
        return;
    }

    pr_info("Received userspace command (type: %u)\n", cmd->cmd_type);

    switch (cmd->cmd_type) {
    case AK_CMD_SET_CONFIG:
        pr_info("Applying config: long_press_ms=%u, action=%u, br=%u\n",
                cmd->payload.config.long_press_ms,
                cmd->payload.config.long_press_action,
                cmd->payload.config.torch_brightness);
        action_key_set_config(&cmd->payload.config);
        break;

    case AK_CMD_TOGGLE_TORCH:
        pr_info("Command: Toggle hardware torch\n");
        action_key_torch_toggle();
        break;

    case AK_CMD_SET_TORCH:
        pr_info("Command: Set torch to %s\n",
                cmd->payload.torch.state ? "ON" : "OFF");
        action_key_torch_set(cmd->payload.torch.state != 0);
        break;

    default:
        pr_warn("Unknown command type: %u\n", cmd->cmd_type);
        break;
    }
}

/**
 * action_key_netlink_init() - Create Netlink kernel socket
 */
int action_key_netlink_init(void)
{
    struct netlink_kernel_cfg cfg = {
        .groups = 1,
        .input  = action_key_nl_recv,
    };

    if (action_key_nl_sock)
        return 0;

    action_key_nl_sock = netlink_kernel_create(&init_net, NETLINK_ACTION_KEY, &cfg);
    if (!action_key_nl_sock) {
        pr_err("Failed to create Netlink socket (unit=%d)\n", NETLINK_ACTION_KEY);
        return -ENOMEM;
    }

    pr_info("Netlink IPC initialized (protocol: %d, group: %d)\n",
            NETLINK_ACTION_KEY, ACTION_KEY_NL_GROUP);
    return 0;
}

/**
 * action_key_netlink_exit() - Release Netlink socket
 */
void action_key_netlink_exit(void)
{
    if (action_key_nl_sock) {
        netlink_kernel_release(action_key_nl_sock);
        action_key_nl_sock = NULL;
        pr_info("Netlink IPC released\n");
    }
}

/**
 * action_key_netlink_send() - Multicast event to userspace daemon
 * @gesture: Gesture type enum value
 * @duration_ms: Press duration or state parameter
 * @timestamp_ms: Monotonic kernel timestamp
 */
int action_key_netlink_send(__u32 gesture, __s64 duration_ms, __s64 timestamp_ms)
{
    struct sk_buff *skb;
    struct nlmsghdr *nlh;
    struct action_key_event *ev;
    size_t payload_len = sizeof(struct action_key_event);
    int ret;

    if (!action_key_nl_sock)
        return -ENODEV;

    skb = nlmsg_new(payload_len, GFP_ATOMIC);
    if (!skb) {
        pr_err("Failed to allocate skb for multicast event\n");
        return -ENOMEM;
    }

    nlh = nlmsg_put(skb, 0, 0, NLMSG_DONE, payload_len, 0);
    if (!nlh) {
        kfree_skb(skb);
        return -EMSGSIZE;
    }

    ev = (struct action_key_event *)nlmsg_data(nlh);
    ev->version = ACTION_KEY_PROTO_VERSION;
    ev->gesture = gesture;
    ev->duration_ms = duration_ms;
    ev->timestamp_ms = timestamp_ms;

    NETLINK_CB(skb).dst_group = 1;

    ret = netlink_broadcast(action_key_nl_sock, skb, 0, 1, GFP_ATOMIC);
    if (ret < 0) {
        if (ret == -ESRCH) {
            /* Normal idle state: no daemon listening */
            return 0;
        }
        pr_warn("Multicast send failed, errno: %d\n", ret);
        return ret;
    }

    return 0;
}
