// SPDX-License-Identifier: GPL-2.0
//! Action Key Assistant - Native Rust Kernel Module
//!
//! OnePlus 15T Action Key Remapper & Hardware Gesture Controller.
//! Built on Rust for Linux (RFL) and Linux 6.12 GKI.

use kernel::prelude::*;

module! {
    type: ActionKeyModule,
    name: "action_key",
    author: "pochita",
    description: "Action Key Driver in Rust for Android 16",
    license: "GPL",
}

extern "C" {
    fn action_key_register_bridge() -> core::ffi::c_int;
    fn action_key_unregister_bridge();

    fn action_key_netlink_init() -> core::ffi::c_int;
    fn action_key_netlink_exit();
}

struct ActionKeyModule;

impl kernel::Module for ActionKeyModule {
    fn init(_module: &'static ThisModule) -> Result<Self> {
        pr_warn!("Initializing Action Key driver (Target: KeyCode 735, GKI 6.12)\n");

        // 1. Initialize full-duplex Netlink IPC
        let nl_ret = unsafe { action_key_netlink_init() };
        if nl_ret != 0 {
            pr_warn!("Failed to initialize Netlink IPC: {}\n", nl_ret);
            return Err(Error::from_errno(nl_ret));
        }

        // 2. Register Linux input filter & LED trigger
        let bridge_ret = unsafe { action_key_register_bridge() };
        if bridge_ret != 0 {
            pr_warn!("Failed to register input bridge: {}\n", bridge_ret);
            unsafe { action_key_netlink_exit() };
            return Err(Error::from_errno(bridge_ret));
        }

        pr_warn!("Action Key driver initialized successfully\n");
        Ok(ActionKeyModule)
    }
}

impl Drop for ActionKeyModule {
    fn drop(&mut self) {
        unsafe {
            action_key_unregister_bridge();
            action_key_netlink_exit();
        }
        pr_warn!("Action Key driver unloaded successfully\n");
    }
}
