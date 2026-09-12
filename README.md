# Android GKI 自动化构建与工程套件 (GKI Builder Suite)

本项目是一套专为 **Android GKI（Generic Kernel Image，通用内核镜像）** 打造的现代化、工程化自动化构建与 AnyKernel3 刷机包打包套件。

项目采用 **「轻量控制中心 + AOSP 底座解耦」** 的分层架构设计，基于 `uv` 虚拟环境与 Python 现代化 CLI 构建。支持一键快速编译、LTO 策略切换、编译耗时统计、系统资源自检、个性化刷机包自动打包以及基于 Patch 驱动的技术补丁管理。

---

## 🏗️ 整体工程架构 (Architecture)

当前工程将 **轻量级工程控制中心** 与 **几十 GB 的 AOSP 巨型构建树** 完全解耦：

```text
/home/pochita/gki/                     <-- 【本工程】轻量级工程控制中心（约 1 MB，Git 统一管理）
├── gki_builder/                       # 核心自动化构建与 AnyKernel3 动态打包引擎 (Python)
├── build.sh                           # 根目录便捷交互与构建启动脚本
├── build_config.yaml                  # 核心配置文件（多内核预设、个性化命名、打包选项）
├── pyproject.toml / uv.lock           # uv Python 依赖锁文件
├── patches/                           # 核心技术避坑与功能修复 Patch 库
│   ├── android16-6.12/                # Android 16 (6.12) 补丁（如签名放宽、WiFi修复等）
│   └── tools/                         # AnyKernel3 现代 GKI 架构适配补丁
├── docs/                              # 专业技术排错复盘与工程文档
│   ├── README.md                      # 技术文档索引中心
│   └── troubleshooting/               # 深度技术排错复盘报告 (01, 02, 03)
├── tools/AnyKernel3/                  # 【内置开箱即用】通用现代 GKI 刷机模板与打包工具
├── tools/kptools/                     # 【内核修补工具链】kptools 补丁工具与 kpimg 运行时
├── tools/boot_templates/              # 【按 KMI 归档的原厂 Boot 模板】(.gitignore 忽略)
│   └── android16-6.12/boot.img        # 对应 KMI 的完整 OEM 96MB 结构镜像
├── out/                               # 编译与打包输出目录（.gitignore 忽略）
│   └── release/                       # 最终发布产物（分流管理）
│       ├── boot/                      # Fastboot 官方结构 boot.img (纯原 / FolkPatch)
│       └── anykernel/                 # AnyKernel3 刷机 ZIP (纯原 / FolkPatch)
│
└── android16-6.12/                    <-- 【外部 AOSP 底座】由 repo 独立管理（数十 GB，.gitignore 忽略）
    ├── .repo/                         # Google 官方源码清单
    └── common/                        # Linux 内核通用树（独立 Git 仓库）
```

---

## 🚀 新开发者从零上手指南 (Quickstart from Scratch)

### 1. 环境前置准备
- **操作系统**：Linux（推荐 Ubuntu 22.04/24.04 LTS）或 Windows WSL2。
- **必备基础工具**：`git`、`curl`、`python3`。
- **推荐安装 uv**（现代极速 Python 包管理器）：
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **安装 Google repo 工具**：
  ```bash
  mkdir -p ~/.bin && curl https://storage.googleapis.com/git-repo-downloads/repo > ~/.bin/repo
  chmod a+x ~/.bin/repo
  export PATH="$HOME/.bin:$PATH"
  ```

---

### 2. 克隆本工程与初始化环境

本工程已内置开箱即用的 AnyKernel3 打包工具，**标准克隆即可直接使用（无需子模块递归）**：

```bash
# 克隆仓库
git clone <你的gki仓库URL> gki
cd gki

# 一键初始化 Python 虚拟环境与依赖
uv sync
```

---

### 3. 按需拉取目标 AOSP 内核源码 (ACK)

根据你要编译的目标内核版本，在根目录下新建对应目录，使用 `repo` 拉取 Google ACK 官方代码：

