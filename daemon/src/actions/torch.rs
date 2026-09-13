// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Flashlight / Torch Controller
 *
 * 通过 Android 系统级 Quick Settings / SystemUI 控制链切换手电筒。
 * 优势：与系统状态栏图标 100% 同步，黑屏与锁屏状态下无缝工作，相机启动时自动互斥避让。
 */

use std::process::Command;

pub struct TorchController;

impl TorchController {
    /// 切换手电筒开/关状态
    pub fn toggle() -> Result<String, String> {
        println!("🔦 [ActionKey-Torch] 正在请求系统切换手电筒...");

        // 优先使用 Android 系统通用命令: cmd statusbar click-tile flashlight
        let output = Command::new("/system/bin/cmd")
            .args(["statusbar", "click-tile", "flashlight"])
            .output();

        match output {
            Ok(out) if out.status.success() => {
                let msg = "手电筒切换指令已发送 (cmd statusbar click-tile flashlight)";
                println!("✅ [ActionKey-Torch] {}", msg);
                Ok(msg.to_string())
            }
            Ok(out) => {
                let err = String::from_utf8_lossy(&out.stderr).to_string();
                let msg = format!("cmd statusbar 执行返回非零: {}", err);
                eprintln!("⚠️ [ActionKey-Torch] {}", msg);
                // 尝试通用 fallback: 通过 sh 调用
                Self::fallback_toggle()
            }
            Err(e) => {
                eprintln!("⚠️ [ActionKey-Torch] 直接调用 cmd 失败: {}, 尝试 sh fallback", e);
                Self::fallback_toggle()
            }
        }
    }

    /// 备选方案: 通过 shell 执行系统命令
    fn fallback_toggle() -> Result<String, String> {
        let output = Command::new("/system/bin/sh")
            .args(["-c", "cmd statusbar click-tile flashlight"])
            .output();

        match output {
            Ok(out) if out.status.success() => {
                Ok("手电筒切换成功 (via fallback shell)".to_string())
            }
            Ok(out) => {
                let err = String::from_utf8_lossy(&out.stderr).to_string();
                Err(format!("手电筒切换失败: {}", err))
            }
            Err(e) => Err(format!("无法执行手电筒控制命令: {}", e)),
        }
    }
}
