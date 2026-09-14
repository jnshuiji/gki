// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Userspace Daemon & WebUI Controller
 *
 * Modes:
 * 1. Daemon Mode (`run`): Listens for kernel Netlink events and executes mapped actions.
 * 2. CLI Mode (`status`, `config`, `test`, `ha`, `torch`): Invoked by KernelSU WebUI (ksu.exec).
 */

mod actions;
mod config;
mod dispatcher;
mod netlink;
mod protocol;

use actions::ha::HaClient;
use actions::torch::TorchController;
use config::AppConfig;
use dispatcher::{GestureDispatcher, ResolvedGesture};
use netlink::NetlinkListener;
use protocol::ACTION_KEY_PROTO_VERSION;
use std::env;
use std::fs;
use std::path::Path;
use std::process;

fn print_usage() {
    println!("Action Key Assistant - 用户态守护进程与 WebUI CLI 控制端");
    println!("Usage: action_key_daemon <command> [args...]");
    println!();
    println!("Commands:");
    println!("  run                                      常驻后台监听 Netlink 手势事件");
    println!("  status                                   输出当前驱动、守护进程与配置状态 (JSON)");
    println!("  config get                               输出当前完整 JSON 配置");
    println!("  config set <gesture> <field> <val>       修改指定手势配置");
    println!("  config set-ha <url> <token> [entity]     配置单地址 HA");
    println!("  config set-ha-dual <lan> <wan> <token>   配置局域网与公网双地址 HA");
    println!("  config set-timeout <ms>                  设置双击判定时间窗 (ms)");
    println!("  config set-longpress-timeout <ms>        设置长按判定触发时间 (ms)");
    println!("  ha test                                  测试与 Home Assistant 服务器的连通性");
    println!("  ha trigger <single|double|long>          手动发送指定事件至 Home Assistant");
    println!("  ha detect-lan                            自动探测当前 WiFi 局域网并获取 HA 网关");
    println!("  torch toggle                             手动切换手电筒开/关状态");
    println!("  test <short|double|long>                 模拟手势触发");
    println!("  help                                     显示帮助");
}

fn is_driver_loaded() -> bool {
    Path::new("/sys/module/action_key").exists()
}

fn sync_kernel_config(config: &AppConfig) {
    if !is_driver_loaded() {
        return;
    }
    let long_press_action = if config.actions.long_press.enabled && config.actions.long_press.action_type == "torch" {
        0 // AK_LP_ACTION_TORCH_KERNEL
    } else {
        1 // AK_LP_ACTION_DISPATCH_USER
    };
    let kernel_cfg = crate::protocol::ActionKeyConfigData {
        long_press_ms: config.long_press_timeout_ms.clamp(100, 3000) as u32,
        long_press_action,
        torch_brightness: 200,
    };
    let cmd = crate::protocol::ActionKeyCmd::new_set_config(kernel_cfg);
    let _ = crate::netlink::send_kernel_cmd(&cmd);
}

