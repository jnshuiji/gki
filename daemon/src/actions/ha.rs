// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Home Assistant (HA) Direct Client
 *
 * 核心特性：
 * 1. 纯本地 WiFi 属性判定局域网，0 耗时零网络延迟，严禁阻塞探测。
 * 2. 支持自定义局域网 WiFi 名称 (SSID / 网关 IP)，支持一键自动识别。
 * 3. 处于目标局域网 WiFi 时直连局域网地址，否则瞬间直连公网地址。
 * 4. 原生 /system/bin/curl 上报，完全免疫前后台进程杀死。
 */

use crate::config::HomeAssistantConfig;
use std::fs;
use std::process::Command;

pub struct HaClient;

impl HaClient {
    /// 检查手机当前是否已连接 WiFi (wlan0)
    pub fn is_wifi_connected() -> bool {
        if let Ok(carrier) = fs::read_to_string("/sys/class/net/wlan0/carrier") {
            carrier.trim() == "1"
        } else {
            false
        }
    }

    /// 获取当前连接的 WiFi SSID (纯本地查询，耗时 ~2ms，0 网络流量)
    pub fn get_current_wifi_ssid() -> Option<String> {
        // 方案 1: iw dev wlan0 link (Linux 内核直读，极速)
        let iw_paths = ["/system/bin/iw", "/vendor/bin/iw", "iw"];
        for iw_cmd in iw_paths {
            if let Ok(output) = Command::new(iw_cmd).args(["dev", "wlan0", "link"]).output() {
                if output.status.success() {
                    let text = String::from_utf8_lossy(&output.stdout);
                    for line in text.lines() {
                        let trimmed = line.trim();
                        if let Some(ssid) = trimmed.strip_prefix("SSID: ") {
                            let s = ssid.trim();
                            if !s.is_empty() {
                                return Some(s.to_string());
                            }
                        }
                    }
                }
            }
        }

        // 方案 2: cmd wifi status (Android Framework 回退)
        if let Ok(output) = Command::new("/system/bin/cmd").args(["wifi", "status"]).output() {
            if output.status.success() {
                let text = String::from_utf8_lossy(&output.stdout);
                for line in text.lines() {
                    let trimmed = line.trim();
                    if let Some(rest) = trimmed.strip_prefix("Wifi is connected to \"") {
                        if let Some(ssid) = rest.strip_suffix("\"") {
                            if !ssid.is_empty() {
                                return Some(ssid.to_string());
                            }
                        }
                    }
                }
            }
        }

        // 方案 3: dumpsys wifi 回退
        if let Ok(output) = Command::new("/system/bin/sh")
            .args(["-c", "dumpsys wifi | grep 'mWifiInfo SSID' | head -n 1"])
            .output()
        {
            let text = String::from_utf8_lossy(&output.stdout);
            if let Some(start) = text.find("SSID: \"") {
                let sub = &text[start + 7..];
                if let Some(end) = sub.find('"') {
                    let s = &sub[..end];
                    if !s.is_empty() && s != "<unknown ssid>" {
                        return Some(s.to_string());
                    }
                }
            }
        }

        None
    }

    /// 获取当前连接的 WiFi BSSID (MAC 地址)
    pub fn get_current_wifi_bssid() -> Option<String> {
        let iw_paths = ["/system/bin/iw", "/vendor/bin/iw", "iw"];
        for iw_cmd in iw_paths {
            if let Ok(output) = Command::new(iw_cmd).args(["dev", "wlan0", "link"]).output() {
                if output.status.success() {
                    let text = String::from_utf8_lossy(&output.stdout);
                    if let Some(line) = text.lines().next() {
                        if let Some(rest) = line.trim().strip_prefix("Connected to ") {
                            if let Some(bssid) = rest.split_whitespace().next() {
                                return Some(bssid.to_string());
                            }
                        }
                    }
                }
            }
        }
        None
    }

