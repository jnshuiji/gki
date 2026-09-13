// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Configuration Management
 *
 * 负责读取、保存与管理单击 (short_press)、双击 (double_tap)、长按 (long_press) 三种手势的配置。
 */

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

const DEFAULT_SYS_CONFIG_PATH: &str = "/data/adb/modules/action_key/config.json";
const LOCAL_CONFIG_PATH: &str = "./config.json";

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct GestureAction {
    pub enabled: bool,
    pub name: String,
    pub description: String,
    pub action_type: String, // 预留: "log" (当前基础测试), "shell", "torch", "webhook" 等
    pub payload: String,     // 预留参数或描述字符串
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct GestureActions {
    pub short_press: GestureAction,
    pub double_tap: GestureAction,
    pub long_press: GestureAction,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct AppConfig {
    pub version: u32,
    pub double_tap_timeout_ms: u64, // 双击判定等待时间窗 (默认 300 ms)
    pub actions: GestureActions,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            version: 1,
            double_tap_timeout_ms: 300,
            actions: GestureActions {
                short_press: GestureAction {
                    enabled: true,
                    name: "单击 (Short Press)".to_string(),
                    description: "短按实体按键触发".to_string(),
                    action_type: "log".to_string(),
                    payload: "[默认动作] 单击已触发".to_string(),
                },
                double_tap: GestureAction {
                    enabled: true,
                    name: "双击 (Double Tap)".to_string(),
                    description: "短时间内连续按两次按键触发".to_string(),
                    action_type: "log".to_string(),
                    payload: "[默认动作] 双击已触发".to_string(),
                },
                long_press: GestureAction {
                    enabled: true,
                    name: "长按 (Long Press)".to_string(),
                    description: "长按按键超过阈值触发".to_string(),
                    action_type: "log".to_string(),
                    payload: "[默认动作] 长按已触发".to_string(),
                },
            },
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
