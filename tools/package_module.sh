#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0
# Action Key Assistant - KernelSU Module Packaging Script

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_DIR="$PROJECT_ROOT/package/action_key"
OUT_DIR="$PROJECT_ROOT/out"
KO_SRC="$PROJECT_ROOT/android16-6.12/bazel-bin/modules/action_key/action_key/action_key.ko"
DAEMON_SRC="$PROJECT_ROOT/daemon/target/aarch64-unknown-linux-musl/release/action_key_daemon"

echo "========================================================"
echo "📦 [ActionKey-Packager] 正在打包 KernelSU 模块..."
echo "========================================================"

mkdir -p "$PACKAGE_DIR/bin"
mkdir -p "$OUT_DIR"

# 1. 检查并复制 action_key.ko
if [ -f "$KO_SRC" ]; then
    echo "✔ 复制内核驱动: $KO_SRC -> $PACKAGE_DIR/action_key.ko"
    cp "$KO_SRC" "$PACKAGE_DIR/action_key.ko"
else
    echo "❌ 错误: 未找到内核驱动 $KO_SRC，请先运行 bazel build!"
    exit 1
fi

# 2. 检查并复制 action_key_daemon
if [ -f "$DAEMON_SRC" ]; then
    echo "✔ 复制守护进程: $DAEMON_SRC -> $PACKAGE_DIR/bin/action_key_daemon"
    cp "$DAEMON_SRC" "$PACKAGE_DIR/bin/action_key_daemon"
    
    # 使用 llvm-strip 压缩体积
    STRIP_TOOL="$PROJECT_ROOT/android16-6.12/prebuilts/clang/host/linux-x86/clang-r536225/bin/llvm-strip"
    if [ -x "$STRIP_TOOL" ]; then
        "$STRIP_TOOL" --strip-all "$PACKAGE_DIR/bin/action_key_daemon" || true
        echo "✔ 已完成二进制 strip 优化"
    fi
else
    echo "❌ 错误: 未找到守护进程 $DAEMON_SRC，请先运行 cargo build --release!"
    exit 1
fi

# 3. 设置权限
chmod 755 "$PACKAGE_DIR/service.sh" "$PACKAGE_DIR/action.sh" "$PACKAGE_DIR/customize.sh" "$PACKAGE_DIR/bin/action_key_daemon"
chmod 644 "$PACKAGE_DIR/module.prop" "$PACKAGE_DIR/action_key.ko"

# 4. 使用 Python 生成保留 Unix 权限的标准 ZIP 刷机包
ZIP_NAME="action_key-v1.0.0.zip"
ZIP_OUT="$OUT_DIR/$ZIP_NAME"
rm -f "$ZIP_OUT"

echo "✔ 正在创建标准 KernelSU 刷机包: $ZIP_OUT"
python3 -c "
import os, zipfile

package_dir = '$PACKAGE_DIR'
zip_out = '$ZIP_OUT'

with zipfile.ZipFile(zip_out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(package_dir):
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, package_dir)
            zinfo = zipfile.ZipInfo.from_file(full_path, rel_path)
            mode = os.stat(full_path).st_mode
            zinfo.external_attr = (mode & 0xFFFF) << 16
            with open(full_path, 'rb') as fp:
                zf.writestr(zinfo, fp.read())
"

echo "========================================================"
echo "🎉 打包完成！"
echo "产物路径: $ZIP_OUT"
ls -lh "$ZIP_OUT"
echo "========================================================"
