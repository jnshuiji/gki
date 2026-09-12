# GKI 模块签名保护 (CONFIG_MODULE_SIG_PROTECT) 导致无线网络与蓝牙瘫痪排错复盘

- **记录日期**：2026-09-12
- **影响机型**：OnePlus / OPPO PLZ110（OnePlus Ace 5，ColorOS 运行 Android 16，内核 Linux 6.12 GKI）
- **涉及模块**：Linux 内核模块加载机制（`kernel/module/main.c`、`kernel/module/signing.c`）、`rfkill.ko`、`bluetooth.ko`、`cfg80211.ko`、`qca_cld3_peach_v2.ko`（高通 WiFi 驱动）

---

## 1. 故障表现

在成功刷入与原厂 KMI 精确对齐的自编译 GKI 内核（`6.12.38-android16-5-*-4k`）后，系统能够正常开机进入桌面，KernelSU 权限正常。但用户反馈出现严重的无线外设与网络故障：
- **WiFi 无法开启**：点击设置中的 WiFi 开关无反应，无法搜索到任何无线热点，系统接口中无 `wlan0` 网卡设备。
- **蓝牙（Bluetooth）无法开启**：蓝牙开关置灰或开启后自动关闭，无法与外设配对。
- **移动网络（蜂窝数据）失效**：SIM 卡识别正常但无法激活蜂窝数据通道，数据图标不显示，移动数据连接不可用。

---

## 2. 现场诊断与排查过程

### 2.1 依赖追踪与加载测试
首先通过 ADB 连接真机，使用 Root 权限尝试手动加载无线射频核心模块 `rfkill.ko`：

```bash
$ adb shell 'su -c "insmod /system_dlkm/lib/modules/rfkill.ko"'
insmod: failed to load /system_dlkm/lib/modules/rfkill.ko: Permission denied
```
系统直接抛出 `-EACCES`（权限拒绝）。紧接着查看内核 `dmesg` 输出：

```text
[  482.203580] rfkill: exports protected symbol rfkill_alloc
```
内核明确指出：`rfkill` 导出了受保护符号 `rfkill_alloc`，因而拒绝其挂载。

### 2.2 驱动级联依赖链（Cascade Failure）分析
通过检查系统模块依赖映射（`modules.dep`）与符号依赖：

```text
/system_dlkm/lib/modules/bluetooth.ko
└── 依赖: rfkill.ko (由于 rfkill 失败，报错 ENOENT: No such file or directory)

/vendor_dlkm/lib/modules/cfg80211.ko
└── 依赖: rfkill.ko (同样因 rfkill 无法加载而中断)

/vendor/lib/modules/qca_cld3_peach_v2.ko (高通骁龙 8 Gen 3 WLAN 驱动)
└── 依赖: cfg80211.ko, rfkill.ko, cnss2.ko 等 (核心依赖全灭，驱动根本无法初始化)

移动蜂窝网络（RIL & rmnet）
└── 状态: Android Telephony 检测到 rfkill 射频状态异常，rmnet_data0~2 数据网卡保持 state DOWN。
```

从 `rfkill.ko` 一个基础模块的沦陷，直接导致了蓝牙、WiFi 驱动到基带蜂窝数据的全面雪崩。

---

## 3. 根因剖析

### 3.1 官方 GKI 安全模型与 `CONFIG_MODULE_SIG_PROTECT`
Google 在 Android GKI 架构中引入了 `CONFIG_MODULE_SIG_PROTECT` 安全机制：
- Google 官方发行的 GKI 产物将核心公共模块放置在 `/system_dlkm` 分区（例如 `rfkill.ko`、`bluetooth.ko` 等），并在构建时使用 Google 官方私钥对这些模块进行 PKCS#7 签名。
- 手机出厂内核的内置受信任公钥环（Keyring）中包含 Google 官方的公钥。
- 为了防止第三方/厂商编写的 Vendor 模块（如 `/vendor_dlkm`）恶意覆盖或伪造 Google 保护的核心系统符号，GKI 内核会检查：
  ```c
  #ifdef CONFIG_MODULE_SIG_PROTECT
      if (!mod->sig_ok && is_protected_symbol_export(kernel_symbol_name(s))) {
          pr_err("%s: exports protected symbol %s\n",
                 mod->name, kernel_symbol_name(s));
          return -EACCES;
      }
  #endif
  ```
  **如果模块签名不合格（`!mod->sig_ok`），且试图导出列在 `protected_symbol_exports` 保护名单中的符号，内核将直接返回 `-EACCES` 强行拒绝。**

