// SPDX-License-Identifier: GPL-2.0
//! Action Key Assistant - Native Rust Kernel Module
//!
//! 一加 15T (PLZ110) 物理快捷键 (Action Key) 内核级重映射与手势识别驱动。
//! 基于 Rust for Linux (RFL) 与 Linux 6.12 GKI 架构构建。

use core::sync::atomic::{AtomicI64, Ordering};
use kernel::prelude::*;
use kernel::time::Ktime;

// =======================================================================
// 1. 模块元数据 (Module Metadata)
// =======================================================================
module! {
    type: ActionKeyModule,
    name: "action_key",
    author: "pochita",
    description: "Action Key Driver in Rust for Android 16",
    license: "GPL",
}

// =======================================================================
// 2. C 桥接层接口 (Input Bridge & Netlink IPC FFI)
// =======================================================================
extern "C" {
    // Linux 输入子系统桥接接口 (input_bridge.c)
    fn action_key_register_bridge() -> core::ffi::c_int;
    fn action_key_unregister_bridge();

    // 专属 Netlink IPC 通信接口 (netlink_ipc.c)
    fn action_key_netlink_init() -> core::ffi::c_int;
    fn action_key_netlink_exit();
    fn action_key_netlink_send(gesture: u32, duration_ms: i64, timestamp_ms: i64) -> core::ffi::c_int;
}

// =======================================================================
// 3. 硬件与事件常量定义 (Hardware Constants)
// =======================================================================
/// Linux 按键事件类型 (Event Type for Key/Button)
const EV_KEY: u32 = 0x01;

/// 一加 15T (PLZ110 / OP64DDL1) 实体独立快捷键的 Linux 硬件键值
/// 对应内核标准键码: `BTN_TRIGGER_HAPPY32` (0x2df = 十进制 735)
const KEY_ACTION: u32 = 735;

/// 判定为长按的阈值（毫秒）
const LONG_PRESS_THRESHOLD_MS: i64 = 500;

/// 按键按下瞬间的单调时间戳（毫秒）
/// 使用原子变量保证在中断底半部上下文中的并发安全与零锁开销
static PRESS_TIME_MS: AtomicI64 = AtomicI64::new(0);

// =======================================================================
// 4. 手势类型抽象与业务分发 (Gesture Abstraction & Dispatcher)
// =======================================================================
/// 表示识别出的用户按键手势，方便后续扩展更多动作（双击、多击等）
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum KeyGesture {
    /// 单击 / 短按 (Short Press / Single Click)
    ShortPress {
        /// 按压持续时间（毫秒）
        duration_ms: i64,
    },
    /// 长按 (Long Press)
    LongPress {
        /// 按压持续时间（毫秒）
        duration_ms: i64,
    },
}

/// 业务动作分发中心 (Gesture Action Dispatcher)
///
/// 当内核判定出完整的手势时在此处触发。后续阶段可直接在此挂接业务逻辑：
/// - 纯内核动作: 操作 LED (手电筒)、触发线性马达 Force Feedback 震动
/// - 用户态通信: 通过 Netlink Socket 或字符设备通知守护进程执行 Home Assistant / 启动 App
fn dispatch_gesture(gesture: KeyGesture) {
    let (gesture_id, duration_ms) = match gesture {
        KeyGesture::ShortPress { duration_ms } => {
            pr_warn!("✨ [ActionKey] 触发手势:【短按/单击】 (按压时长: {} ms)\n", duration_ms);
            (1, duration_ms)
        }
        KeyGesture::LongPress { duration_ms } => {
            pr_warn!("⚡⚡⚡ [ActionKey] 触发手势:【长按】 (按压时长: {} ms)\n", duration_ms);
            (2, duration_ms)
        }
    };

    // 获取当前内核时间戳并向 Netlink 广播事件给用户态 Daemon
    let timestamp_ms = Ktime::ktime_get().to_ms();
    let ret = unsafe { action_key_netlink_send(gesture_id, duration_ms, timestamp_ms) };
    if ret != 0 {
        pr_warn!("[ActionKey] Netlink 广播通知失败, code: {}\n", ret);
    }
}

