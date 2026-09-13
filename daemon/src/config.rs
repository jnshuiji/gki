// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Configuration Management
 *
 * 负责读取、保存与管理单击 (short_press)、双击 (double_tap)、长按 (long_press) 三种手势的配置，
 * 以及 Home Assistant (HA) 服务器与 Token 配置。
 */

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

const DEFAULT_SYS_CONFIG_PATH: &str = "/data/adb/modules/action_key/config.json";
const LOCAL_CONFIG_PATH: &str = "./config.json";

/// Home Assistant 全局直连配置
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct HomeAssistantConfig {
    pub enabled: bool,
    pub base_url: String,   // e.g. "http://192.168.1.100:8123" 或 "https://ha.example.com:8123"
    pub token: String,      // 长期访问令牌 (Long-Lived Access Token)
    pub entity_id: String,  // 目标实体 ID，默认 "event.action_button"
}

impl Default for HomeAssistantConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            base_url: "".to_string(),
            token: "".to_string(),
            entity_id: "event.action_button".to_string(),
        }
    }
}

/// 单一手势动作定义
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct GestureAction {
    pub enabled: bool,
    pub name: String,
    pub description: String,
    pub action_type: String, // "ha", "torch", "shell", "log"
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
    pub version: u32,
    pub double_tap_timeout_ms: u64, // 双击判定等待时间窗 (默认 300 ms)
    pub actions: GestureActions,
    pub home_assistant: HomeAssistantConfig,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            version: 1,
            double_tap_timeout_ms: 300,
            actions: GestureActions {
                // 单击默认: Home Assistant (single)
                short_press: GestureAction {
                    enabled: true,
                    name: "单击 (Short Press)".to_string(),
                    description: "短按实体按键触发 -> 触发 Home Assistant 单击事件".to_string(),
                    action_type: "ha".to_string(),
                    payload: "single".to_string(),
                },
                // 双击默认: Home Assistant (double)
                double_tap: GestureAction {
                    enabled: true,
                    name: "双击 (Double Tap)".to_string(),
                    description: "短时间内连续按两次按键触发 -> 触发 Home Assistant 双击事件".to_string(),
                    action_type: "ha".to_string(),
                    payload: "double".to_string(),
                },
                // 长按默认: 手电筒开关
                long_press: GestureAction {
                    enabled: true,
                    name: "长按 (Long Press)".to_string(),
                    description: "长按按键超过阈值触发 -> 极速开关手电筒".to_string(),
                    action_type: "torch".to_string(),
                    payload: "toggle".to_string(),
                },
            },
            home_assistant: HomeAssistantConfig::default(),
        }
    }
}

impl AppConfig {
    /// 自动探测最适合的配置文件保存路径
    pub fn config_file_path() -> PathBuf {
        let sys_dir = Path::new("/data/adb/modules/action_key");
        if sys_dir.exists() {
            PathBuf::from(DEFAULT_SYS_CONFIG_PATH)
        } else {
            PathBuf::from(LOCAL_CONFIG_PATH)
        }
    }

    /// 加载配置文件，若不存在则创建并写入默认配置
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

    /// 保存配置至 JSON 文件
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