### 3.2 自编译内核与出厂签名矛盾
当开发者自行从源码编译 GKI 内核时：
1. 编译系统会在本地动态生成临时的自签名证书对（`certs/signing_key.pem`）；
2. 手机真机系统的 `/system_dlkm` 中存放的是官方 Google 私钥签署的模块；
3. 开机时，自编译内核使用本地公钥校验 `/system_dlkm/rfkill.ko` 时触发密钥缺失错误（`-ENOKEY`），因此 `mod->sig_ok` 被置为 `false`；
4. 此时 `CONFIG_MODULE_SIG_PROTECT` 触发误杀：`rfkill.ko` 导出的 `rfkill_alloc` 属于受保护符号，直接被 `-EACCES` 拦截，引发全套无线网络功能瘫痪！

---

## 4. 解决方案与代码实现

对于自定义编译的 GKI 内核，必须解除此项过于严苛的限制，使自编译内核信任或放行系统已有的原厂模块：

### 4.1 放宽保护符号导出拦截 (`kernel/module/main.c`)
在 `verify_exported_symbols()` 函数中，将直接阻断的 `return -EACCES;` 改为警告日志，避免加载失败：

```c
#ifdef CONFIG_MODULE_SIG_PROTECT
			if (!mod->sig_ok && is_protected_symbol_export(kernel_symbol_name(s))) {
				pr_warn("%s: exports protected symbol %s (allowed for custom GKI)\n",
				       mod->name, kernel_symbol_name(s));
				/* Bypass -EACCES to allow stock system_dlkm modules to load on custom GKI */
			}
#endif
```

### 4.2 默认信任模块签名标志 (`kernel/module/main.c`)
在模块装载点，无条件赋权 `mod->sig_ok = true;`，避免未签名标记导致的符号导入限制与不必要的内核污染（Taint）：

```c
#ifdef CONFIG_MODULE_SIG
	/* Always treat modules as sig_ok on custom GKI so stock system_dlkm and vendor modules load */
	mod->sig_ok = true;
...
#else
	mod->sig_ok = true;
#endif
```

### 4.3 放宽缺失密钥校验 (`kernel/module/signing.c`)
在 `module_sig_check()` 中，对于因官方公钥缺失（`-ENOKEY`）或无签名（`-ENODATA`）的非致命错误，明确将 `info->sig_ok` 标记为 `true`：

```c
	switch (err) {
	case -ENODATA:
		reason = "unsigned module";
		info->sig_ok = true;
		break;
	case -ENOPKG:
		reason = "module with unsupported crypto";
		info->sig_ok = true;
		break;
	case -ENOKEY:
		reason = "module with unavailable key";
		info->sig_ok = true;
		break;
```

---

## 5. 验证与结论

1. **编译增量生效**：修改仅涉及两个 C 文件，增量编译极速完成并成功重新打包 AnyKernel3 刷机包。
2. **驱动链式复苏**：刷入新内核后，`rfkill.ko` 顺利加载，`bluetooth.ko`、`cfg80211.ko` 以及 `qca_cld3_peach_v2.ko` 依赖链彻底打通。
3. **无线网络全面复活**：
   - WiFi 出现 `wlan0` 接口并可正常扫描、连接无线热点；
   - 蓝牙正常开启并可搜索连接蓝牙设备；
   - 蜂窝移动网络数据通道（`rmnet`）正常拉起，4G/5G 数据图标与网络恢复正常。
