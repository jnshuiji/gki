// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Userspace Netlink IPC Protocol
 *
 * Strictly aligned with modules/action_key/src/netlink_ipc.h
 */

pub const NETLINK_ACTION_KEY: i32 = 31;
pub const ACTION_KEY_NL_GROUP: u32 = 1;
pub const ACTION_KEY_PROTO_VERSION: u32 = 2;
pub const ACTION_KEY_MAGIC: u32 = 0x414B4559; // 'AKEY'

/// Kernel multicast gesture or hardware state payload (24 bytes aligned)
#[repr(C, align(8))]
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
    TorchStateChanged = 10,
}

impl KernelGesture {
    pub fn from_u32(val: u32) -> Self {
        match val {
            1 => KernelGesture::ShortPress,
            2 => KernelGesture::LongPress,
            3 => KernelGesture::DoubleTap,
            10 => KernelGesture::TorchStateChanged,
            _ => KernelGesture::None,
        }
    }
}

pub const AK_CMD_SET_CONFIG: u32 = 10;
pub const AK_CMD_TOGGLE_TORCH: u32 = 11;
#[allow(dead_code)]
pub const AK_CMD_SET_TORCH: u32 = 12;

#[repr(C, align(4))]
#[derive(Debug, Clone, Copy)]
pub struct ActionKeyConfigData {
    pub long_press_ms: u32,
    pub long_press_action: u32,
    pub torch_brightness: u32,
}

#[repr(C, align(8))]
#[derive(Debug, Clone, Copy)]
pub struct ActionKeyCmd {
    pub magic: u32,
    pub version: u32,
    pub cmd_type: u32,
    pub reserved: u32,
    pub payload: [u8; 32],
}

impl ActionKeyCmd {
    pub fn new_set_config(cfg: ActionKeyConfigData) -> Self {
        let mut cmd = Self {
            magic: ACTION_KEY_MAGIC,
            version: ACTION_KEY_PROTO_VERSION,
            cmd_type: AK_CMD_SET_CONFIG,
            reserved: 0,
            payload: [0u8; 32],
        };
        unsafe {
            let ptr = cmd.payload.as_mut_ptr() as *mut ActionKeyConfigData;
            *ptr = cfg;
        }
        cmd
    }

    pub fn new_toggle_torch() -> Self {
        Self {
            magic: ACTION_KEY_MAGIC,
            version: ACTION_KEY_PROTO_VERSION,
            cmd_type: AK_CMD_TOGGLE_TORCH,
            reserved: 0,
            payload: [0u8; 32],
        }
    }

    #[allow(dead_code)]
    pub fn new_set_torch(on: bool) -> Self {
        let mut cmd = Self {
            magic: ACTION_KEY_MAGIC,
            version: ACTION_KEY_PROTO_VERSION,
            cmd_type: AK_CMD_SET_TORCH,
            reserved: 0,
            payload: [0u8; 32],
        };
        unsafe {
            let ptr = cmd.payload.as_mut_ptr() as *mut u32;
            *ptr = if on { 1 } else { 0 };
        }
        cmd
    }
}
