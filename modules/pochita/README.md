# Pochita Kernel Companion Module

`modules/pochita` 是配套自编译 GKI 内核的用户态伴侣模块，支持 KernelSU 与 Magisk 运行环境。该模块主要负责在系统完全启动后执行内核级网络优化参数调度与防火墙规则配置。

---

## 1. 架构与目录结构

```text
modules/pochita/
├── module.prop                  # 模块元数据定义（ID、版本、描述）
├── customize.sh                 # 刷入安装脚本（配置目录与可执行权限）
├── service.sh                   # 主服务守护脚本（开机事件监听与子服务分发）
├── action.sh                    # KernelSU Action WebUI 交互与状态检查脚本
├── build.sh                     # 模块一键打包脚本（生成 flashable ZIP）
├── config/
│   └── pochita.conf             # 核心用户配置文件
└── service.d/                   # 模块化启动任务目录
    ├── 10-tcp-bbr.sh            # TCP BBR 运行时调度子服务
    └── 20-net-ttl.sh            # 出站数据包 TTL / Hop Limit 伪装子服务
```

---

## 2. 运行机制

1. **开机就绪事件同步**：
   在 `service.sh` 中轮询等待系统属性 `sys.boot_completed=1`。确保 Android 系统网络守护进程（`netd`）及上层服务初始化完毕后再下发参数，避免开机阶段因参数竞态造成系统不稳定。
2. **配置读取**：
   载入 `config/pochita.conf` 中定义的开关与参数。
3. **子服务执行**：
   按字典序遍历执行 `service.d/*.sh`，将输出记录于 `daemon.log`。

---

## 3. 配置说明 (`config/pochita.conf`)

| 配置项 | 默认值 | 作用与说明 |
| :--- | :---: | :--- |
| `ENABLE_BBR` | `1` | 设为 `1` 时，运行时调用 `sysctl -w net.ipv4.tcp_congestion_control=bbr` 将拥塞控制算法设为 BBR；设为 `0` 时保持系统当前算法。 |
| `ENABLE_TTL` | `0` | 设为 `1` 时，启用出站流量 TTL/HL 伪装规则。 |
| `TTL_VALUE` | `64` | 指定目标 TTL 数值（`64` 对应常见移动端默认值，`128` 对应 Windows 桌面默认值）。 |
| `ENABLE_EXTRA_SERVICES` | `1` | 预留未来扩展驱动或后台任务的调度总开关。 |

---

## 4. 打包与分发

在根工程目录下执行打包：

```bash
python3 modules/pochita/build.sh
```

- 打包脚本自动读取 `module.prop` 中的版本号。
- 产物输出路径：`out/release/modules/pochita-<version>.zip`。
- 生成的 ZIP 文件可直接在 KernelSU Manager 或 Magisk Manager 中刷入。

---

## 5. 状态验证

### 5.1 通过 ADB / 终端验证
```bash
# 验证 TCP 拥塞控制算法
$ sysctl net.ipv4.tcp_congestion_control
net.ipv4.tcp_congestion_control = bbr

# 验证 Netfilter TTL 规则
$ iptables -t mangle -L POSTROUTING -n -v
```

### 5.2 通过 KernelSU 管理器验证
在 KernelSU 管理器中进入模块列表，点击 Pochita 模块的 **执行操作 / Action** 按钮，`action.sh` 将输出当前内核版本、TCP 拥塞算法当前值及 SuSFS 保护状态。