fn handle_run() {
    println!("🚀 [ActionKey-Daemon] 正在启动用户态守护进程...");
    let config = AppConfig::load_or_default();
    println!(
        "📄 [ActionKey-Daemon] 已载入配置 (双击: {} ms, 长按: {} ms)",
        config.double_tap_timeout_ms, config.long_press_timeout_ms
    );
    if config.home_assistant.enabled {
        let lan = config.home_assistant.get_lan_url();
        let wan = config.home_assistant.get_wan_url();
        println!(
            "🏠 [ActionKey-Daemon] Home Assistant 已配置 (局域网: '{}', 公网: '{}')",
            lan, wan
        );
    }

    let dispatcher = GestureDispatcher::new();

    println!("🔗 [ActionKey-Daemon] 正在连接内核 Netlink 套接字 (Protocol 31, Group 1)...");
    let listener = match NetlinkListener::bind() {
        Ok(l) => {
            println!("✅ [ActionKey-Daemon] Netlink 套接字绑定成功，开始监听按键事件！");
            let _ = std::process::Command::new("/system/bin/log")
                .args(["-t", "ActionKey", "🚀 ActionKey 用户态守护进程已启动，开始监听按键事件"])
                .spawn();

            // 1. 同步初始硬件配置至内核
            let long_press_action = if config.actions.long_press.enabled && config.actions.long_press.action_type == "torch" {
                0
            } else {
                1
            };
            let kernel_cfg = crate::protocol::ActionKeyConfigData {
                long_press_ms: config.long_press_timeout_ms.clamp(100, 3000) as u32,
                long_press_action,
                torch_brightness: 200,
            };
            if let Err(e) = l.send_cmd(&crate::protocol::ActionKeyCmd::new_set_config(kernel_cfg)) {
                eprintln!("⚠️ [ActionKey-Daemon] 下发初始配置至内核失败: {}", e);
            } else {
                println!(
                    "✔ [ActionKey-Daemon] 已向内核同步硬件配置 (长按阈值: {}ms, action: {})",
                    kernel_cfg.long_press_ms, long_press_action
                );
            }

            // 2. 绑定 sysfs 闪光灯触发器至 action_key_torch
            let _ = std::fs::write("/sys/class/leds/white:flash-1/trigger", "action_key_torch");
            let _ = std::fs::write("/sys/class/leds/yellow:flash-0/trigger", "action_key_torch");

            l
        }
        Err(e) => {
            eprintln!("❌ [ActionKey-Daemon] 绑定 Netlink 失败: {}", e);
            eprintln!("   提示: 请确认 action_key.ko 是否已加载，且拥有 root 权限。");
            process::exit(1);
        }
    };

    loop {
        match listener.recv_event() {
            Ok(event) => {
                if event.version != ACTION_KEY_PROTO_VERSION {
                    eprintln!(
                        "⚠️ 收到版本不匹配的 Netlink 数据包 (期望: {}, 实际: {})",
                        ACTION_KEY_PROTO_VERSION, event.version
                    );
                    continue;
                }
                dispatcher.push_event(event);
            }
            Err(e) => {
                eprintln!("❌ [ActionKey-Daemon] 读取 Netlink 数据包异常: {}", e);
            }
        }
    }
}

fn handle_status() {
    let config = AppConfig::load_or_default();
    let driver_loaded = is_driver_loaded();
    let config_path = AppConfig::config_file_path();

    let status = serde_json::json!({
        "driver_loaded": driver_loaded,
        "config_path": config_path.to_string_lossy(),
        "config": config,
    });

    println!("{}", serde_json::to_string_pretty(&status).unwrap());
}

