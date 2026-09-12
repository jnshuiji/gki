import hashlib
import os
import re
import shutil
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .config import AnyKernelConfig, BuildConfig, KernelPreset
from .system_info import format_bytes


def compute_sha256(file_path: Path) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def package_anykernel(
    config: BuildConfig,
    kernel_preset: KernelPreset,
    image_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    custom_zip_name: Optional[str] = None,
    patch_devicecheck: Optional[bool] = None,
) -> Dict[str, Any]:
    start_time = time.time()
    ak_config: AnyKernelConfig = config.anykernel3

    # Locate Image
    if image_path is None:
        image_path = kernel_preset.get_image_abs_path(config.workspace_root)

    if not image_path.exists():
        raise FileNotFoundError(f"Kernel Image not found at: {image_path}. Please build the kernel first.")

    # Locate AnyKernel3 template
    template_dir = ak_config.get_template_abs_path(config.workspace_root)
    if not template_dir.exists():
        raise FileNotFoundError(f"AnyKernel3 template directory not found at: {template_dir}")

    # Prepare output dir
    if output_dir is None:
        out_dir = ak_config.get_output_abs_path(config.workspace_root)
    else:
        out_dir = output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Determine zip filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    branch = kernel_preset.path
    if custom_zip_name:
        zip_filename = custom_zip_name
        if not zip_filename.endswith(".zip"):
            zip_filename += ".zip"
    else:
        zip_filename = ak_config.zip_name_template.format(
            branch=branch,
            kernel_name=kernel_preset.name.replace(" ", "_"),
            timestamp=timestamp,
        )
    dest_zip = out_dir / zip_filename

    # Create temporary staging directory
    with tempfile.TemporaryDirectory(prefix="ak3_stage_") as tmp_stage_str:
        tmp_stage = Path(tmp_stage_str)

        # Copy AnyKernel3 template files
        for item in template_dir.iterdir():
            if item.name.startswith(".git") or item.name in ("README.md", "LICENSE") or item.name.endswith(".zip"):
                continue
            dest_item = tmp_stage / item.name
            if item.is_dir():
                shutil.copytree(item, dest_item, symlinks=True)
            else:
                shutil.copy2(item, dest_item)

        # Copy Image
        shutil.copy2(image_path, tmp_stage / "Image")

        # Patch anykernel.sh with kernel name and ensure safe GKI settings
        ak_sh = tmp_stage / "anykernel.sh"
        if ak_sh.exists():
            content = ak_sh.read_text(encoding="utf-8")
            # Update kernel.string to preset name
            content = re.sub(r"kernel\.string=.*", f"kernel.string={kernel_preset.name}", content)
            should_patch = patch_devicecheck if patch_devicecheck is not None else ak_config.auto_patch_devicecheck
            if should_patch:
                content = re.sub(r"do\.devicecheck=\d+", "do.devicecheck=0", content)
            if "BLOCK=/dev/block/platform" in content:
                content = re.sub(r"BLOCK=/dev/block/platform/[^;\n]+;", "BLOCK=boot;", content)
                content = re.sub(r"IS_SLOT_DEVICE=\d+;", "IS_SLOT_DEVICE=auto;", content)
            ak_sh.write_text(content, encoding="utf-8")

        # Create flashable zip using Python zipfile
        with zipfile.ZipFile(dest_zip, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for root, dirs, files in os.walk(tmp_stage):
                for file in files:
                    file_path = Path(root) / file
                    rel_path = file_path.relative_to(tmp_stage)
                    zinfo = zipfile.ZipInfo.from_file(file_path, arcname=str(rel_path))

                    # Preserve executable permissions
                    st = file_path.stat()
                    # Keep Unix permissions in external_attr (upper 16 bits)
                    zinfo.external_attr = (st.st_mode & 0xFFFF) << 16
                    zf.writestr(zinfo, file_path.read_bytes())

    # Create symlink AnyKernel3-latest.zip
    latest_symlink = out_dir / f"AnyKernel3-{branch}-latest.zip"
    try:
        if latest_symlink.is_symlink() or latest_symlink.exists():
            latest_symlink.unlink()
        latest_symlink.symlink_to(dest_zip.name)
    except Exception:
        pass

    duration = time.time() - start_time
    file_size = format_bytes(dest_zip.stat().st_size)
    sha256 = compute_sha256(dest_zip)

    return {
        "zip_path": str(dest_zip),
        "filename": zip_filename,
        "size": file_size,
        "sha256": sha256,
        "duration": duration,
        "latest_symlink": str(latest_symlink) if latest_symlink.exists() else None,
    }
