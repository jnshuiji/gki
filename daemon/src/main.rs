// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Userspace Daemon & WebUI Controller
 *
 * 支持双模运行：
 * 1. 后台守护进程 (Daemon Mode: `run`)：阻塞监听内核 Netlink 事件并执行动作。
 * 2. 命令行控制端 (CLI Mode: `status`, `config`, `test`, `ha`, `torch`)：专供 KernelSU WebUI (ksu.exec) 交互。
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
use std::path::Path;
use std::process;

fn print_usage() {
    println!("Action Key Assistant - 用户态守护进程与 WebUI CLI 控制端");
    println!("Usage: action_key_daemon <command> [args...]");
    println!();
    println!("Commands:");
    println!("  run                          以守护进程模式常驻后台运行，监听 Netlink 手势事件");
    println!("  status                       输出当前驱动、守护进程与配置状态 (JSON 格式，供 WebUI 读取)");
    println!("  config get                   输出当前完整 JSON 配置");
    println!("  config set <gesture> <field> <val>  修改指定手势配置 (field: enabled, action_type, payload, name)");
    println!("  config set-ha <url> <token> [entity] 配置 Home Assistant 连接信息");
    println!("  config set-timeout <ms>      设置双击判定时间窗 (ms)");
    println!("  ha test                      测试与 Home Assistant 服务器的连通性");
    println!("  ha trigger <single|double|long> 手动发送指定事件至 Home Assistant");
    println!("  torch toggle                 手动切换手电筒开/关状态");
    println!("  test <short|double|long>     模拟手势触发（用于 WebUI 调试与测试框架）");
    println!("  help                         显示本帮助信息");
}

fn is_driver_loaded() -> bool {
    Path::new("/sys/module/action_key").exists()
}

fn handle_run() {
    println!("🚀 [ActionKey-Daemon] 正在启动用户态守护进程...");
    let config = AppConfig::load_or_default();
    println!(
        "📄 [ActionKey-Daemon] 已载入配置 (双击判定阈值: {} ms)",
        config.double_tap_timeout_ms
    );
    if config.home_assistant.enabled && !config.home_assistant.base_url.is_empty() {
        println!(
            "🏠 [ActionKey-Daemon] Home Assistant 直连已激活 (目标: {})",
            config.home_assistant.base_url
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
        eprintln!("错误: 缺少 config 子命令 (get, set, set-ha, set-timeout)");
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
            println!("{{\"success\": true, \"message\": \"配置更新成功\"}}");
        }
        "set-ha" => {
            if args.len() < 3 {
                eprintln!("用法: action_key_daemon config set-ha <base_url> <token> [entity_id]");
                process::exit(1);
            }
            let mut config = AppConfig::load_or_default();
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
        "set-timeout" => {
            if args.len() < 2 {
                eprintln!("用法: action_key_daemon config set-timeout <ms>");
                process::exit(1);
            }
            let ms = args[1].parse::<u64>().unwrap_or(300);
            let mut config = AppConfig::load_or_default();
            config.double_tap_timeout_ms = ms;
            if let Err(e) = config.save() {
                eprintln!("保存超时配置失败: {}", e);
                process::exit(1);
            }
            println!("{{\"success\": true, \"message\": \"双击时间窗已更新为 {} ms\"}}", ms);
        }
        _ => {
            eprintln!("未知 config 操作: {}", args[0]);
            process::exit(1);
        }
    }
}

fn handle_ha(args: &[String]) {
    if args.is_empty() {
        eprintln!("用法: action_key_daemon ha <test | trigger <single|double|long>>");
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
    GestureDispatcher::execute(gesture, 150, &config);
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
        "help" | "-h" | "--help" => print_usage(),
        other => {
            eprintln!("未知命令: {}", other);
            print_usage();
            process::exit(1);
        }
    }
}