fn handle_config(args: &[String]) {
    if args.is_empty() {
        eprintln!("错误: 缺少 config 子命令");
        process::exit(1);
    }

    match args[0].as_str() {
        "get" => {
            let config = AppConfig::load_or_default();
            println!("{}", serde_json::to_string_pretty(&config).unwrap());
        }
        "set" => {
            if args.len() < 4 {
                eprintln!("用法: action_key_daemon config set <short_press|double_tap|long_press> <enabled|action_type|payload|name> <value>");
                process::exit(1);
            }
            let gesture_key = &args[1];
            let field_key = &args[2];
            let value = &args[3];

            let mut config = AppConfig::load_or_default();
            let action = match gesture_key.as_str() {
                "short_press" => &mut config.actions.short_press,
                "double_tap" => &mut config.actions.double_tap,
                "long_press" => &mut config.actions.long_press,
                _ => {
                    eprintln!("未知手势类型: {}", gesture_key);
                    process::exit(1);
                }
            };

            match field_key.as_str() {
                "enabled" => {
                    action.enabled = value.parse::<bool>().unwrap_or(true);
                }
                "action_type" => {
                    action.action_type = value.to_string();
                }
                "payload" => {
                    action.payload = value.to_string();
                }
                "name" => {
                    action.name = value.to_string();
                }
                _ => {
                    eprintln!("未知字段: {}", field_key);
                    process::exit(1);
                }
            }

            if let Err(e) = config.save() {
                eprintln!("保存配置失败: {}", e);
                process::exit(1);
            }

            sync_kernel_config(&config);
            println!("{{\"success\": true, \"message\": \"配置更新成功\"}}");
        }
        "set-ha" => {
            if args.len() < 3 {
                eprintln!("用法: action_key_daemon config set-ha <lan_url> <token> [entity_id]");
                process::exit(1);
            }
            let mut config = AppConfig::load_or_default();
            config.home_assistant.internal_url = args[1].clone();
            config.home_assistant.base_url = args[1].clone();
            config.home_assistant.token = args[2].clone();
            if args.len() >= 4 {
                config.home_assistant.entity_id = args[3].clone();
            }
            if let Err(e) = config.save() {
                eprintln!("保存 HA 配置失败: {}", e);
                process::exit(1);
            }
            println!("{{\"success\": true, \"message\": \"Home Assistant 配置已更新\"}}");
        }
        "set-ha-dual" => {
            if args.len() < 5 {
                eprintln!("用法: action_key_daemon config set-ha-dual <lan_url> <wan_url> <lan_ssid> <token> [entity_id]");
                process::exit(1);
            }
            let mut config = AppConfig::load_or_default();
            config.home_assistant.internal_url = args[1].clone();
            config.home_assistant.base_url = args[1].clone();
            config.home_assistant.external_url = args[2].clone();
            config.home_assistant.lan_ssid = args[3].clone();
            config.home_assistant.token = args[4].clone();
            if args.len() >= 6 {
                config.home_assistant.entity_id = args[5].clone();
            }
            if let Err(e) = config.save() {
                eprintln!("保存 HA 双地址与局域网 WiFi 属性配置失败: {}", e);
                process::exit(1);
            }
            println!("{{\"success\": true, \"message\": \"Home Assistant 配置已更新\"}}");
        }
        "set-ha-ssid" => {
            if args.len() < 2 {
                eprintln!("用法: action_key_daemon config set-ha-ssid <lan_ssid>");
                process::exit(1);
            }
            let mut config = AppConfig::load_or_default();
            config.home_assistant.lan_ssid = args[1].clone();
            if let Err(e) = config.save() {
                eprintln!("保存局域网 WiFi 属性配置失败: {}", e);
                process::exit(1);
            }
            println!("{{\"success\": true, \"message\": \"局域网 WiFi 属性已更新\"}}");
        }
        "set-timeout" => {
            if args.len() < 2 {
                eprintln!("用法: action_key_daemon config set-timeout <ms>");
                process::exit(1);
            }
            let ms = args[1].parse::<u64>().unwrap_or(300);
            let mut config = AppConfig::load_or_default();
            config.double_tap_timeout_ms = ms;
            if let Err(e) = config.save() {
                eprintln!("保存双击超时失败: {}", e);
                process::exit(1);
            }
            println!("{{\"success\": true, \"message\": \"双击时间窗已更新为 {} ms\"}}", ms);
        }
        "set-longpress-timeout" => {
            if args.len() < 2 {
                eprintln!("用法: action_key_daemon config set-longpress-timeout <ms>");
                process::exit(1);
            }
            let ms = args[1].parse::<u64>().unwrap_or(500);
            let mut config = AppConfig::load_or_default();
            config.long_press_timeout_ms = ms;
            if let Err(e) = config.save() {
                eprintln!("保存长按配置失败: {}", e);
                process::exit(1);
            }
            sync_kernel_config(&config);
            println!("{{\"success\": true, \"message\": \"长按触发时间已更新为 {} ms\"}}", ms);
        }
        _ => {
            eprintln!("未知 config 操作: {}", args[0]);
            process::exit(1);
        }
    }
}

