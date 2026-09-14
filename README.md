# Android GKI 构建与打包工程套件 (GKI Builder Suite)

本项目是一套针对 Android GKI（Generic Kernel Image）的自动化构建、补丁管理与镜像打包工具集。

工程采用分层解耦设计，将控制套件与 AOSP 源码树分离。支持 Bazel/Kleaf 自动化编译、LTO 策略控制、内核补丁集成、AnyKernel3 与 Fastboot Boot 镜像生成，以及内核级 LSP 开发环境配置。

---

## 1. 工程目录结构

```text
/home/pochita/gki/                     # 控制中心工程仓库
├── gki_builder/                       # 构建与打包核心 Python 库
├── modules/                           # 内核模块与扩展服务
│   ├── action_key/                    # 示例内核驱动模块（C/Rust）
│   └── pochita/                       # KernelSU 伴侣模块（开机网络优化与运行时服务）
├── build.sh                           # 构建入口脚本（支持命令行参数与交互终端）
├── build_config.yaml                  # 构建配置（内核版本、Kleaf 目标、打包策略）
├── pyproject.toml / uv.lock           # Python 依赖管理配置
├── patches/                           # 官方内核补丁集
│   ├── android16-6.12/                # Android 16 (6.12) 补丁
│   │   ├── 0001-kernel-configs-bypass-module-sig-protect-and-enable-network-configs.patch
│   │   └── 0002-feat-integrate-KernelSU-v3.3.0-and-SuSFS-2.3.0-in-tr.patch
│   └── tools/                         # AnyKernel3 架构适配补丁
├── docs/                              # 技术文档与故障排查复盘
│   ├── README.md                      # 文档索引
│   └── troubleshooting/               # 技术排错报告 (01, 02, 03)
├── tools/AnyKernel3/                  # 通用 GKI AnyKernel3 刷机模板与打包脚本
├── tools/kptools/                     # Boot 镜像解包与重打包工具
├── tools/boot_templates/              # 原厂 Boot 镜像模板归档（按 KMI 目录存放）
├── tools/update_lsp.py                # Clangd 与 rust-analyzer LSP 配置生成工具
├── out/                               # 编译与打包产物输出目录
│   └── release/
│       ├── boot/                      # Fastboot 结构 boot.img
│       ├── anykernel/                 # AnyKernel3 刷机 ZIP
│       └── modules/                   # 伴侣模块发布包 ZIP
│
└── android16-6.12/                    # 外部 AOSP 内核源码树（由 repo 独立管理）
    ├── common/                        # Linux 内核通用源码仓库
    └── modules -> ../modules          # 软链接挂载外部模块，供 Bazel/Kleaf 构建
```

---

## 2. 快速开始

### 2.1 环境依赖
- **操作系统**：Linux (Ubuntu 22.04 / 24.04 LTS) 或 WSL2。
- **基础工具**：`git`、`curl`、`python3`。
- **Python 环境管理（推荐 uv）**：
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Google repo 工具**：
  ```bash
  mkdir -p ~/.bin && curl https://storage.googleapis.com/git-repo-downloads/repo > ~/.bin/repo
  chmod a+x ~/.bin/repo
  export PATH="$HOME/.bin:$PATH"
  ```

### 2.2 初始化工程
```bash
git clone <repository_url> gki
cd gki
uv sync
```

### 2.3 同步 AOSP 内核源码
以 Android 16 (Linux 6.12) 为例：
```bash
mkdir -p android16-6.12 && cd android16-6.12
repo init -u https://android.googlesource.com/kernel/manifest -b android16-6.12-2025-09_r17
repo sync -c -j$(nproc)
cd ..
```

### 2.4 应用内核补丁
```bash
git -C android16-6.12/common apply patches/android16-6.12/*.patch
```

### 2.5 执行构建与打包
```bash
# 执行完整构建并自动生成刷机产物（默认采用 LTO none）
./build.sh build
```

产物生成路径：
- 内核镜像：`android16-6.12/out/dist/Image`
- 刷机包（AnyKernel3）：`out/release/anykernel/AnyKernel3-android16-6.12-*.zip`
- 刷机包（Boot 镜像）：`out/release/boot/boot_android16-6.12_*.img`（存在模板时）

---

## 3. 内核补丁与功能规范

### 3.1 `0001-kernel-configs-bypass-module-sig-protect-and-enable-network-configs.patch`
- **模块签名保护放行 (`kernel/module/`)**：
  - `main.c`：放行 `verify_exported_symbols` 中 `is_protected_symbol_export` 引起的 `-EACCES` 阻断，避免未通过官方签名校验的模块加载受阻；将 `mod->sig_ok` 显式设为 `true`。
  - `signing.c`：对非致命签名错误（`-ENODATA`、`-ENOPKG`、`-ENOKEY`）设置 `info->sig_ok = true`，使自定义内核兼容加载出厂 `system_dlkm` 专有模块（解决 WiFi、蓝牙及蜂窝驱动加载失败问题）。
- **网络与拥塞控制配置 (`arch/arm64/configs/gki_defconfig`)**：
  - `CONFIG_TCP_CONG_ADVANCED=y`
  - `CONFIG_TCP_CONG_BBR=y`（保持系统默认拥塞控制算法为 `cubic`，保障引导阶段稳定性）
  - 显式关闭 `CONFIG_TCP_CONG_BIC`、`CONFIG_TCP_CONG_WESTWOOD`、`CONFIG_TCP_CONG_HTCP`，避免生成未声明的外部模块目标
  - `CONFIG_IP_NF_TARGET_TTL=y`
  - `CONFIG_IP6_NF_TARGET_HL=y`

