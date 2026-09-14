# AnyKernel3 刷机模板架构适配与排错

- **记录日期**：2026-09-12
- **适用架构**：Android 13+（Boot Header v4/v3）、A/B 分区结构
- **涉及配置**：`tools/AnyKernel3/anykernel.sh`、`gki_builder/anykernel.py`

---

## 1. 故障现象

在 Recovery（TWRP / OrangeFox）或通过 KernelSU / Magisk 管理器刷入 AnyKernel3 打包的内核 ZIP 时，安装脚本报错中止：

```text
Unable to determine /dev/block/platform/omap/omap_hsmmc.0/by-name/boot partition. Aborting...
```

---

## 2. 根因分析

1. **块设备物理路径硬编码**：
   原始模板中的 `BLOCK` 变量指定为特定的物理设备路径（如 `/dev/block/platform/omap/...`）。现代 SoC（高通、联发科等）采用不同的设备树节点与动态符号链接，导致 `ak3-core.sh` 无法定位目标 boot 分区。
2. **槽位检测机制缺失**：
   原配置硬编码 `IS_SLOT_DEVICE=0;`，未适配 Android A/B 分区系统（`_a` / `_b`）。
3. **Ramdisk 架构变更**：
   原脚本使用 `dump_boot` 与 `write_boot`，内部默认执行解包与重打包 Ramdisk。在 Android 13+（Boot Header v4）规范中，通用内核镜像所在的 `boot.img` 不包含 Ramdisk（Ramdisk 迁移至独立的 `init_boot.img` 分区）。执行 `dump_boot` 解包空 Ramdisk 时触发 `No ramdisk found to unpack. Aborting...` 异常。

---

## 3. 解决方案

修改 `tools/AnyKernel3/anykernel.sh`，采用通用探测与直接替换模式：

```shell
### AnyKernel setup
properties() { '
kernel.string=Android 16 (Linux 6.12 GKI)
do.devicecheck=0
do.modules=0
do.systemless=1
do.cleanup=1
do.cleanuponabort=0
'; }

### AnyKernel install
BLOCK=boot;
IS_SLOT_DEVICE=auto;
RAMDISK_COMPRESSION=auto;
PATCH_VBMETA_FLAG=auto;

. tools/ak3-core.sh;

# 直接解构并替换 boot 分区内核 Image，不解包 Ramdisk
split_boot;
flash_boot;
```

---

## 4. 验证结果

- 脚本自动定位 `/dev/block/bootdevice/by-name/boot_a`（或 `_b`）目标设备。
- 替换过程仅写入内核 `Image`，保留现有 `init_boot` 中的 Root 授权组件。
- 刷机流程正常结束，重启后内核版本生效。
