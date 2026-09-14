# GKI KMI 代际对齐与开机异常排错

- **记录日期**：2026-09-12
- **环境信息**：OnePlus / OPPO PLZ110（Android 16，Linux 6.12 GKI）
- **涉及机制**：KMI 代际控制、`build.config.constants`、内核模块 `vermagic` 与 ABI 校验

---

## 1. 故障现象

从 AOSP 顶层主线编译新版 GKI 内核（`6.12.92-android16-6`）并刷入后，设备在开机阶段触发硬件看门狗复位，陷入循环重启。

---

## 2. 现场数据与诊断

### 2.1 检查出厂专有模块信息
```bash
$ adb shell 'su -c "modinfo /vendor/lib/modules/oplus_secure_guard_new.ko"'
filename:       /vendor/lib/modules/oplus_secure_guard_new.ko
license:        GPL
depends:        oplusboot
name:           oplus_secure_guard_new
vermagic:       6.12.38-android16-5-o-g1127b872f565-4k SMP preempt mod_unload modversions aarch64
```
模块要求运行于 `6.12.38-android16-5-*-4k` 环境。

### 2.2 检查出厂原生系统运行信息
```bash
$ adb shell 'su -c "uname -a"'
Linux localhost 6.12.38-android16-5-g844001fb8721-ab14552068-4k #1 SMP PREEMPT Fri Dec  5 02:15:49 UTC 2025 aarch64 Toybox
```
系统启动命令行参数包含：
```text
phx_rus_conf.main_on=1 phx_rus_conf.kernel_time=240 oplusboot.secure_type=3 oplusboot.mode=reboot
```

### 2.3 异常构建产物对比
新构建产物的 `out/dist/gki-info.txt`：
```text
kernel_release=6.12.92-android16-6-maybe-dirty-4k
```

---

## 3. 根因分析

1. **KMI 代际与 ABI 兼容性破坏**：
   Google GKI 规范在同一 KMI 代际内保证模块 ABI 稳定性。主线分支推进到 `android16-6` 后，内核小版本升级至 `6.12.92`，导出的符号 CRC 校验与结构体布局发生变动，与系统出厂的 `android16-5` 模块不兼容。
2. **看门狗超时机制触发**：
   系统服务在开机初期尝试挂载 `/vendor/lib/modules/oplus_secure_guard_new.ko`。Module Loader 校验 `vermagic` 不匹配而拒绝加载。看门狗保护机制因核心安全模块未就绪而触发硬复位。

---

## 4. 解决方案

根据出厂内核 Git Commit 前缀 `844001fb8721` 检索对应的 AOSP 官方 Release 标签：
- **匹配 Tag**：`android16-6.12-2025-09_r17`
- **提交哈希**：`844001fb8721c3ee305f17a51628744997f787a0`

检出并重新构建：
```bash
cd /home/pochita/gki/android16-6.12/common
git fetch --depth=1 aosp refs/tags/android16-6.12-2025-09_r17:refs/tags/android16-6.12-2025-09_r17
git checkout -b android16-5-dev refs/tags/android16-6.12-2025-09_r17

cd /home/pochita/gki
./build.sh build --lto none
```

---

## 5. 验证结果

- 生成内核版本对齐为：`6.12.38-android16-5-maybe-dirty-4k`。
- 刷入后，厂商专有模块正常加载，设备顺利启动进入系统。
