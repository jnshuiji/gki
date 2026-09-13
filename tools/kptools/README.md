# Boot Image Unpack & Repack Toolchain (`kptools`)

此目录存放用于自动化解包与重打包 OEM Boot 镜像（如 OnePlus / OPPO 96MB 包含完整厂商专属硬件配置的镜像）的工具。

## 包含文件

- `kptools`: 官方预编译 Linux x86_64 二进制工具，用于执行 `kptools unpack <boot.img>` 与 `kptools repack <boot.img>`。

## 原理说明

在打包 Fastboot OEM 镜像时：
1. `kptools unpack` 自动解析出厂商原厂 Boot 镜像中的内核及 32MB 专属 bootconfig/AVB 签名数据。
2. 将自编译的纯原 GKI 内核二进制（`out/dist/Image`）替换进去。
3. `kptools repack` 重封装生成可直接通过 `fastboot flash boot` 刷入的 96MB 官方结构镜像。