    /// 获取当前 WiFi 默认网关 IP (纯本地路由表直读)
    pub fn get_current_gateway() -> Option<String> {
        if let Ok(output) = Command::new("/system/bin/sh")
            .args(["-c", "ip route show table 0 2>/dev/null | grep default | grep wlan0 | head -n 1"])
            .output()
        {
            let text = String::from_utf8_lossy(&output.stdout);
            let parts: Vec<&str> = text.split_whitespace().collect();
            for i in 0..parts.len() {
                if parts[i] == "via" && i + 1 < parts.len() {
                    return Some(parts[i + 1].to_string());
                }
            }
        }

        if let Ok(output) = Command::new("/system/bin/sh")
            .args(["-c", "ip route | grep 'dev wlan0.*src' | head -n 1"])
            .output()
        {
            let text = String::from_utf8_lossy(&output.stdout);
            for part in text.split_whitespace() {
                if part.ends_with(".0/24") {
                    return Some(format!("{}.1", part.trim_end_matches(".0/24")));
                }
            }
        }

        None
    }

    /// 根据自定义 WiFi 属性判断是否处于局域网（0 网络请求，纯本地瞬时判断）
    pub fn is_in_lan(config: &HomeAssistantConfig) -> bool {
        if !Self::is_wifi_connected() {
            return false;
        }

        let configured = config.lan_ssid.trim();
        let current_ssid = Self::get_current_wifi_ssid();
        let current_bssid = Self::get_current_wifi_bssid();
        let current_gateway = Self::get_current_gateway();

        if configured.is_empty() {
            // 未配置特定属性时，只要连上 WiFi 即视为局域网
            return true;
        }

        let targets: Vec<&str> = configured
            .split([',', ';', '，', '；'])
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
            .collect();

        // 1. 匹配当前连接的 WiFi SSID
        if let Some(ref ssid) = current_ssid {
            for target in &targets {
                if target.eq_ignore_ascii_case(ssid) {
                    return true;
                }
            }
        }

        // 2. 匹配当前连接的 WiFi BSSID
        if let Some(ref bssid) = current_bssid {
            for target in &targets {
                if target.eq_ignore_ascii_case(bssid) {
                    return true;
                }
            }
        }

        // 3. 匹配网关 IP
        if let Some(ref gw) = current_gateway {
            for target in &targets {
                if target.eq_ignore_ascii_case(gw) {
                    return true;
                }
            }
        }

        false
    }

    /// 依据 WiFi 属性瞬间解析生效的目标服务器地址
    pub fn resolve_active_url(config: &HomeAssistantConfig) -> Result<(String, &'static str), String> {
        let lan_url = config.get_lan_url();
        let wan_url = config.get_wan_url();

        if lan_url.is_empty() && wan_url.is_empty() {
            return Err("未配置 Home Assistant 服务器地址（局域网与公网地址均为空）".to_string());
        }

        if lan_url.is_empty() {
            return Ok((wan_url.to_string(), "公网"));
        }

        if wan_url.is_empty() {
            return Ok((lan_url.to_string(), "局域网"));
        }

        // 纯本地 WiFi 属性判定，0 延迟
        if Self::is_in_lan(config) {
            println!("🏠 [ActionKey-HA] 匹配局域网 WiFi 属性，使用局域网地址: {}", lan_url);
            Ok((lan_url.to_string(), "局域网"))
        } else {
            println!("🌐 [ActionKey-HA] 未连接到局域网 WiFi，使用公网地址: {}", wan_url);
            Ok((wan_url.to_string(), "公网"))
        }
    }

    /// 获取当前本地 ISO 8601 时间戳
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

        let (base_url, net_type) = Self::resolve_active_url(config)?;

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
        let target_url = Self::format_url(&base_url, &format!("api/states/{}", entity_id));
        let auth_header = format!("Authorization: Bearer {}", config.token.trim());

        println!(
            "🌐 [ActionKey-HA] 正在向 HA 发送手势事件 ({}) -> {} [时间: {}]",
            net_type, target_url, iso_time
        );

