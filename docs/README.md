# GKI 工程技术文档中心

欢迎查阅 Android GKI 内核构建与 AnyKernel3 自动化套件的工程技术文档。

---

## 📚 目录结构

```text
docs/
├── README.md                           # 本文档（文档中心索引）
└── troubleshooting/                    # 关键踩坑与技术排错复盘记录
    ├── 01-anykernel3-block-device-adaptation.md   # AnyKernel3 刷机模板现代架构适配
    ├── 02-gki-kmi-generation-mismatch.md          # GKI KMI 代际断代导致真机 BootLoop 排错
    └── 03-module-sig-protect-wireless-failure.md   # GKI 模块签名保护导致无线网络/蓝牙瘫痪排错
```

---

## 🛠️ 关键技术复盘与排错日志 (Troubleshooting Reports)

| 编号 | 故障主题 | 涉及平台 / 模块 | 影响等级 | 文档链接 |
| :---: | :--- | :--- | :--- | :--- |
| **01** | AnyKernel3 模板架构未适配导致刷入中断 | AnyKernel3 / Boot Header v4 / A/B 分区 | 🔴 高 | [查看排错日志](troubleshooting/01-anykernel3-block-device-adaptation.md) |
| **02** | GKI KMI 代际断代导致真机开机无限重启 (BootLoop) | GKI 2.0 / KMI 5 vs 6 / ColorOS 厂商模块 | 🔴 高 | [查看排错日志](troubleshooting/02-gki-kmi-generation-mismatch.md) |
| **03** | 模块签名保护机制导致 WiFi、蓝牙与蜂窝网络瘫痪 | GKI 签名保护 / `rfkill` / 高通 WLAN 驱动 / `sig_ok` | 🔴 高 | [查看排错日志](troubleshooting/03-module-sig-protect-wireless-failure.md) |

---

## 💡 开发者备忘录

- **KMI 版本核对原则**：
  在拉取 AOSP 主线代码前，务必先通过 `modinfo` 或 `uname -a` 确认目标真机的 KMI 代际（例如 `android16-5` 还是 `android16-6`），并基于对应精准 Tag 检出分支，以避免模块 ABI 不兼容。
- **AnyKernel3 刷机包规范**：
  面向 Android 13+ 的 GKI 内核包必须采用 `split_boot; flash_boot;` 模式，切勿对 `boot.img` 执行 `dump_boot` 解包 Ramdisk。