#### 场景 A：开发 Android 16 (Linux 6.12 GKI)
```bash
# 1. 创建源码目录
mkdir -p android16-6.12 && cd android16-6.12

# 2. 初始化 repo（以 Android 16 稳定 Tag 为例）
repo init -u https://android.googlesource.com/kernel/manifest -b android16-6.12-2025-09_r17

# 3. 多线程同步源码（体积约 30~50GB，耗时视网速而定）
repo sync -c -j$(nproc)
cd ..
```

#### 场景 B：开发 Android 12 (Linux 5.10 GKI)
```bash
mkdir -p android12-5.10 && cd android12-5.10
repo init -u https://android.googlesource.com/kernel/manifest -b common-android12-5.10
repo sync -c -j$(nproc)
cd ..
```

---

### 4. 应用开箱即用补丁 (Apply Patches)

本工程将验证通过的驱动修复与安全放宽补丁集中存放在 `patches/` 目录下。编译前建议打入对应补丁：

```bash
# 为 Android 16 内核打入 WiFi/蓝牙修复补丁（绕过签名保护）
git -C android16-6.12/common apply patches/android16-6.12/*.patch
```

---

### 5. 一键构建与生成刷机包

现在，直接使用便捷脚本启动编译：

```bash
# 启动交互式引导菜单（小白推荐）
./build.sh

# 或一键极速开发构建（无 LTO，耗时最短）
./build.sh build --lto none
```

构建完成后：
- **内核镜像** 位于：`android16-6.12/out/dist/Image`
- **可刷入的 AnyKernel3 ZIP** 位于：`out/release/AnyKernel3-android16-6.12-latest.zip`

---

## 🎨 个性化定制指南 (Customization Guide)

在 `build_config.yaml` 中，您可以极其轻松地为自己的内核打造个性化品牌：

```yaml
default_kernel: "android16-6.12"

kernels:
  android16-6.12:
    name: "Android 16 (Linux 6.12 GKI)"
    # 【个性化刷机横幅】在 Recovery / KernelSU 刷入时第一行显示的名称
    # 留空时自动回退使用上面的 name
    kernel_string: "Pochita Kernel for Android 16 (Linux 6.12 GKI)"
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
  # 刷机包命名模板，支持 {branch}、{kernel_name}、{timestamp} 占位符
  zip_name_template: "AnyKernel3-{branch}-{timestamp}.zip"
  # 自动将 do.devicecheck 设为 0，启用通用 GKI 适配
  auto_patch_devicecheck: true

# FolkPatch (KernelPatch / APatch 现代化派生) 动态注入选项
folkpatch:
  enabled: false                       # 是否默认启用（建议保持 false，按需通过参数启用）
  kptools_path: "tools/kptools/kptools"
  kpimg_path: "tools/kptools/kpimg-android"
  superkey: ""                         # 预设超级密钥（留空时在 CLI 动态交互输入）
  tag: "FolkPatch"                     # 启用时刷机包文件名追加标记
```

---

## 🦊 FolkPatch (KernelPatch) 动态注入支持

