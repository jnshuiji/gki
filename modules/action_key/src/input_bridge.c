// SPDX-License-Identifier: GPL-2.0
/*
 * Action Key Assistant - Linux Input Subsystem Bridge & Hardware Torch Controller
 *
 * Design:
 *   1. Intercept physical Action Key (KeyCode 735 / BTN_TRIGGER_HAPPY32) at input core.
 *   2. High-precision kernel timer for zero-latency long press detection (holding state).
 *   3. Direct hardware LED trigger ('action_key_torch') for PMIC flashlight control.
 *   4. Spinlock-protected state transitions and robust error unwinding.
 */

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/module.h>
#include <linux/input.h>
#include <linux/slab.h>
#include <linux/timer.h>
#include <linux/ktime.h>
#include <linux/leds.h>
#include <linux/atomic.h>
#include <linux/spinlock.h>

#include "netlink_ipc.h"

#define EV_KEY_TYPE     0x01
#define KEY_ACTION_CODE 735 /* BTN_TRIGGER_HAPPY32 (OnePlus 15T Action Key) */

/* Global configuration with spinlock protection */
static DEFINE_SPINLOCK(g_config_lock);
static struct action_key_config_data g_config = {
    .long_press_ms     = 500,
    .long_press_action = AK_LP_ACTION_TORCH_KERNEL,
    .torch_brightness  = 200,
};

/* Hardware LED trigger, torch state and spinlock */
static DEFINE_SPINLOCK(g_torch_lock);
static struct led_trigger *g_torch_trigger = NULL;
static bool g_torch_is_on = false;

/* Long press timer and event state */
static struct timer_list g_long_press_timer;
static atomic_t g_long_press_triggered = ATOMIC_INIT(0);
static ktime_t g_press_time;

/**
 * action_key_set_config() - Atomically update runtime gesture parameters
 * @cfg: User-provided configuration payload
 */
void action_key_set_config(const struct action_key_config_data *cfg)
{
    unsigned long flags;

    if (!cfg)
        return;

    spin_lock_irqsave(&g_config_lock, flags);
    if (cfg->long_press_ms >= 100 && cfg->long_press_ms <= 3000)
        g_config.long_press_ms = cfg->long_press_ms;

    g_config.long_press_action = cfg->long_press_action;

    if (cfg->torch_brightness >= 1 && cfg->torch_brightness <= 255)
        g_config.torch_brightness = cfg->torch_brightness;
    spin_unlock_irqrestore(&g_config_lock, flags);

    pr_info("Config updated: long_press_ms=%u, action=%u, brightness=%u\n",
            READ_ONCE(g_config.long_press_ms),
            READ_ONCE(g_config.long_press_action),
            READ_ONCE(g_config.torch_brightness));
}

/**
 * action_key_torch_set() - Thread-safe flashlight state control
 * @on: true to turn on, false to turn off
 */
void action_key_torch_set(bool on)
{
    unsigned long flags;
    u32 brightness;

    brightness = READ_ONCE(g_config.torch_brightness);

    spin_lock_irqsave(&g_torch_lock, flags);
    g_torch_is_on = on;

    if (g_torch_trigger) {
        enum led_brightness br = on ? (enum led_brightness)brightness : LED_OFF;
        led_trigger_event(g_torch_trigger, br);
    }
    spin_unlock_irqrestore(&g_torch_lock, flags);

    pr_info("Torch state: %s (brightness: %u)\n",
            on ? "ON" : "OFF", on ? brightness : 0);

    /* Notify userspace daemon of hardware state change */
    action_key_netlink_send(ACTION_KEY_EVENT_TORCH_STATE, on ? 1 : 0,
                            ktime_to_ms(ktime_get()));
}

/**
 * action_key_torch_toggle() - Toggle hardware flashlight
 */
void action_key_torch_toggle(void)
{
    bool target;
    unsigned long flags;

    spin_lock_irqsave(&g_torch_lock, flags);
    target = !g_torch_is_on;
    spin_unlock_irqrestore(&g_torch_lock, flags);

    action_key_torch_set(target);
}

/**
 * action_key_torch_get() - Query current flashlight state
 */
bool action_key_torch_get(void)
{
    bool state;
    unsigned long flags;

    spin_lock_irqsave(&g_torch_lock, flags);
    state = g_torch_is_on;
    spin_unlock_irqrestore(&g_torch_lock, flags);

    return state;
}

