// SPDX-License-Identifier: GPL-2.0
/*
 * Action Key Assistant - Linux Input Subsystem Bridge
 *
 * 该 C 桥接层负责对接 Linux 内核复杂的 input_handler 结构体与回调链表，
 * 并将底层的原始输入事件以最高效率（零额外开销）直接转发至 Rust 核心逻辑。
 *
 * Architecture:
 *   Hardware IRQ -> drivers/input/input.c -> input_bridge.c (Filter) -> rust_on_key_event()
 */

#include <linux/module.h>
#include <linux/input.h>
#include <linux/slab.h>

/*
 * 声明由 Rust 侧导出的事件处理回调函数。
 * Rust 端签名: pub extern "C" fn rust_on_key_event(type, code, value) -> bool
 *
 * @return: true  = 消费/吞掉该事件 (拦截系统默认动作)
 *          false = 放行该事件给上层 (Android EventHub / /dev/input/eventX)
 */
extern bool rust_on_key_event(unsigned int type, unsigned int code, int value);

/**
 * action_key_filter() - 内核输入事件过滤器钩子
 *
 * Linux 输入核心在分发事件至各个 handle（如 evdev）前，
 * 会最先调用所有注册了 .filter 的 handler。
 */
static bool action_key_filter(struct input_handle *handle, unsigned int type,
                              unsigned int code, int value)
{
    return rust_on_key_event(type, code, value);
}

/**
 * action_key_connect() - 输入设备连接回调
 *
 * 当内核发现系统中存在匹配的输入设备时调用，
 * 为该输入设备动态绑定一个监听纽带 (input_handle)。
 */
static int action_key_connect(struct input_handler *handler, struct input_dev *dev,
                              const struct input_device_id *id)
{
    struct input_handle *handle;
    int error;

    handle = kzalloc(sizeof(struct input_handle), GFP_KERNEL);
    if (!handle)
        return -ENOMEM;

    handle->dev = dev;
    handle->handler = handler;
    handle->name = "action_key_handle";

    error = input_register_handle(handle);
    if (error) {
        kfree(handle);
        return error;
    }

    error = input_open_device(handle);
    if (error) {
        input_unregister_handle(handle);
        kfree(handle);
        return error;
    }

    return 0;
}

/**
 * action_key_disconnect() - 输入设备断开/模块注销回调
 */
static void action_key_disconnect(struct input_handle *handle)
{
    input_close_device(handle);
    input_unregister_handle(handle);
    kfree(handle);
}

/*
 * 匹配规则表:
 * 设置 .driver_info = 1 并以空项结尾，通配匹配系统中的所有输入设备。
 */
static const struct input_device_id action_key_ids[] = {
    { .driver_info = 1 }, /* Match all input devices */
    { },
};

/*
 * 静态装配 Linux 内核 input_handler
 */
static struct input_handler action_key_handler = {
    .filter     = action_key_filter,
    .connect    = action_key_connect,
    .disconnect = action_key_disconnect,
    .name       = "action_key_filter",
    .id_table   = action_key_ids,
};

/**
 * action_key_register_bridge() - 向内核注册输入监听桥梁
 * 供 Rust 侧的 ActionKeyModule::init 调用
 */
int action_key_register_bridge(void)
{
    return input_register_handler(&action_key_handler);
}

/**
 * action_key_unregister_bridge() - 从内核注销输入监听桥梁
 * 供 Rust 侧的 ActionKeyModule::drop 调用
 */
void action_key_unregister_bridge(void)
{
    input_unregister_handler(&action_key_handler);
}
