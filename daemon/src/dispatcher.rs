// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Gesture Dispatcher & State Machine
 *
 * 负责手势去歧义（单击 vs 双击）与动作分发。
 * 支持全双工与内核自闭环协同。
 */

use crate::config::AppConfig;
use crate::protocol::{ActionKeyEvent, KernelGesture};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::thread;
use std::time::Duration;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ResolvedGesture {
    ShortPress,
    DoubleTap,
    LongPress,
}

impl ResolvedGesture {
    #[allow(dead_code)]
    pub fn as_str(&self) -> &'static str {
        match self {
            ResolvedGesture::ShortPress => "short_press",
            ResolvedGesture::DoubleTap => "double_tap",
            ResolvedGesture::LongPress => "long_press",
        }
    }

    pub fn display_name(&self) -> &'static str {
        match self {
            ResolvedGesture::ShortPress => "单击 (Short Press)",
            ResolvedGesture::DoubleTap => "双击 (Double Tap)",
            ResolvedGesture::LongPress => "长按 (Long Press)",
        }
    }
}

pub struct GestureDispatcher {
    event_tx: Sender<ActionKeyEvent>,
}

impl GestureDispatcher {
    /// 创建并启动手势状态机工作线程
    pub fn new() -> Self {
        let (tx, rx) = channel::<ActionKeyEvent>();

        thread::spawn(move || {
            Self::state_machine_loop(rx);
        });

        Self { event_tx: tx }
    }

    /// 向状态机注入来自 Netlink 或测试接口的事件
    pub fn push_event(&self, event: ActionKeyEvent) {
        let _ = self.event_tx.send(event);
    }

