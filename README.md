# GKI 自动化构建与打包工具套件

本项目提供了针对 Android GKI 内核的高效自动化构建与 AnyKernel3 打包工具。
基于 `uv` 虚拟环境与 Python 现代化 CLI 构建，支持快速编译、耗时统计、产物检查以及 Recovery 刷机包一键生成。

---

## ⚡ 快速使用

### 1. 便捷启动脚本 (`./build.sh`)
根目录下已配置 `build.sh`，可直接运行：

```bash
# 启动交互式菜单（推荐，引导式选择）
./build.sh

# 快速编译并自动打包 AnyKernel3 ZIP（默认 android16-6.12，--lto=none）
./build.sh build

# 仅打包现有 Image 为 AnyKernel3 ZIP（无需重新编译）
./build.sh package

# 查看系统资源与编译产物状态
./build.sh info

# 清理 Bazel 缓存
./build.sh clean
```

### 2. 通过 `uv run` 运行高级参数

```bash
# 查看完整帮助
uv run gki --help

# 常用构建命令示例
uv run gki build --lto none                     # 极速开发编译（不开启 LTO）
uv run gki build --lto thin                     # 生产/测试编译（开启 ThinLTO）
uv run gki build --clean                        # 先清理 Bazel 缓存再编译
uv run gki build --no-ak3                       # 仅编译内核，不生成 AnyKernel3 ZIP
uv run gki build --dry-run                      # 仅预览构建指令，不实际执行
```

---

## ⚙️ 配置文件说明 (`build_config.yaml`)

项目行为可通过根目录的 `build_config.yaml` 灵活定制：

```yaml
default_kernel: "android16-6.12"

kernels:
  android16-6.12:
    name: "Android 16 (Linux 6.12 GKI)"
    path: "android16-6.12"
    build_system: "kleaf"
    default_target: "//common:kernel_aarch64_dist"
    default_lto: "none"
    destdir: "out/dist"
    image_relpath: "out/dist/Image"

anykernel3:
  enabled: true
  template_dir: "tools/AnyKernel3"
  output_dir: "out/release"
  zip_name_template: "AnyKernel3-{branch}-{timestamp}.zip"
  auto_patch_devicecheck: true   # 通用 GKI 自动适配（将 do.devicecheck 设为 0）
```

---

## 📦 打包产物目录

- **内核直出产物**：`android16-6.12/out/dist/Image`
- **AnyKernel3 刷机包**：`out/release/AnyKernel3-android16-6.12-<timestamp>.zip`
- **最新刷机包软链接**：`out/release/AnyKernel3-android16-6.12-latest.zip`

---

## 📚 关键踩坑与技术排错复盘

在实际构建与真机刷入适配过程中，我们攻克并系统复盘了三大典型问题，已按工程标准归档至专门的技术文档目录：

| 故障主题 | 对应技术排错报告 |
| :--- | :--- |
| **AnyKernel3 刷机模板架构未适配报错** | [01-anykernel3-block-device-adaptation.md](docs/troubleshooting/01-anykernel3-block-device-adaptation.md) |
| **GKI KMI 跨代断代导致真机死循环 (BootLoop)** | [02-gki-kmi-generation-mismatch.md](docs/troubleshooting/02-gki-kmi-generation-mismatch.md) |
| **GKI 签名保护导致 WiFi / 蓝牙 / 蜂窝网络瘫痪** | [03-module-sig-protect-wireless-failure.md](docs/troubleshooting/03-module-sig-protect-wireless-failure.md) |

更多详细记录与工程架构说明请参阅 [docs/README.md](docs/README.md)。

