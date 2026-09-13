// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Gesture Dispatcher & State Machine
 *
 * 负责手势去歧义（单击 vs 双击）与动作分发。
 * 当前阶段遵循用户要求：仅打印测试日志，验证端到端框架跑通。
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
                KernelGesture::LongPress => {
                    // 长按无需等待后续按键，直接判定触发
                    Self::execute(ResolvedGesture::LongPress, first_event.duration_ms, &config);
                }

                KernelGesture::ShortPress => {
                    if !config.actions.double_tap.enabled {
                        // 如果用户禁用了双击，则单击无需任何延迟，立即触发
                        Self::execute(ResolvedGesture::ShortPress, first_event.duration_ms, &config);
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
                                );
                            } else if second_gesture == KernelGesture::LongPress {
                                // 第一次是短按，紧接着长按：分别触发
                                Self::execute(
                                    ResolvedGesture::ShortPress,
                                    first_event.duration_ms,
                                    &config,
                                );
                                Self::execute(
                                    ResolvedGesture::LongPress,
                                    second_event.duration_ms,
                                    &config,
                                );
                            }
                        }
                        Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                            // 时间窗超时，没有第二击 -> 判定为【单击】
                            Self::execute(
                                ResolvedGesture::ShortPress,
                                first_event.duration_ms,
                                &config,
                            );
                        }
                        Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
                    }
                }

                KernelGesture::DoubleTap => {
                    // 内核若直接上报双击，直接触发
                    Self::execute(ResolvedGesture::DoubleTap, first_event.duration_ms, &config);
                }

                KernelGesture::None => {}
            }
        }
    }

    /// 执行手势对应的动作（当前基础阶段：打印标准化日志与状态）
    pub fn execute(gesture: ResolvedGesture, duration_ms: i64, config: &AppConfig) {
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
        println!("========================================================");
    }
}