### 3.2 `0002-feat-integrate-KernelSU-v3.3.0-and-SuSFS-2.3.0-in-tr.patch`
- 树内集成 KernelSU v3.3.0 (`drivers/kernelsu/`)。
- 树内集成 SuSFS 2.3.0 (`fs/susfs.c`, `include/linux/susfs.h`, `include/linux/susfs_def.h`)。
- 适配 LSM、系统调用分发、文件描述符及挂载命名空间劫持点。

---

## 4. 伴侣模块与扩展服务 (`modules/pochita`)

`modules/pochita` 为配套的 KernelSU / Magisk 用户态运行时伴侣模块，负责开机完成后的内核参数调度与网络规则配置。

### 4.1 核心特性
- **开机事件监听**：在后台轮询 `getprop sys.boot_completed` 直至系统完全启动，避免在早期阶段修改网络参数引发竞态或重启。
- **TCP BBR 运行时激活**：通过 `sysctl -w net.ipv4.tcp_congestion_control=bbr` 将拥塞控制切换至 BBR，对 IPv4 与 IPv6 连接双栈生效。
- **TTL / Hop Limit 伪装规则**：根据 `config/pochita.conf` 配置，自动下发 iptables 与 ip6tables mangle 规则。
- **模块化调度架构**：自动遍历执行 `service.d/*.sh` 子脚本，支持动态扩展自定义服务。
- **Action WebUI 交互**：内置 `action.sh`，支持在 KernelSU 管理器内查看当前内核状态、拥塞算法及 SuSFS 状态。

### 4.2 打包伴侣模块
```bash
python3 modules/pochita/build.sh
```
产物输出至：`out/release/modules/pochita-v1.0.0.zip`。

---

## 5. 命令行使用说明

### 5.1 入口脚本 (`./build.sh`)
```bash
./build.sh                  # 启动交互式管理菜单
./build.sh build            # 编译内核并打包（自动匹配 Boot 模板或 AnyKernel3）
./build.sh package          # 仅对现有 Image 进行打包
./build.sh info             # 查看系统资源与当前产物状态
./build.sh clean            # 清理 Bazel 缓存
```

### 5.2 打包格式指定
```bash
# 自动检测（存在 tools/boot_templates/<kmi>/boot.img 则打包 boot，否则打包 anykernel）
./build.sh package --format auto

# 强制打包 AnyKernel3 ZIP
./build.sh package --format anykernel

# 强制打包 Fastboot Boot 镜像
./build.sh package --format boot

# 同时生成两种格式
./build.sh package --format both
```

### 5.3 CLI 原生命令 (`uv run gki`)
```bash
uv run gki build                        # 默认构建（LTO none）
uv run gki build --lto thin             # 启用 ThinLTO
uv run gki build --lto full             # 启用 Full LTO
uv run gki build --no-package           # 仅编译内核 Image，不执行打包
uv run gki build --clean                # 构建前清理 Bazel 缓存
uv run gki build --dry-run              # 仅打印底层构建指令
```

---

## 6. 开发辅助工具

### 6.1 独立模块编译
自研内核模块位于 `modules/` 目录下，通过软链接桥接至 AOSP 源码树：
```bash
cd android16-6.12
./tools/bazel build //modules/action_key:action_key
```

### 6.2 LSP 补全与语义分析环境
生成适用于 Clangd (C) 与 rust-analyzer (Rust) 的编译数据库：
```bash
python3 tools/update_lsp.py
```
该脚本执行以下操作：
1. 提取内核编译命令并生成 `compile_commands.json`（供 Clangd 使用）。
2. 构建并链接宿主端 proc-macro 动态库 `libmacros.so`。
3. 生成 `rust-project.json`（供 rust-analyzer 使用），支持 Rust 内核代码补全与符号跳转。

---

## 7. 故障排查与技术文档

详细复盘报告存放于 `docs/troubleshooting/`：

| 编号 | 文档 | 故障描述与核心方案 |
| :---: | :--- | :--- |
| **01** | [AnyKernel3 刷机模板架构适配](docs/troubleshooting/01-anykernel3-block-device-adaptation.md) | 解决旧版模板块设备路径硬编码与 Android 13+ 无 Ramdisk boot.img 解包报错问题，采用 `split_boot; flash_boot;` 模式。 |
| **02** | [GKI KMI 代际断代排错](docs/troubleshooting/02-gki-kmi-generation-mismatch.md) | 解决内核小版本与 KMI generation 错位导致厂商模块 vermagic 拒绝加载而触发看门狗重启的问题，锁定官方精准 Release Tag。 |
| **03** | [模块签名保护机制排错](docs/troubleshooting/03-module-sig-protect-wireless-failure.md) | 解决 `CONFIG_MODULE_SIG_PROTECT` 拦截非官方签名模块导致 `rfkill`、WiFi、蓝牙与蜂窝网络瘫痪的问题，放行导出符号并重置 `sig_ok`。 |

更多技术规范请参阅 [docs/README.md](docs/README.md)。
