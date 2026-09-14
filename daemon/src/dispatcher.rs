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
            ResolvedGesture::ShortPress => "单击",
            ResolvedGesture::DoubleTap => "双击",
            ResolvedGesture::LongPress => "长按",
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

    /// 获取当前本地时间字符串 (HH:MM:SS)
    pub fn get_time_str() -> String {
        let now = unsafe { libc::time(std::ptr::null_mut()) };
        let mut tm: libc::tm = unsafe { std::mem::zeroed() };
        unsafe { libc::localtime_r(&now, &mut tm) };
        format!("{:02}:{:02}:{:02}", tm.tm_hour, tm.tm_min, tm.tm_sec)
    }

    /// 执行手势对应的动作
    /// - `from_kernel`: 为 true 时表示由内核触发，长按自闭环直驱无需重复下发指令
    pub fn execute(gesture: ResolvedGesture, duration_ms: i64, config: &AppConfig, from_kernel: bool) {
        use std::io::Write;

        let action = match gesture {
            ResolvedGesture::ShortPress => &config.actions.short_press,
            ResolvedGesture::DoubleTap => &config.actions.double_tap,
            ResolvedGesture::LongPress => &config.actions.long_press,
        };

        let now_time = Self::get_time_str();

        if !action.enabled {
            println!(
                "[{}] ⚠️ 手势【{}】已触发，但配置为已禁用，跳过执行",
                now_time,
                gesture.display_name()
            );
            let _ = std::io::stdout().flush();
            return;
        }

        let action_name = match action.action_type.as_str() {
            "ha" => "Home Assistant",
            "torch" => "手电筒",
            "log" => "仅记录日志",
            _ => action.action_type.as_str(),
        };

        println!(
            "[{}] 🎯 捕获手势:【{}】(耗时: {}ms) -> 动作: {}",
            now_time,
            gesture.display_name(),
            duration_ms,
            action_name
        );

        // 系统震动触感反馈 (静默执行)
        let _ = std::process::Command::new("/system/bin/cmd")
            .args(["vibrator_manager", "synced", "oneshot", "80"])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
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
                match crate::actions::ha::HaClient::send_event(ha_action, &config.home_assistant) {
                    Ok(info) => {
                        println!("[{}] ✅ [HA] {}", Self::get_time_str(), info);
                    }
                    Err(e) => {
                        eprintln!("[{}] ❌ [HA] {}", Self::get_time_str(), e);
                    }
                }
            }
            "torch" => {
                // 仅当长按且内核配置为硬件直驱时，已在内核定时器中断中 0ms 瞬间完成
                let kernel_handled = gesture == ResolvedGesture::LongPress
                    && from_kernel
                    && config.actions.long_press.enabled
                    && config.actions.long_press.action_type == "torch";

                if kernel_handled {
                    println!("[{}] 🔦 硬件手电筒已在内核 0ms 直驱瞬发完成", Self::get_time_str());
                } else {
                    // 单击、双击或用户态触发：向内核下发 Netlink 指令瞬间切换手电筒
                    match crate::actions::torch::TorchController::toggle() {
                        Ok(info) => {
                            println!("[{}] 🔦 {}", Self::get_time_str(), info);
                        }
                        Err(e) => {
                            eprintln!("[{}] ❌ 切换手电筒失败: {}", Self::get_time_str(), e);
                        }
                    }
                }
            }
            "log" => {
                println!("[{}] 📝 日志已记录", Self::get_time_str());
            }
            _ => {
                println!(
                    "[{}] ℹ️ 手势【{}】未绑定具体执行动作",
                    Self::get_time_str(),
                    gesture.display_name()
                );
            }
        }
        let _ = std::io::stdout().flush();
    }
}
