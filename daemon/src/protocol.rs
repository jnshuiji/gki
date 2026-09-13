// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Userspace Netlink IPC Protocol
 *
 * 严格对齐内核模块 modules/action_key/src/netlink_ipc.h
 */

pub const NETLINK_ACTION_KEY: i32 = 31;
pub const ACTION_KEY_NL_GROUP: u32 = 1;
pub const ACTION_KEY_PROTO_VERSION: u32 = 1;

/// 内核广播的手势事件载荷 (24 字节内存对齐)
#[repr(C)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ActionKeyEvent {
    pub version: u32,
    pub gesture: u32,
    pub duration_ms: i64,
    pub timestamp_ms: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KernelGesture {
    None = 0,
    ShortPress = 1,
    LongPress = 2,
    DoubleTap = 3,
}

impl KernelGesture {
    pub fn from_u32(val: u32) -> Self {
        match val {
            1 => KernelGesture::ShortPress,
            2 => KernelGesture::LongPress,
            3 => KernelGesture::DoubleTap,
            _ => KernelGesture::None,
        }
    }
}