// =======================================================================
// 5. C 桥梁回调接口 (Input Event Callback)
// =======================================================================
/// 处理来自 C 桥接层过滤器的原始输入事件
///
/// # Parameters
/// - `event_type`: Linux 输入事件类型 (`EV_KEY`, `EV_REL` 等)
/// - `code`: 键值或硬件扫描码 (`KEY_ACTION` = 735)
/// - `value`: 按键状态: `1` = 按下 (Pressed), `0` = 松开 (Released), `2` = 连击 (Repeat)
///
/// # Returns
/// - `true`:  在内核源头拦截并吞掉该事件（Android 系统和 ColorOS 完全静默，无法收到）
/// - `false`: 放行该事件，交由 Android 上层框架正常处理
#[no_mangle]
pub extern "C" fn rust_on_key_event(event_type: u32, code: u32, value: i32) -> bool {
    if event_type == EV_KEY && code == KEY_ACTION {
        let now_ms = Ktime::ktime_get().to_ms();

        match value {
            1 => {
                // 按下瞬间：记录起始时间戳
                PRESS_TIME_MS.store(now_ms, Ordering::Relaxed);
                pr_warn!("🔥 [ActionKey] 物理键按下 (Timestamp: {} ms)\n", now_ms);
            }
            0 => {
                // 松开瞬间：计算按压持续时长并判定手势
                let start_ms = PRESS_TIME_MS.load(Ordering::Relaxed);
                let duration_ms = now_ms - start_ms;

                let gesture = if duration_ms >= LONG_PRESS_THRESHOLD_MS {
                    KeyGesture::LongPress { duration_ms }
                } else {
                    KeyGesture::ShortPress { duration_ms }
                };

                dispatch_gesture(gesture);
            }
            _ => {}
        }

        // 返回 true: 彻底屏蔽系统默认动作，实现静默重映射
        true
    } else {
        // 其他按键（音量键、电源键等）原样放行
        false
    }
}

// =======================================================================
// 6. 内核模块生命周期管理 (Module Lifecycle)
// =======================================================================
/// ActionKey 内核模块上下文结构体
struct ActionKeyModule;

impl kernel::Module for ActionKeyModule {
    fn init(_module: &'static ThisModule) -> Result<Self> {
        pr_warn!("====================================================\n");
        pr_warn!("[ActionKey] 驱动模块加载成功 (Target: KeyCode 735)\n");
        pr_warn!("[ActionKey] 运行底座: Android 16 (Linux 6.12 GKI)\n");

        // 1. 初始化 Netlink IPC 管道（先于输入监听器启动）
        let nl_ret = unsafe { action_key_netlink_init() };
        if nl_ret != 0 {
            pr_warn!("[ActionKey] 初始化 Netlink IPC 失败, errno: {}\n", nl_ret);
            return Err(Error::from_errno(nl_ret));
        }

        // 2. 向 Linux 输入核心注册 C 桥接监听器
        let ret = unsafe { action_key_register_bridge() };
        if ret != 0 {
            pr_warn!("[ActionKey] 注册输入监听器失败, errno: {}\n", ret);
            unsafe { action_key_netlink_exit() };
            return Err(Error::from_errno(ret));
        }

        pr_warn!("[ActionKey] 输入监听与 Netlink IPC 已就绪，按键拦截已激活！\n");
        pr_warn!("====================================================\n");

        Ok(ActionKeyModule)
    }
}

impl Drop for ActionKeyModule {
    fn drop(&mut self) {
        // 安全注销输入监听器与 Netlink 套接字
        unsafe {
            action_key_unregister_bridge();
            action_key_netlink_exit();
        }
        pr_warn!("[ActionKey] 驱动模块已安全卸载，输入监听器与 Netlink IPC 已注销。\n");
    }
}
