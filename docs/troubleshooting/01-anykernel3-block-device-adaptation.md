# AnyKernel3 刷机模板现代 GKI 架构适配与排错

- **记录日期**：2026-09-12
- **影响范围**：所有基于 Android 13+（Boot Header v4/v3）及现代 A/B 分区的通用 GKI 刷机包
- **涉及模块**：`tools/AnyKernel3/anykernel.sh`、`gki_builder/anykernel.py`

---

## 1. 故障表现

在 TWRP、OrangeFox 或通过 KernelSU / Magisk App 刷入由 AnyKernel3 打包的内核 ZIP 时，安装流程意外终止并报错退出：

```text
ExampleKernel by osm0sis @ xda-developers
Unable to determine /dev/block/platform/omap/omap_hsmmc.0/by-name/boot partition. Aborting...
```

---

## 2. 根因剖析

### 2.1 古老芯片物理路径硬编码
AnyKernel3 官方仓库克隆后自带的 `anykernel.sh` 是以 2011 年三星 Galaxy Nexus（研发代号 tuna / maguro，搭载德州仪器 TI OMAP4460 处理器）为参考的示例脚本。其配置项写死了 OMAP 芯片专属的物理块设备路径：
```shell
BLOCK=/dev/block/platform/omap/omap_hsmmc.0/by-name/boot;
```
现代主流 SoC（高通骁龙、联发科天玑、Google Tensor、三星 Exynos 等）根本不存在该路径。`ak3-core.sh` 尝试检测该块设备是否存在时失败，抛出错误终止安装。

### 2.2 不支持现代 A/B 槽位检测
原脚本配置了 `IS_SLOT_DEVICE=0;`，完全忽略了从 Android 9/10 起普及的 A/B 及虚拟 A/B（Virtual A/B）槽位（`_a` / `_b`）机制。

### 2.3 Android 13+ Ramdisk 架构变更冲突
原脚本默认调用：
```shell
dump_boot;   # 内部执行 split_boot + unpack_ramdisk
write_boot;  # 内部执行 repack_ramdisk + flash_boot
```
在 Android 13+（Boot Header v4）架构下：
- **`boot.img` 只包含核心内核 `Image`，其 Ramdisk 大小为 0**；
- 系统的 First-stage Ramdisk 已经被 Google 完全转移至独立的 **`init_boot.img`** 分区。

如果使用 `dump_boot` 强行解包一个无 Ramdisk 的 `boot.img`，`ak3-core.sh` 会在第 230 行触发 `abort "No ramdisk found to unpack. Aborting...";`。

---

## 3. 解决方案与实施

对 `tools/AnyKernel3/anykernel.sh` 进行现代化重构，调整为面向现代 GKI 的通用标准配置：

```shell
### AnyKernel setup
properties() { '
kernel.string=Android 16 (Linux 6.12 GKI)
do.devicecheck=0               # 取消针对特定机型的限制，实现通用刷入
do.modules=0
do.systemless=1
do.cleanup=1
do.cleanuponabort=0
'; }

### AnyKernel install
BLOCK=boot;                    # 自动探测现代各平台 /dev/block/(bootdevice/)by-name/boot 路径
IS_SLOT_DEVICE=auto;           # 自动探测 A/B 槽位（_a / _b）
RAMDISK_COMPRESSION=auto;
PATCH_VBMETA_FLAG=auto;

. tools/ak3-core.sh;

# GKI 专用刷入逻辑：
# 使用 split_boot + flash_boot，直接替换 boot 分区中的内核 Image
# 免去 ramdisk 解包/重打包（完美适配 Android 13+ init_boot 架构），并自动继承 Magisk / KernelSU
split_boot;
flash_boot;
```

---

## 4. 验证结果

重新打包生成的 ZIP 刷机包在真机（OnePlus PLZ110）上测试：
- 顺利识别 `/dev/block/bootdevice/by-name/boot_a`（或 `_b`）槽位；
- 成功解开原始 boot 分区并将编译出的 `Image` 写入；
- 刷机成功，未破坏 `init_boot` 中的 Magisk/KernelSU 补丁。
