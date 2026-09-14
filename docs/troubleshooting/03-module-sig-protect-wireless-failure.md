# GKI 模块签名保护 (CONFIG_MODULE_SIG_PROTECT) 导致无线网络故障排查

- **记录日期**：2026-09-12
- **环境信息**：OnePlus / OPPO PLZ110（Android 16，Linux 6.12 GKI）
- **涉及模块**：Linux 内核模块装载机制（`kernel/module/main.c`、`kernel/module/signing.c`）、`rfkill.ko`、`bluetooth.ko`、`cfg80211.ko`、`qca_cld3_peach_v2.ko`

---

## 1. 故障现象

刷入与出厂 KMI 对齐的自编译 GKI 内核后，系统可正常启动，但无线通信功能出现异常：
- WiFi 无法打开，接口中无 `wlan0` 网络设备。
- 蓝牙开关置灰或开启后自动回弹关闭。
- 蜂窝数据连接未激活，数据接口保持 DOWN 状态。

---

## 2. 现场诊断

### 2.1 手动装载测试
通过 Root 权限尝试装载核心无线模块 `rfkill.ko`：
```bash
$ adb shell 'su -c "insmod /system_dlkm/lib/modules/rfkill.ko"'
insmod: failed to load /system_dlkm/lib/modules/rfkill.ko: Permission denied
```
系统返回 `-EACCES`。内核日志输出如下：
```text
rfkill: exports protected symbol rfkill_alloc
```
内核拒绝加载导出受保护符号 `rfkill_alloc` 的模块。

### 2.2 驱动依赖链分析
检查系统模块依赖关系（`modules.dep`）：
```text
/system_dlkm/lib/modules/bluetooth.ko
└── 依赖: rfkill.ko (由于 rfkill 加载失败，提示 ENOENT)

/vendor_dlkm/lib/modules/cfg80211.ko
└── 依赖: rfkill.ko (同上)

/vendor/lib/modules/qca_cld3_peach_v2.ko
└── 依赖: cfg80211.ko, rfkill.ko (依赖缺失，驱动初始化中断)
```
由于基础模块 `rfkill.ko` 加载受阻，导致其后续依赖驱动均未能正常加载。

---

## 3. 根因分析

1. **GKI 签名校验机制**：
   Google 官方构建在 `/system_dlkm` 中存放核心通用驱动，并使用官方私钥签名。
   出厂内核仅信任官方密钥。当自编译内核从源码构建时，本地生成临时密钥对，真机上的出厂模块使用该临时密钥校验会返回密钥不匹配（`-ENOKEY`），从而将 `mod->sig_ok` 标记为 `false`。
2. **`CONFIG_MODULE_SIG_PROTECT` 拦截逻辑**：
   内核源码中存在如下保护判断：
   ```c
   #ifdef CONFIG_MODULE_SIG_PROTECT
       if (!mod->sig_ok && is_protected_symbol_export(kernel_symbol_name(s))) {
           pr_err("%s: exports protected symbol %s\n",
                  mod->name, kernel_symbol_name(s));
           return -EACCES;
       }
   #endif
   ```
   未通过签名校验的模块一旦导出受保护符号（如 `rfkill_alloc`），将被强行拦截，返回 `-EACCES`。

---

## 4. 解决方案

在补丁 `patches/android16-6.12/0001-kernel-configs-bypass-module-sig-protect-and-enable-network-configs.patch` 中放宽相关限制：

### 4.1 放行受保护符号导出 (`kernel/module/main.c`)
```c
#ifdef CONFIG_MODULE_SIG_PROTECT
			if (!mod->sig_ok && is_protected_symbol_export(kernel_symbol_name(s))) {
				pr_warn("%s: exports protected symbol %s (allowed for custom GKI)\n",
				       mod->name, kernel_symbol_name(s));
				/* Bypass -EACCES to allow stock system_dlkm modules to load on custom GKI */
			}
#endif
```

### 4.2 统一设置模块签名有效标记 (`kernel/module/main.c`)
```c
#ifdef CONFIG_MODULE_SIG
	/* Always treat modules as sig_ok on custom GKI so stock system_dlkm and vendor modules load */
	mod->sig_ok = true;
...
#else
	mod->sig_ok = true;
#endif
```

### 4.3 允许未签名或密钥缺失模块标记 (`kernel/module/signing.c`)
在 `module_sig_check()` 中：
```c
	info->sig_ok = true;

	if (is_module_sig_enforced()) {
		pr_notice("Loading of %s is rejected\n", reason);
		return -EKEYREJECTED;
	}
```

---

## 5. 验证结果

- 重新构建并刷入内核后，`rfkill.ko`、`bluetooth.ko`、`cfg80211.ko` 及 WLAN 驱动均正常加载。
- WiFi 出现 `wlan0` 接口并正常关联热点。
- 蓝牙及蜂窝数据通道正常激活。