        let mut cmd = Command::new("/system/bin/curl");
        cmd.args([
            "-k",
            "-s",
            "-S",
            "--connect-timeout", "2",
            "--max-time", "3",
            "-X", "POST",
            "-H", "Content-Type: application/json",
            "-H", &auth_header,
            "-d", &payload_str,
            &target_url,
        ]);

        let output = cmd.output().map_err(|e| format!("执行 curl 失败: {}", e))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let wan_url = config.get_wan_url();
            // 如果局域网发送失败且配置了公网地址，自动回退公网重试
            if net_type == "局域网" && !wan_url.is_empty() {
                println!("⚠️ [ActionKey-HA] 局域网发送失败，立即回退至公网重试...");
                let wan_target = Self::format_url(wan_url, &format!("api/states/{}", entity_id));
                let mut retry_cmd = Command::new("/system/bin/curl");
                retry_cmd.args([
                    "-k", "-s", "-S",
                    "--connect-timeout", "3",
                    "--max-time", "4",
                    "-X", "POST",
                    "-H", "Content-Type: application/json",
                    "-H", &auth_header,
                    "-d", &payload_str,
                    &wan_target,
                ]);
                if let Ok(retry_out) = retry_cmd.output() {
                    if retry_out.status.success() {
                        println!("✅ [ActionKey-HA] 公网回退重试成功！");
                        return Ok(format!("公网发送成功: {}", action));
                    }
                }
            }

            let err = format!("HA 事件上报失败: {}", stderr);
            eprintln!("❌ [ActionKey-HA] {}", err);
            return Err(err);
        }

        let _stdout = String::from_utf8_lossy(&output.stdout);
        println!("✅ [ActionKey-HA] 事件成功注入 Home Assistant！");

        // 异步向 EventBus 广播事件
        let event_bus_name = entity_id.strip_prefix("event.").unwrap_or("action_button");
        let bus_url = Self::format_url(&base_url, &format!("api/events/{}", event_bus_name));
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

        Ok(format!("事件上报成功 ({})", net_type))
    }

    /// 测试与 Home Assistant 服务器的连通性与 Token 有效性
    pub fn test_connection(config: &HomeAssistantConfig) -> Result<String, String> {
        let (active_url, net_type) = Self::resolve_active_url(config)?;

        let test_url = Self::format_url(&active_url, "api/");
        let auth_header = format!("Authorization: Bearer {}", config.token.trim());

        let output = Command::new("/system/bin/curl")
            .args([
                "-k",
                "-s",
                "-S",
                "--connect-timeout", "3",
                "--max-time", "4",
                "-H", &auth_header,
                &test_url,
            ])
            .output()
            .map_err(|e| format!("无法调用 curl: {}", e))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(format!("网络连接失败 ({}): {}", net_type, stderr.trim()));
        }

        let body = String::from_utf8_lossy(&output.stdout);
        if body.contains("API running") {
            Ok(format!("连接成功！当前通过【{}】直连 HA", net_type))
        } else if body.contains("401: Unauthorized") {
            Err(format!("连接到 {}，但 Token 鉴权失败 (401: Unauthorized)", net_type))
        } else {
            Err(format!("服务器响应异常: {}", body.trim()))
        }
    }

    /// 识别当前已连接的 WiFi 属性与局域网配置
    pub fn detect_lan_config() -> Result<serde_json::Value, String> {
        if !Self::is_wifi_connected() {
            return Err("当前未连接到 WiFi".to_string());
        }

        let ssid = Self::get_current_wifi_ssid().unwrap_or_else(|| "".to_string());
        let bssid = Self::get_current_wifi_bssid().unwrap_or_else(|| "".to_string());
        let gateway = Self::get_current_gateway().unwrap_or_else(|| "192.168.1.1".to_string());
        let suggested_url = format!("http://{}:8123", gateway);

        Ok(serde_json::json!({
            "success": true,
            "ssid": ssid,
            "bssid": bssid,
            "gateway": gateway,
            "suggested_lan_url": suggested_url,
            "message": if !ssid.is_empty() {
                format!("已识别当前 WiFi: {}", ssid)
            } else {
                format!("已检测到网关: {}", gateway)
            }
        }))
    }
}