    /// 核心状态机循环：利用 mpsc::recv_timeout 零 CPU 消耗做双击去歧义
    fn state_machine_loop(rx: Receiver<ActionKeyEvent>) {
        loop {
            // 阻塞等待首个事件到来
            let first_event = match rx.recv() {
                Ok(ev) => ev,
                Err(_) => break, // 通道关闭
            };

            let config = AppConfig::load_or_default();
            let kernel_gesture = KernelGesture::from_u32(first_event.gesture);

            match kernel_gesture {
                KernelGesture::TorchStateChanged => {
                    let state_str = if first_event.duration_ms > 0 { "开启 [ON]" } else { "关闭 [OFF]" };
                    println!("🔦 [ActionKey-Dispatcher] 收到内核手电筒硬件状态同步: {}", state_str);
                    let _ = std::process::Command::new("/system/bin/log")
                        .args(["-t", "ActionKey", &format!("🔦 硬件手电筒状态: {}", state_str)])
                        .spawn();
                }

                KernelGesture::LongPress => {
                    // 长按无需等待后续按键，直接判定触发 (来自内核 500ms 定时器)
                    Self::execute(ResolvedGesture::LongPress, first_event.duration_ms, &config, true);
                }

                KernelGesture::ShortPress => {
                    if !config.actions.double_tap.enabled {
                        // 如果用户禁用了双击，则单击无需任何延迟，立即触发
                        Self::execute(ResolvedGesture::ShortPress, first_event.duration_ms, &config, true);
                        continue;
                    }

                    // 等待双击时间窗 (例如 300ms)
                    let timeout = Duration::from_millis(config.double_tap_timeout_ms);
                    match rx.recv_timeout(timeout) {
                        Ok(second_event) => {
                            let second_gesture = KernelGesture::from_u32(second_event.gesture);
                            if second_gesture == KernelGesture::ShortPress {
                                // 成功在时间窗内捕获第二次单击 -> 判定为【双击】
                                Self::execute(
                                    ResolvedGesture::DoubleTap,
                                    second_event.duration_ms,
                                    &config,
                                    true,
                                );
                            } else if second_gesture == KernelGesture::LongPress {
                                // 第一次是短按，紧接着长按：分别触发
                                Self::execute(
                                    ResolvedGesture::ShortPress,
                                    first_event.duration_ms,
                                    &config,
                                    true,
                                );
                                Self::execute(
                                    ResolvedGesture::LongPress,
                                    second_event.duration_ms,
                                    &config,
                                    true,
                                );
                            }
                        }
                        Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                            // 时间窗超时，没有第二击 -> 判定为【单击】
                            Self::execute(
                                ResolvedGesture::ShortPress,
                                first_event.duration_ms,
                                &config,
                                true,
                            );
                        }
                        Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
                    }
                }

                KernelGesture::DoubleTap => {
                    // 内核若直接上报双击，直接触发
                    Self::execute(ResolvedGesture::DoubleTap, first_event.duration_ms, &config, true);
                }

                KernelGesture::None => {}
            }
        }
    }

    /// 执行手势对应的动作
    /// - `from_kernel`: 为 true 时表示由内核触发，内核硬件自闭环动作无需重复执行
    pub fn execute(gesture: ResolvedGesture, duration_ms: i64, config: &AppConfig, from_kernel: bool) {
        let action = match gesture {
            ResolvedGesture::ShortPress => &config.actions.short_press,
            ResolvedGesture::DoubleTap => &config.actions.double_tap,
            ResolvedGesture::LongPress => &config.actions.long_press,
        };

        if !action.enabled {
            println!(
                "[ActionKey-Dispatcher] 手势【{}】已触发，但配置为已禁用 (enabled = false)，跳过执行",
                gesture.display_name()
            );
            return;
        }

        println!("========================================================");
        println!(
            "🎯 [ActionKey-Event] 成功捕获手势: 【{}】 (时长: {} ms)",
            gesture.display_name(),
            duration_ms
        );
        println!("  - 配置名称: {}", action.name);
        println!("  - 动作类型: {}", action.action_type);
        println!("  - 执行载荷: {}", action.payload);

        // 1. Android 系统震动触感反馈
        let _ = std::process::Command::new("/system/bin/cmd")
            .args(["vibrator_manager", "synced", "oneshot", "80"])
            .spawn();

        // 2. Android 系统日志 logcat (标签 ActionKey)
        let logcat_msg = format!(
            "🎯 [ActionKey] 捕获手势: 【{}】 (时长: {}ms) -> 动作: {} ({})",
            gesture.display_name(),
            duration_ms,
            action.action_type,
            action.payload
        );
        let _ = std::process::Command::new("/system/bin/log")
            .args(["-t", "ActionKey", &logcat_msg])
            .spawn();

        match action.action_type.as_str() {
            "ha" => {
                let ha_action = if action.payload.is_empty() {
                    match gesture {
                        ResolvedGesture::ShortPress => "single",
                        ResolvedGesture::DoubleTap => "double",
                        ResolvedGesture::LongPress => "long",
                    }
                } else {
                    action.payload.as_str()
                };
                let res = crate::actions::ha::HaClient::send_event(ha_action, &config.home_assistant);
                match res {
                    Ok(info) => {
                        println!("✅ [ActionKey-HA] {}", info);
                        let _ = std::process::Command::new("/system/bin/log")
                            .args(["-t", "ActionKey", &format!("✅ [ActionKey-HA] {}", info)])
                            .spawn();
                    }
                    Err(e) => {
                        eprintln!("⚠️ [ActionKey-HA] {}", e);
                        let _ = std::process::Command::new("/system/bin/log")
                            .args(["-t", "ActionKey", &format!("⚠️ [ActionKey-HA] {}", e)])
                            .spawn();
                    }
                }
            }
            "torch" => {
                if from_kernel {
                    // 内核硬件自闭环直驱已在中断中 0ms 瞬间完成
                    println!("🔦 [ActionKey-Torch] 硬件手电筒已在内核 0ms 瞬发完成");
                } else {
                    // 来自 CLI 或 WebUI 模拟测试触发
                    let res = crate::actions::torch::TorchController::toggle();
                    match res {
                        Ok(info) => {
                            println!("✅ [ActionKey-Torch] {}", info);
                        }
                        Err(e) => {
                            eprintln!("⚠️ [ActionKey-Torch] {}", e);
                        }
                    }
                }
            }
            "none" | _ => {
                println!(
                    "ℹ️ [ActionKey-Action] 手势【{}】未绑定具体执行动作 (action_type: {})",
                    gesture.display_name(),
                    action.action_type
                );
            }
        }
        println!("========================================================");
    }
}
