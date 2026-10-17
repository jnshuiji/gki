# GKI 工程技术文档中心

本目录归档 Android GKI 内核构建、补丁集维护、排错复盘与扩展模块的技术规范。

---

## 1. 目录索引

```text
docs/
├── README.md                           # 技术文档索引（本文档）
├── maintenance/                        # 系统升级与日常维护规范
│   └── kmi-ota-update-and-patch-management.md # KMI 代际对齐与厂商 OTA 持续维护规范
└── troubleshooting/                    # 故障排查与技术复盘报告
    ├── 01-anykernel3-block-device-adaptation.md   # AnyKernel3 刷机模板架构适配
    ├── 02-gki-kmi-generation-mismatch.md          # GKI KMI 代际对齐与版本锁定
    └── 03-module-sig-protect-wireless-failure.md   # GKI 模块签名保护放行
```

---

## 2. 持续维护与技术规范

| 专题 | 文档主题 | 适用场景 / 核心机制 | 文档链接 |
| :---: | :--- | :--- | :--- |
| **维护指南** | KMI 代际对齐与厂商 OTA 持续维护规范 | 手机厂商推送系统更新后的出厂基线识别、Git 变基实战与补丁集同步 | [kmi-ota-update-and-patch-management.md](maintenance/kmi-ota-update-and-patch-management.md) |

---

## 3. 故障复盘与技术报告

| 编号 | 报告主题 | 涉及平台 / 机制 | 严重等级 | 文档链接 |
| :---: | :--- | :--- | :---: | :--- |
| **01** | AnyKernel3 模板架构未适配导致刷入中断 | Boot Header v4 / A/B 槽位检测 / init_boot 解耦 | 高 | [01-anykernel3-block-device-adaptation.md](troubleshooting/01-anykernel3-block-device-adaptation.md) |
| **02** | GKI KMI 代际断代导致真机开机无限重启 | KMI Generation / ABI 向后兼容 / 厂商驱动 vermagic 校验 | 高 | [02-gki-kmi-generation-mismatch.md](troubleshooting/02-gki-kmi-generation-mismatch.md) |
| **03** | 模块签名保护机制导致网络与无线驱动受阻 | `CONFIG_MODULE_SIG_PROTECT` / 保护符号导出 / `rfkill` 级联依赖 | 高 | [03-module-sig-protect-wireless-failure.md](troubleshooting/03-module-sig-protect-wireless-failure.md) |

---

## 3. 内核补丁与扩展规范

### 3.1 官方内核补丁集 (`patches/android16-6.12/`)
1. **`0001-kernel-configs-bypass-module-sig-protect-and-enable-network-configs.patch`**：
   - 移除 `kernel/module/main.c` 中针对未签名模块导出受保护符号的 `-EACCES` 强行阻断，显式置位 `mod->sig_ok = true`。
   - 在 `kernel/module/signing.c` 中，将非致命签名异常（未签名、无对应公钥等）的 `info->sig_ok` 置为 `true`。
   - 在 `arch/arm64/configs/gki_defconfig` 中内建 `CONFIG_TCP_CONG_ADVANCED=y`、`CONFIG_TCP_CONG_BBR=y`，并开启 `CONFIG_IP_NF_TARGET_TTL=y` 及 `CONFIG_IP6_NF_TARGET_HL=y`。
2. **`0002-feat-integrate-KernelSU-v3.3.0-and-SuSFS-2.3.0-in-tr.patch`**：
   - 树内集成 KernelSU v3.3.0 (`drivers/kernelsu/`) 与 SuSFS 2.3.0 (`fs/susfs.c`)。

### 3.2 运行时伴侣服务 (`modules/pochita/`)
- 负责系统完全启动（`sys.boot_completed=1`）后的网络参数切换与防火墙规则应用。
- 详细说明请参见 [modules/pochita/README.md](../modules/pochita/README.md)。

---

## 4. 开发与维护准则

- **KMI 代际锁定**：拉取 AOSP 主线代码前，必须核对真机环境中的 KMI 版本（例如 `uname -r` 或模块 `vermagic`），基于准确的 Release Tag 建立分支，避免跨代破坏 ABI。
- **Boot 镜像刷入模式**：针对 Android 13+ 架构，`boot.img` 不包含 Ramdisk，必须采用 `split_boot; flash_boot;` 模式更新内核镜像，避免触发解包异常。