/**
 * action_key_long_press_timer_fn() - Timer expiration callback
 * @t: Timer instance pointer
 *
 * Fires when user holds the key continuously for long_press_ms.
 */
static void action_key_long_press_timer_fn(struct timer_list *t)
{
    int64_t now_ms = ktime_to_ms(ktime_get());
    int64_t duration = now_ms - ktime_to_ms(g_press_time);
    u32 action = READ_ONCE(g_config.long_press_action);

    atomic_set(&g_long_press_triggered, 1);
    pr_info("Long press detected at %lld ms (held)\n", duration);

    /* 1. Direct hardware activation if configured */
    if (action == AK_LP_ACTION_TORCH_KERNEL)
        action_key_torch_toggle();

    /* 2. Broadcast event to userspace daemon */
    action_key_netlink_send(ACTION_KEY_GESTURE_LONG_PRESS, duration, now_ms);
}

/**
 * action_key_filter() - Linux input subsystem filter hook
 */
static bool action_key_filter(struct input_handle *handle, unsigned int type,
                              unsigned int code, int value)
{
    if (type == EV_KEY_TYPE && code == KEY_ACTION_CODE) {
        int64_t now_ms = ktime_to_ms(ktime_get());
        u32 timeout_ms = READ_ONCE(g_config.long_press_ms);

        if (value == 1) {
            /* Key DOWN: Record timestamp and arm timer */
            g_press_time = ktime_get();
            atomic_set(&g_long_press_triggered, 0);

            mod_timer(&g_long_press_timer, jiffies + msecs_to_jiffies(timeout_ms));
            pr_info("Key DOWN (ts: %lld ms, timeout: %u ms)\n", now_ms, timeout_ms);
            return true;
        } else if (value == 0) {
            /* Key UP: Deactivate timer and determine gesture */
            int timer_canceled = del_timer(&g_long_press_timer);

            if (timer_canceled) {
                /* Timer canceled before expiry: unambiguous short press */
                int64_t duration = now_ms - ktime_to_ms(g_press_time);
                pr_info("Key UP (short press resolved, duration: %lld ms)\n", duration);
                action_key_netlink_send(ACTION_KEY_GESTURE_SHORT_PRESS, duration, now_ms);
            } else {
                /* Timer already expired: long press was triggered; suppress release */
                pr_info("Key UP (long press release swallowed)\n");
            }
            return true;
        }

        /* Swallow autorepeat events (value == 2) */
        return true;
    }

    /* Pass through all other keys */
    return false;
}

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

static void action_key_disconnect(struct input_handle *handle)
{
    input_close_device(handle);
    input_unregister_handle(handle);
    kfree(handle);
}

static const struct input_device_id action_key_ids[] = {
    { .driver_info = 1 }, /* Match all input devices */
    { },
};

static struct input_handler action_key_handler = {
    .filter     = action_key_filter,
    .connect    = action_key_connect,
    .disconnect = action_key_disconnect,
    .name       = "action_key_filter",
    .id_table   = action_key_ids,
};

int action_key_register_bridge(void)
{
    int ret;

    /* Initialize long press timer */
    timer_setup(&g_long_press_timer, action_key_long_press_timer_fn, 0);

    /* Register LED Trigger 'action_key_torch' */
    led_trigger_register_simple("action_key_torch", &g_torch_trigger);
    pr_info("LED trigger 'action_key_torch' registered\n");

    /* Register input subsystem filter handler */
    ret = input_register_handler(&action_key_handler);
    if (ret) {
        pr_err("Failed to register input handler: %d\n", ret);
        if (g_torch_trigger) {
            led_trigger_unregister_simple(g_torch_trigger);
            g_torch_trigger = NULL;
        }
        del_timer_sync(&g_long_press_timer);
        return ret;
    }

    return 0;
}

void action_key_unregister_bridge(void)
{
    /* 1. Stop input handling first */
    input_unregister_handler(&action_key_handler);

    /* 2. Synchronize timer to guarantee callback completion */
    del_timer_sync(&g_long_press_timer);

    /* 3. Turn off LED and unregister trigger */
    if (g_torch_trigger) {
        unsigned long flags;
        spin_lock_irqsave(&g_torch_lock, flags);
        if (g_torch_is_on) {
            led_trigger_event(g_torch_trigger, LED_OFF);
            g_torch_is_on = false;
        }
        spin_unlock_irqrestore(&g_torch_lock, flags);

        led_trigger_unregister_simple(g_torch_trigger);
        g_torch_trigger = NULL;
    }
}
