# FolkPatch / KernelPatch Toolchain (`kptools`)

此目录存放用于自动化注入 [FolkPatch](https://github.com/LyraVoid/FolkPatch) (KernelPatch / APatch 上游派生) 的核心工具链。

## 包含文件

- `kptools`: 官方预编译 Linux x86_64 补丁注入 CLI 工具（版本 `d08` / `v0.13.8`）。
- `kpimg-android`: KernelPatch Android ARM64 运行时 Payload 镜像（版本 `d08` / `v0.13.8`）。

## 原理说明

在打包 AnyKernel3 刷机包时，如果启用了 `--folkpatch` 选项：
1. `kptools` 直接读取编译生成的原生通用 GKI 内核二进制（`out/dist/Image`）。
2. 将 `kpimg-android` 内核 Payload 嵌入到 Image 中，并将用户指定的 `superkey`（超级密钥）植入。
3. 将注入后的内核重新打包为 AnyKernel3 刷机包（文件名追加 `-FolkPatch-` 标记），刷入设备后即可直接配合 FolkPatch App / APatch Manager 获取 Root 权限与 KPM 模块支持。

## 命令行手动测试

```bash
# 查看版本与支持参数
./tools/kptools/kptools --help

# 手动给 Image 注入补丁并指定 superkey
./tools/kptools/kptools -p -i <Image_path> -k tools/kptools/kpimg-android -s <your_superkey> -o Image.patched
```

## 更新工具链

如需更新至最新版本的 `kptools` 或 `kpimg-android`：
可从 [KernelPatch Releases](https://github.com/bmax121/KernelPatch/releases) 或 [FolkPatch Releases](https://github.com/LyraVoid/FolkPatch/releases) 下载对应的 `kptools-linux` 和 `kpimg-android` 替换此目录下的文件，并赋予执行权限：
```bash
chmod +x tools/kptools/kptools
```
