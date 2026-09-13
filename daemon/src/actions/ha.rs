// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Home Assistant (HA) Direct Client
 *
 * 严格遵循官方 HA 事件规范 (参考 jnshuiji/action-key-assistant):
 * 向 POST /api/states/{entity_id} 注入状态与 event_type 属性。
 * 支持单次毫秒级直接上报，完全免疫前后台进程杀死，支持局域网/公网自签名证书 (-k)。
 */

use crate::config::HomeAssistantConfig;
use std::process::Command;

pub struct HaClient;

impl HaClient {
    /// 获取当前本地 ISO 8601 格式时间字符串
    fn get_iso_timestamp() -> String {
        let now = unsafe { libc::time(std::ptr::null_mut()) };
        let mut tm: libc::tm = unsafe { std::mem::zeroed() };
        unsafe { libc::localtime_r(&now, &mut tm) };

        format!(
            "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}",
            tm.tm_year + 1900,
            tm.tm_mon + 1,
            tm.tm_mday,
            tm.tm_hour,
            tm.tm_min,
            tm.tm_sec
        )
    }

    /// 规范化拼接 URL 路径
    fn format_url(base: &str, endpoint: &str) -> String {
        let trimmed_base = base.trim_end_matches('/');
        let trimmed_endpoint = endpoint.trim_start_matches('/');
        format!("{}/{}", trimmed_base, trimmed_endpoint)
    }

    /// 向 Home Assistant 发送按键手势事件
    /// action: "single" | "double" | "long"
    pub fn send_event(action: &str, config: &HomeAssistantConfig) -> Result<String, String> {
        if !config.enabled {
            return Ok("Home Assistant 处于禁用状态，跳过发送".to_string());
        }

        if config.base_url.trim().is_empty() {
            let warn_msg = "⚠️ HA 服务器地址未配置 (请在 KernelSU WebUI 中填写地址与 Token)";
            eprintln!("[ActionKey-HA] {}", warn_msg);
            return Err(warn_msg.to_string());
        }

        let entity_id = if config.entity_id.trim().is_empty() {
            "event.action_button"
        } else {
            config.entity_id.trim()
        };

        let iso_time = Self::get_iso_timestamp();
        let icon = match action {
            "single" => "mdi:gesture-tap-button",
            "double" => "mdi:gesture-double-tap",
            "long" => "mdi:gesture-tap-hold",
            _ => "mdi:gesture-tap-button",
        };

        // 构建符合 HA 官方 Event Entity 规范的 JSON 数据包
        let payload = serde_json::json!({
            "state": iso_time,
            "attributes": {
                "friendly_name": "快捷按键事件",
                "icon": icon,
                "event_type": action,
                "event_types": ["single", "double", "long"],
                "device_class": "button",
                "source": "KernelSU_ActionKey"
            }
        });

        let payload_str = payload.to_string();
        let target_url = Self::format_url(&config.base_url, &format!("api/states/{}", entity_id));
        let auth_header = format!("Authorization: Bearer {}", config.token.trim());

        println!(
            "🌐 [ActionKey-HA] 正在向 HA 注入手势事件: {} -> {} (时间戳: {})",
            action, entity_id, iso_time
        );

        // 调用 Android 原生 /system/bin/curl 进行非阻塞安全请求
        let mut cmd = Command::new("/system/bin/curl");
        cmd.args([
            "-k",               // 允许局域网自签名 SSL 证书
            "-s",               // 静默模式
            "-S",               // 出错时输出错误信息
            "--connect-timeout", "2", // 连接超时 2 秒
            "--max-time", "3",        // 最大耗时 3 秒
            "-X", "POST",
            "-H", "Content-Type: application/json",
            "-H", &auth_header,
            "-d", &payload_str,
            &target_url,
        ]);

        let output = cmd.output().map_err(|e| format!("执行 curl 失败: {}", e))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let err = format!("HA 事件上报失败 (curl error): {}", stderr);
            eprintln!("❌ [ActionKey-HA] {}", err);
            return Err(err);
        }

        let stdout = String::from_utf8_lossy(&output.stdout);
        println!("✅ [ActionKey-HA] 事件已成功注入 Home Assistant！");

        // 异步尝试广播至 EventBus (/api/events/action_button)
        let event_bus_name = entity_id.strip_prefix("event.").unwrap_or("action_button");
        let bus_url = Self::format_url(&config.base_url, &format!("api/events/{}", event_bus_name));
        let bus_payload = serde_json::json!({
            "action": action,
            "device": "ActionKey",
            "timestamp": iso_time
        })
        .to_string();

        let _ = Command::new("/system/bin/curl")
            .args([
                "-k", "-s", "--max-time", "2",
                "-X", "POST",
                "-H", "Content-Type: application/json",
                "-H", &auth_header,
                "-d", &bus_payload,
                &bus_url,
            ])
            .spawn();

        Ok(format!("事件上报成功: {} ({})", action, stdout))
    }

    /// 测试与 Home Assistant 服务器的连通性与 Token 有效性
    pub fn test_connection(config: &HomeAssistantConfig) -> Result<String, String> {
        if config.base_url.trim().is_empty() {
            return Err("HA 服务器地址不能为空！".to_string());
        }

        let test_url = Self::format_url(&config.base_url, "api/");
        let auth_header = format!("Authorization: Bearer {}", config.token.trim());

        let output = Command::new("/system/bin/curl")
            .args([
                "-k", "-s", "-i",
                "--connect-timeout", "3",
                "--max-time", "4",
                "-H", &auth_header,
                &test_url,
            ])
            .output()
            .map_err(|e| format!("无法连接 HA: {}", e))?;

        let response = String::from_utf8_lossy(&output.stdout);
        if response.contains("401 Unauthorized") {
            return Err("认证失败 (HTTP 401)：长期访问令牌 (Token) 无效或已过期".to_string());
        }

        if response.contains("200 OK") || response.contains("API running") {
            return Ok("🎉 连接成功！Home Assistant API 正常运行中。".to_string());
        }

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(format!("连接超时或失败: {}", stderr));
        }

        Ok(format!("连接返回: {}", response.lines().next().unwrap_or("未知")))
    }
}