[FolkPatch](https://github.com/LyraVoid/FolkPatch) 是基于 KernelPatch / APatch 的现代化分支，提供 APD Lua 插件生态与高级 KPM 模块支持。

本工程采用 **「可选开关（Path B）」** 架构：
- 默认构建与打包均生成**纯净原生 GKI 内核**；
- 当指定 `--folkpatch` 或在菜单选择注入时，自动调用 `kptools` 将内核补丁与 SuperKey 嵌入 Image，并打包为独立的 `*-FolkPatch-*.zip`。

> [!CAUTION]
> **切勿双 Root 并存**：若手机已通过 KernelSU 获取 Root 权限，请勿同时刷入包含 FolkPatch 的内核，否则会导致系统冲突甚至无法开机。

---

## ⚡ 常用命令速查 (CLI Shortcuts)

### 1. 便捷启动脚本 (`./build.sh`)
```bash
./build.sh              # 启动 Rich 彩色交互式终端菜单（支持一键构建、打包、打补丁）
./build.sh build        # 编译内核并根据 KMI 模板智能打包（存在模板打包 boot，否则打包 zip）
./build.sh package      # 仅打包现有 Image（纯原 GKI，跟随 KMI 智能选择 boot 或 anykernel）
./build.sh info         # 查看 CPU、RAM、磁盘空间及当前编译产物状态
./build.sh clean        # 清理 Bazel 构建缓存
```

### 2. 智能打包与格式指定 (`./build.sh package`)
```bash
# 纯原 GKI 打包（默认 auto：检测到 tools/boot_templates/<kmi>/boot.img 时打包 boot，否则打包 anykernel）
./build.sh package

# 强制打包 AnyKernel3 ZIP（输出到 out/release/anykernel/）
./build.sh package --format anykernel

# 强制打包 Fastboot Boot 镜像（输出到 out/release/boot/）
./build.sh package --format boot

# 同时打包 Fastboot 镜像与 AnyKernel3 刷机包
./build.sh package --format both
```

### 3. FolkPatch 注入命令
```bash
# 打包时注入 FolkPatch（默认使用 "su" 零交互免密鉴权，输出对应 boot 或 zip）
./build.sh package --folkpatch

# 编译并直接打包 FolkPatch 镜像
./build.sh build --lto none --folkpatch

# 单独修补提取出的 OEM 原厂 Boot 镜像（官方 3 步修补流）
./build.sh patch-boot [path/to/boot.img]
```

### 4. 高级参数构建 (`uv run gki build`)
```bash
uv run gki build --lto none         # 极速开发模式（禁用跨模块优化，编译最快）
uv run gki build --lto thin         # 生产/性能测试模式（开启 ThinLTO）
uv run gki build --clean            # 先清理 Bazel 缓存再重新完整构建
uv run gki build --no-package       # 仅编译内核，不执行任何打包
uv run gki build --dry-run          # 仅预览底层构建命令，不实际执行
```


---

## 🔄 日常协同与 Git 工作流规范

由于 AOSP 源码树由 Google `repo` 管理，日常开发推荐 **「Patch 驱动」** 工作流：

1. **修改内核代码**：在 `android16-6.12/common` 内进行驱动调试与代码编写；
2. **提交与验证**：在 `android16-6.12/common` 仓库下执行 `git commit`；
3. **导出补丁**：
   ```bash
   git -C android16-6.12/common format-patch -1 HEAD -o patches/android16-6.12/
   ```
4. **提交根工程**：在根目录下将新增的 patch、文档或构建脚本提交至个人 Git 仓库，实现超轻量化版本追踪。

---

## 📚 关键踩坑复盘与技术文档库

在构建与真机适配过程中，我们针对关键疑难问题进行了深度复盘与分析，欢迎查阅专门的技术日志：

| 故障主题 | 涉及平台 / 模块 | 影响等级 | 详细报告链接 |
| :--- | :--- | :---: | :--- |
| **AnyKernel3 刷机模板架构未适配报错** | AnyKernel3 / Boot Header v4 / A/B 分区 | 🔴 高 | [01-anykernel3-block-device-adaptation.md](docs/troubleshooting/01-anykernel3-block-device-adaptation.md) |
| **GKI KMI 跨代断代导致真机死循环 (BootLoop)** | GKI 2.0 / KMI 5 vs 6 / ColorOS 厂商模块 | 🔴 高 | [02-gki-kmi-generation-mismatch.md](docs/troubleshooting/02-gki-kmi-generation-mismatch.md) |
| **GKI 签名保护机制导致 WiFi / 蓝牙 / 蜂窝网络瘫痪** | GKI 签名校验 / `rfkill` / 高通 WLAN 驱动 | 🔴 高 | [03-module-sig-protect-wireless-failure.md](docs/troubleshooting/03-module-sig-protect-wireless-failure.md) |

更多详细记录请参阅 [docs/README.md](docs/README.md)。
