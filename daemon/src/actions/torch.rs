// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Flashlight / Torch Controller
 *
 * 核心设计（路线 B：内核硬件直驱）：
 * 1. 优先通过全双工 Netlink 向 action_key.ko 发送 AK_CMD_TOGGLE_TORCH 指令；
 * 2. 内核中断底半部瞬间驱动 PMIC 硬件通路，零常驻 Java 进程，0ms 物理瞬发；
 * 3. 硬件直接供电常亮，绝对不会被 CameraService 自动熄灭；
 * 4. 备用通道支持直接操作 /sys/class/leds/white:flash-1 节点。
 */

use crate::netlink::send_kernel_cmd;
use crate::protocol::ActionKeyCmd;

pub struct TorchController;

impl TorchController {
    /// 切换手电筒开/关状态
    pub fn toggle() -> Result<String, String> {
        println!("🔦 [ActionKey-Torch] 正在请求内核直驱切换硬件手电筒...");

        // 通道 1: 通过全双工 Netlink 向内核发送切换指令
        let cmd = ActionKeyCmd::new_toggle_torch();
        match send_kernel_cmd(&cmd) {
            Ok(()) => {
                let msg = "手电筒指令已发送至内核驱动 (0ms 硬件直驱)";
                println!("✅ [ActionKey-Torch] {}", msg);
                Ok(msg.to_string())
            }
            Err(e) => {
                eprintln!("⚠️ [ActionKey-Torch] Netlink 下发失败: {}, 尝试 sysfs 备用通道", e);
                Self::fallback_sysfs_toggle()
            }
        }
    }

    /// 备用通道: 直接读写 sysfs 亮度节点
    fn fallback_sysfs_toggle() -> Result<String, String> {
        let white_path = "/sys/class/leds/white:flash-1/brightness";
        let cur_br = std::fs::read_to_string(white_path)
            .unwrap_or_else(|_| "0".to_string())
            .trim()
            .parse::<u32>()
            .unwrap_or(0);

        let target_br = if cur_br > 0 { 0 } else { 200 };

        let res_white = std::fs::write(white_path, target_br.to_string());
        let _ = std::fs::write("/sys/class/leds/yellow:flash-0/brightness", target_br.to_string());

        match res_white {
            Ok(_) => {
                let msg = format!("已通过 sysfs 切换硬件手电筒亮度为: {}", target_br);
                println!("✅ [ActionKey-Torch] {}", msg);
                Ok(msg)
            }
            Err(e) => {
                let err_msg = format!("sysfs 控制失败: {}", e);
                eprintln!("❌ [ActionKey-Torch] {}", err_msg);
                Err(err_msg)
            }
        }
    }
}
