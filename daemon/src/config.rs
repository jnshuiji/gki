// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Configuration Management
 *
 * 负责读取、保存与管理单击、双击、长按三种手势配置，
 * 以及 Home Assistant 局域网 WiFi 属性判定、局域网/公网双地址与访问令牌。
 */

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

const DEFAULT_SYS_CONFIG_PATH: &str = "/data/adb/modules/action_key/config.json";
const LOCAL_CONFIG_PATH: &str = "./config.json";

fn default_true() -> bool {
    true
}

fn default_entity_id() -> String {
    "event.action_button".to_string()
}

fn default_version() -> u32 {
    1
}

fn default_double_tap_timeout() -> u64 {
    300
}

fn default_long_press_timeout() -> u64 {
    500
}

/// Home Assistant 全局直连配置
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct HomeAssistantConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default)]
    pub base_url: String, // 兼容历史字段
    #[serde(default)]
    pub internal_url: String, // 局域网地址 (LAN), 例: "http://10.0.0.1:8123"
    #[serde(default)]
    pub external_url: String, // 公网地址 (WAN), 例: "https://ha.example.com:8123"
    #[serde(default)]
    pub lan_ssid: String, // 局域网 WiFi 属性 (SSID / 网段), 例: "C_5G" (支持多名称逗号隔开)
    #[serde(default)]
    pub token: String, // 长期访问令牌 (Long-Lived Access Token)
    #[serde(default = "default_entity_id")]
    pub entity_id: String, // 目标实体 ID，默认 "event.action_button"
}

impl Default for HomeAssistantConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            base_url: "".to_string(),
            internal_url: "".to_string(),
            external_url: "".to_string(),
            lan_ssid: "".to_string(),
            token: "".to_string(),
            entity_id: "event.action_button".to_string(),
        }
    }
}

impl HomeAssistantConfig {
    pub fn get_lan_url(&self) -> &str {
        if !self.internal_url.trim().is_empty() {
            self.internal_url.trim()
        } else {
            self.base_url.trim()
        }
    }

    pub fn get_wan_url(&self) -> &str {
        self.external_url.trim()
    }
}

/// 单一手势动作定义
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct GestureAction {
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub action_type: String, // "ha", "torch", "log"
    #[serde(default)]
    pub payload: String,     // 对于 ha: "single" | "double" | "long"; 对于 torch: "toggle"
}

/// 三手势动作集合
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct GestureActions {
    pub short_press: GestureAction,
    pub double_tap: GestureAction,
    pub long_press: GestureAction,
}

/// 完整应用配置
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct AppConfig {
    #[serde(default = "default_version")]
    pub version: u32,
    #[serde(default = "default_double_tap_timeout")]
    pub double_tap_timeout_ms: u64, // 双击判定等待时间窗 (默认 300 ms)
    #[serde(default = "default_long_press_timeout")]
    pub long_press_timeout_ms: u64, // 长按判定触发时间 (默认 500 ms)
    pub actions: GestureActions,
    pub home_assistant: HomeAssistantConfig,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            version: 1,
            double_tap_timeout_ms: 300,
            long_press_timeout_ms: 500,
            actions: GestureActions {
                short_press: GestureAction {
                    enabled: true,
                    name: "单击".to_string(),
                    description: "短按实体按键触发".to_string(),
                    action_type: "ha".to_string(),
                    payload: "single".to_string(),
                },
                double_tap: GestureAction {
                    enabled: true,
                    name: "双击".to_string(),
                    description: "连续按两次按键触发".to_string(),
                    action_type: "ha".to_string(),
                    payload: "double".to_string(),
                },
                long_press: GestureAction {
                    enabled: true,
                    name: "长按".to_string(),
                    description: "长按按键超过阈值触发".to_string(),
                    action_type: "torch".to_string(),
                    payload: "toggle".to_string(),
                },
            },
            home_assistant: HomeAssistantConfig::default(),
        }
    }
}

impl AppConfig {
    pub fn config_file_path() -> PathBuf {
        let sys_dir = Path::new("/data/adb/modules/action_key");
        if sys_dir.exists() {
            PathBuf::from(DEFAULT_SYS_CONFIG_PATH)
        } else {
            PathBuf::from(LOCAL_CONFIG_PATH)
        }
    }

    pub fn load_or_default() -> Self {
        let path = Self::config_file_path();
        if path.exists() {
            if let Ok(content) = fs::read_to_string(&path) {
                if let Ok(config) = serde_json::from_str::<AppConfig>(&content) {
                    return config;
                }
            }
        }

        let config = AppConfig::default();
        let _ = config.save();
        config
    }

    pub fn save(&self) -> Result<(), String> {
        let path = Self::config_file_path();
        if let Some(parent) = path.parent() {
            if !parent.exists() {
                let _ = fs::create_dir_all(parent);
            }
        }

        let json_str = serde_json::to_string_pretty(self)
            .map_err(|e| format!("序列化配置失败: {}", e))?;
        fs::write(&path, json_str)
            .map_err(|e| format!("写入配置文件 {:?} 失败: {}", path, e))?;
        Ok(())
    }
}