fn handle_ha(args: &[String]) {
    if args.is_empty() {
        eprintln!("用法: action_key_daemon ha <test | trigger <single|double|long> | detect-lan>");
        process::exit(1);
    }

    let config = AppConfig::load_or_default();

    match args[0].as_str() {
        "test" => match HaClient::test_connection(&config.home_assistant) {
            Ok(msg) => println!("{}", msg),
            Err(e) => {
                eprintln!("❌ {}", e);
                process::exit(1);
            }
        },
        "trigger" => {
            let action = args.get(1).map(|s| s.as_str()).unwrap_or("single");
            match HaClient::send_event(action, &config.home_assistant) {
                Ok(msg) => println!("{}", msg),
                Err(e) => {
                    eprintln!("❌ {}", e);
                    process::exit(1);
                }
            }
        }
        "detect-lan" => match HaClient::detect_lan_config() {
            Ok(val) => println!("{}", serde_json::to_string(&val).unwrap()),
            Err(err) => {
                let err_val = serde_json::json!({
                    "success": false,
                    "message": err
                });
                println!("{}", serde_json::to_string(&err_val).unwrap());
            }
        },
        _ => {
            eprintln!("未知 HA 命令: {}", args[0]);
            process::exit(1);
        }
    }
}

fn handle_torch(args: &[String]) {
    let action = args.get(0).map(|s| s.as_str()).unwrap_or("toggle");
    match action {
        "toggle" => match TorchController::toggle() {
            Ok(msg) => println!("{}", msg),
            Err(e) => {
                eprintln!("❌ {}", e);
                process::exit(1);
            }
        },
        _ => {
            eprintln!("未知手电筒操作: {}", action);
            process::exit(1);
        }
    }
}

fn handle_test(args: &[String]) {
    if args.is_empty() {
        eprintln!("用法: action_key_daemon test <short|double|long>");
        process::exit(1);
    }

    let config = AppConfig::load_or_default();
    let gesture = match args[0].as_str() {
        "short" => ResolvedGesture::ShortPress,
        "double" => ResolvedGesture::DoubleTap,
        "long" => ResolvedGesture::LongPress,
        other => {
            eprintln!("未知测试手势: {} (可选: short, double, long)", other);
            process::exit(1);
        }
    };

    println!("🧪 [ActionKey-Test] 正在触发模拟手势: {:?}", gesture);
    GestureDispatcher::execute(gesture, 150, &config, false);
}

fn handle_logs(args: &[String]) {
    let lines_count: usize = args.get(0).and_then(|s| s.parse().ok()).unwrap_or(25);
    let log_path = "/data/adb/modules/action_key/daemon.log";
    if let Ok(content) = fs::read_to_string(log_path) {
        let lines: Vec<&str> = content.lines().filter(|l| !l.trim().is_empty()).collect();
        let start = if lines.len() > lines_count {
            lines.len() - lines_count
        } else {
            0
        };
        let recent = lines[start..].join("\n");
        if recent.trim().is_empty() {
            println!("等待手势操作...");
        } else {
            println!("{}", recent);
        }
    } else {
        println!("等待手势操作...");
    }
}

fn handle_clear_logs() {
    let log_path = "/data/adb/modules/action_key/daemon.log";
    let _ = fs::write(log_path, "");
    println!("{{\"success\": true, \"message\": \"日志已清空\"}}");
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        print_usage();
        return;
    }

    match args[1].as_str() {
        "run" => handle_run(),
        "status" => handle_status(),
        "config" => handle_config(&args[2..]),
        "ha" => handle_ha(&args[2..]),
        "torch" => handle_torch(&args[2..]),
        "test" => handle_test(&args[2..]),
        "logs" => handle_logs(&args[2..]),
        "clear-logs" => handle_clear_logs(),
        "help" | "-h" | "--help" => print_usage(),
        other => {
            eprintln!("未知命令: {}", other);
            print_usage();
            process::exit(1);
        }
    }
}
