# GKI KMI 代际断代导致真机开机死循环 (BootLoop) 排错与对齐

- **记录日期**：2026-09-12
- **影响机型**：OnePlus / OPPO PLZ110（运行 ColorOS，Android 16，内核 Linux 6.12）
- **涉及模块**：AOSP `common` 仓库分支版本控制、`build.config.constants`、KMI 符号白名单

---

## 1. 故障表现

在同步 AOSP 最新分支代码并编译出内核（`6.12.92-android16-6`）后，通过 AnyKernel3 成功刷入真机。手机重启后：
- 无法进入系统；
- 在开机 Logo 阶段卡顿后触发硬件看门狗复位，陷入无限循环重启（BootLoop）。

---

## 2. 诊断与数据采集

通过执行 ADB 诊断命令，获取真机原生固件的关键数据：

### 2.1 提取厂商专有模块的 `modinfo`
```bash
$ adb shell 'su -c "modinfo /vendor/lib/modules/oplus_secure_guard_new.ko"'
filename:       /vendor/lib/modules/oplus_secure_guard_new.ko
license:        GPL
depends:        oplusboot
name:           oplus_secure_guard_new
vermagic:       6.12.38-android16-5-o-g1127b872f565-4k SMP preempt mod_unload modversions aarch64
```
**关键发现**：原厂模块强依赖 `6.12.38-android16-5-*-4k`。

### 2.2 提取真机原生运行环境与启动参数
```bash
$ adb shell 'su -c "uname -a"'
Linux localhost 6.12.38-android16-5-g844001fb8721-ab14552068-4k #1 SMP PREEMPT Fri Dec  5 02:15:49 UTC 2025 aarch64 Toybox
```
```text
/proc/cmdline 包含关键看门狗守护参数：
phx_rus_conf.main_on=1 phx_rus_conf.kernel_time=240 oplusboot.secure_type=3 oplusboot.mode=reboot ...
```
**关键发现**：
- 真机原生内核基于 Commit `844001fb8721`；
- Google 构建编号为 `ab14552068`；
- 启用了 Oplus Phoenix 安全看门狗保护机制。

### 2.3 对比新编译产物版本
新编译内核目录下的 `out/dist/gki-info.txt` 记录如下：
```text
kernel_release=6.12.92-android16-6-maybe-dirty-4k
```

---

## 3. 根因剖析

### 3.1 KMI 代际断代破坏 ABI 兼容性
Google GKI 规范中，**仅在同一 KMI 代际内部（如 `android16-5` 内）保证 ABI 向后兼容**。当 Google 主线代码推代至 `android16-6` 时：
- Linux 内核小版本从 `6.12.38` 升级到 `6.12.92`；
- KMI 代际变量 `KMI_GENERATION` 从 `5` 变为 `6`；
- 导出的符号 CRC（`CONFIG_MODVERSIONS`）和核心结构体布局被重写，旧模块 ABI 宣告失效。

### 3.2 厂商安全驱动加载失败触发看门狗
在手机开机阶段，`init` 进程尝试加载 `/vendor/lib/modules/oplus_secure_guard_new.ko` 和 `oplusboot.ko`。
内核 Module Loader 检测到 `vermagic`（`6.12.38-android16-5` vs `6.12.92-android16-6`）严重不符，拒绝加载该模块。
Oplus 的 Phoenix 看门狗机制（`phx_rus_conf`）检测到安全守护驱动未能按时就绪，触发 Panic / 硬件复位，导致陷入无限 BootLoop。

---

## 4. 解决方案与对齐

在 AOSP 官方仓库中，利用手机原厂内核的 Git Commit 前缀 `844001fb8721` 进行检索，成功锁定了 100% 对应的官方 Release 标签：

- **官方匹配 Tag**：`android16-6.12-2025-09_r17`
- **对应 Commit**：`844001fb8721c3ee305f17a51628744997f787a0`
- **提交信息**：`ANDROID: Update symbols to oplus symbol list.`

### 操作步骤：
```bash
cd /home/pochita/gki/android16-6.12/common

# 拉取并检出官方精准对齐 Tag
git fetch --depth=1 aosp refs/tags/android16-6.12-2025-09_r17:refs/tags/android16-6.12-2025-09_r17
git checkout -b android16-5-dev refs/tags/android16-6.12-2025-09_r17

# 重新触发构建
cd /home/pochita/gki
./build.sh build --lto none
```

---

## 5. 验证结果

- **新产物版本**：`6.12.38-android16-5-maybe-dirty-4k`（`Image` 38.2 MB）；
- **刷入真机测试**：系统成功正常开机，Wi-Fi、蓝牙、触控、指纹及 `oplus_secure_guard_new.ko` 等所有专有驱动模块全部正常加载，BootLoop 彻底消除。
