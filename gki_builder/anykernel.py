import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .config import AnyKernelConfig, BootImageConfig, BuildConfig, KernelPreset
from .system_info import format_bytes


def compute_sha256(file_path: Path) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def patch_image_with_folkpatch(
    image_path: Path,
    output_path: Path,
    kptools_path: Path,
    kpimg_path: Path,
    superkey: str = "su",
) -> Dict[str, str]:
    if not kptools_path.exists():
        raise FileNotFoundError(f"kptools executable not found at: {kptools_path}")
    if not os.access(kptools_path, os.X_OK):
        kptools_path.chmod(kptools_path.stat().st_mode | 0o755)

    if not kpimg_path.exists():
        raise FileNotFoundError(f"kpimg-android payload not found at: {kpimg_path}")

    # Default to 'su' matching FolkPatch 5.0 manager zero-touch authentication
    effective_key = superkey.strip() if superkey else "su"

    # Official FolkPatch injection: -p --image <img/kernel> --skey <key> --kpimg <kpimg> --out <out>
    cmd = [
        str(kptools_path),
        "-p",
        "--image", str(image_path),
        "--skey", str(effective_key),
        "--kpimg", str(kpimg_path),
        "--out", str(output_path),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        err = res.stderr.strip() or res.stdout.strip()
        raise RuntimeError(f"kptools injection failed (exit {res.returncode}):\n{err}")

    return {
        "output": res.stdout,
        "superkey": effective_key,
    }


def repack_oem_boot_image(
    boot_template_path: Path,
    kernel_image_path: Path,
    output_boot_path: Path,
    kptools_path: Path,
) -> Dict[str, Any]:
    """Repack an OEM boot image (e.g. OnePlus/OPPO 96MB image with vendor bootconfig)
    using official kptools unpack -> swap kernel -> repack workflow.
    Works for both clean GKI kernels and FolkPatch-injected kernels.
    """
    if not boot_template_path.exists():
        raise FileNotFoundError(f"OEM Boot template not found at: {boot_template_path}")
    if not kernel_image_path.exists():
        raise FileNotFoundError(f"Kernel Image not found at: {kernel_image_path}")
    if not kptools_path.exists():
        raise FileNotFoundError(f"kptools executable not found at: {kptools_path}")

    if not os.access(kptools_path, os.X_OK):
        kptools_path.chmod(kptools_path.stat().st_mode | 0o755)

    output_boot_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="repack_boot_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        staged_boot = tmp_dir / "boot.img"
        shutil.copy2(boot_template_path, staged_boot)

        # 1. Unpack OEM boot image
        unpack_res = subprocess.run(
            [str(kptools_path), "unpack", "boot.img"],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
        )
        if unpack_res.returncode != 0:
            raise RuntimeError(f"Failed to unpack OEM boot image: {unpack_res.stderr or unpack_res.stdout}")

        # 2. Swap in the target GKI kernel
        kernel_dest = tmp_dir / "kernel"
        shutil.copy2(kernel_image_path, kernel_dest)

        # 3. Repack boot image
        repack_res = subprocess.run(
            [str(kptools_path), "repack", "boot.img"],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
        )
        if repack_res.returncode != 0:
            raise RuntimeError(f"Failed to repack OEM boot image: {repack_res.stderr or repack_res.stdout}")

        new_boot = tmp_dir / "new-boot.img"
        if not new_boot.exists():
            new_boot = staged_boot

        shutil.copy2(new_boot, output_boot_path)

    boot_size = format_bytes(output_boot_path.stat().st_size)
    sha256 = compute_sha256(output_boot_path)
    return {
        "boot_path": str(output_boot_path),
        "filename": output_boot_path.name,
        "size": boot_size,
        "sha256": sha256,
    }


def patch_boot_image_direct(
    boot_image_path: Path,
    output_boot_path: Path,
    kptools_path: Path,
    kpimg_path: Path,
    superkey: str = "su",
) -> Dict[str, Any]:
    """Patch a stock boot.img directly using official FolkPatch workflow:
    1. kptools unpack boot.img
    2. kptools -p --image kernel --skey <superkey> --kpimg <kpimg> --out kernel
    3. kptools repack boot.img
    """
    if not boot_image_path.exists():
        raise FileNotFoundError(f"Boot image not found at: {boot_image_path}")
    if not kptools_path.exists():
        raise FileNotFoundError(f"kptools executable not found at: {kptools_path}")
    if not kpimg_path.exists():
        raise FileNotFoundError(f"kpimg-android not found at: {kpimg_path}")

    if not os.access(kptools_path, os.X_OK):
        kptools_path.chmod(kptools_path.stat().st_mode | 0o755)

    effective_key = superkey.strip() if superkey else "su"
    output_boot_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="patch_boot_direct_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        staged_boot = tmp_dir / "boot.img"
        shutil.copy2(boot_image_path, staged_boot)

        # 1. Unpack boot.img
        unpack_res = subprocess.run(
            [str(kptools_path), "unpack", "boot.img"],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
        )
        if unpack_res.returncode != 0:
            raise RuntimeError(f"Failed to unpack boot.img: {unpack_res.stderr or unpack_res.stdout}")

        # 2. Patch kernel in-place
        patch_res = subprocess.run(
            [
                str(kptools_path),
                "-p",
                "--image", "kernel",
                "--skey", effective_key,
                "--kpimg", str(kpimg_path),
                "--out", "kernel",
            ],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
        )
        if patch_res.returncode != 0:
            raise RuntimeError(f"Failed to patch kernel: {patch_res.stderr or patch_res.stdout}")

        # 3. Repack boot.img
        repack_res = subprocess.run(
            [str(kptools_path), "repack", "boot.img"],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
        )
        if repack_res.returncode != 0:
            raise RuntimeError(f"Failed to repack boot.img: {repack_res.stderr or repack_res.stdout}")

        new_boot = tmp_dir / "new-boot.img"
        if not new_boot.exists():
            new_boot = staged_boot

        shutil.copy2(new_boot, output_boot_path)

    boot_size = format_bytes(output_boot_path.stat().st_size)
    sha256 = compute_sha256(output_boot_path)
    return {
        "boot_path": str(output_boot_path),
        "filename": output_boot_path.name,
        "size": boot_size,
        "sha256": sha256,
        "superkey": effective_key,
    }


def package_boot_image(
    config: BuildConfig,
    kernel_preset: KernelPreset,
    image_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    boot_template_path: Optional[Path] = None,
    folkpatch_enabled: Optional[bool] = None,
    superkey: Optional[str] = None,
    custom_boot_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Package a Fastboot-flashable OEM Boot Image by repacking the KMI's stock template.
    Works for BOTH pure GKI kernels and FolkPatch-injected kernels.
    """
    start_time = time.time()
    boot_config: BootImageConfig = config.boot_image

    # Locate Image
    if image_path is None:
        image_path = kernel_preset.get_image_abs_path(config.workspace_root)
    if not image_path.exists():
        raise FileNotFoundError(f"Kernel Image not found at: {image_path}. Please build the kernel first.")

    # Locate OEM Boot Template
    tmpl = boot_template_path or kernel_preset.get_boot_template_abs_path(config.workspace_root)
    if not tmpl or not tmpl.exists():
        raise FileNotFoundError(
            f"OEM Boot template not found for {kernel_preset.name} (checked {tmpl}). "
            f"Please place the stock boot.img at tools/boot_templates/{kernel_preset.path}/boot.img"
        )

    kptools_path = config.folkpatch.get_kptools_abs_path(config.workspace_root)
    if not kptools_path.exists():
        raise FileNotFoundError(f"kptools executable not found at: {kptools_path}")

    # Determine FolkPatch injection state
    fp_active = folkpatch_enabled if folkpatch_enabled is not None else config.folkpatch.enabled
    effective_superkey = ""
    if fp_active:
        effective_superkey = superkey if superkey is not None else config.folkpatch.superkey
        if not effective_superkey:
            effective_superkey = "su"

    # Prepare output dir (defaults to out/release/boot)
    if output_dir is None:
        out_dir = boot_config.get_output_abs_path(config.workspace_root)
    else:
        out_dir = output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    branch = kernel_preset.path
    tag_str = f"-{config.folkpatch.tag}" if fp_active else ""

    if custom_boot_name:
        boot_filename = custom_boot_name
        if not boot_filename.endswith(".img"):
            boot_filename += ".img"
    else:
        boot_filename = f"boot_{branch}{tag_str}_{timestamp}.img"

    dest_boot = out_dir / boot_filename

    with tempfile.TemporaryDirectory(prefix="boot_stage_") as tmp_stage_str:
        tmp_stage = Path(tmp_stage_str)
        target_kernel = tmp_stage / "kernel"

        if fp_active:
            kpimg_path = config.folkpatch.get_kpimg_abs_path(config.workspace_root)
            patch_image_with_folkpatch(
                image_path=image_path,
                output_path=target_kernel,
                kptools_path=kptools_path,
                kpimg_path=kpimg_path,
                superkey=effective_superkey,
            )
        else:
            # Clean pure GKI kernel
            shutil.copy2(image_path, target_kernel)

        repack_res = repack_oem_boot_image(
            boot_template_path=tmpl,
            kernel_image_path=target_kernel,
            output_boot_path=dest_boot,
            kptools_path=kptools_path,
        )

    # Symlink latest boot image
    latest_symlink = out_dir / f"boot-{branch}{tag_str}-latest.img"
    try:
        if latest_symlink.is_symlink() or latest_symlink.exists():
            latest_symlink.unlink()
        latest_symlink.symlink_to(dest_boot.name)
    except Exception:
        pass

    duration = time.time() - start_time
    file_size = repack_res["size"]
    sha256 = repack_res["sha256"]

    return {
        "boot_path": str(dest_boot),
        "filename": boot_filename,
        "size": file_size,
        "sha256": sha256,
        "duration": duration,
        "latest_symlink": str(latest_symlink) if latest_symlink.exists() else None,
        "folkpatch": fp_active,
        "superkey": effective_superkey if fp_active else None,
        "template_used": str(tmpl),
    }


def package_anykernel(
    config: BuildConfig,
    kernel_preset: KernelPreset,
    image_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    custom_zip_name: Optional[str] = None,
    patch_devicecheck: Optional[bool] = None,
    folkpatch_enabled: Optional[bool] = None,
    superkey: Optional[str] = None,
) -> Dict[str, Any]:
    """Package an AnyKernel3 flashable ZIP.
    Works for BOTH pure GKI kernels and FolkPatch-injected kernels.
    """
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

    # Determine FolkPatch injection state
    fp_active = folkpatch_enabled if folkpatch_enabled is not None else config.folkpatch.enabled
    effective_superkey = ""
    if fp_active:
        effective_superkey = superkey if superkey is not None else config.folkpatch.superkey
        if not effective_superkey:
            effective_superkey = "su"

    # Prepare output dir (defaults to out/release/anykernel)
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
        tag_str = f"-{config.folkpatch.tag}" if fp_active else ""
        if "{tag}" in ak_config.zip_name_template:
            zip_filename = ak_config.zip_name_template.format(
                branch=branch,
                kernel_name=kernel_preset.name.replace(" ", "_"),
                timestamp=timestamp,
                tag=tag_str,
            )
        else:
            zip_filename = ak_config.zip_name_template.format(
                branch=branch,
                kernel_name=kernel_preset.name.replace(" ", "_"),
                timestamp=timestamp,
            )
            if fp_active:
                tag_name = config.folkpatch.tag
                if tag_name not in zip_filename:
                    if f"-{timestamp}.zip" in zip_filename:
                        zip_filename = zip_filename.replace(f"-{timestamp}.zip", f"-{tag_name}-{timestamp}.zip")
                    else:
                        zip_filename = zip_filename.replace(".zip", f"-{tag_name}.zip")

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

        # Copy or Patch Image
        stage_image = tmp_stage / "Image"
        kptools_path = config.folkpatch.get_kptools_abs_path(config.workspace_root)
        kpimg_path = config.folkpatch.get_kpimg_abs_path(config.workspace_root)

        if fp_active:
            patch_image_with_folkpatch(
                image_path=image_path,
                output_path=stage_image,
                kptools_path=kptools_path,
                kpimg_path=kpimg_path,
                superkey=effective_superkey,
            )
        else:
            shutil.copy2(image_path, stage_image)

        # Patch anykernel.sh with kernel name and ensure safe GKI settings
        ak_sh = tmp_stage / "anykernel.sh"
        if ak_sh.exists():
            content = ak_sh.read_text(encoding="utf-8")
            banner = kernel_preset.kernel_string or kernel_preset.name
            if fp_active:
                banner = f"{banner} [FolkPatch]"
            content = re.sub(r"kernel\.string=.*", f"kernel.string={banner}", content)
            should_patch = patch_devicecheck if patch_devicecheck is not None else ak_config.auto_patch_devicecheck
            if should_patch:
                content = re.sub(r"do\.devicecheck=\d+", "do.devicecheck=0", content)
            if "BLOCK=/dev/block/platform" in content:
                content = re.sub(r"BLOCK=/dev/block/platform/[^;\n]+;", "BLOCK=boot;", content)
                content = re.sub(r"IS_SLOT_DEVICE=\d+;", "IS_SLOT_DEVICE=auto;", content)
            ak_sh.write_text(content, encoding="utf-8")

        # Create flashable AnyKernel3 zip
        with zipfile.ZipFile(dest_zip, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for root, dirs, files in os.walk(tmp_stage):
                for file in files:
                    file_path = Path(root) / file
                    rel_path = file_path.relative_to(tmp_stage)
                    zinfo = zipfile.ZipInfo.from_file(file_path, arcname=str(rel_path))

                    # Preserve executable permissions
                    st = file_path.stat()
                    zinfo.external_attr = (st.st_mode & 0xFFFF) << 16
                    zf.writestr(zinfo, file_path.read_bytes())

    # Create symlink AnyKernel3-latest.zip
    tag_suffix = f"-{config.folkpatch.tag}" if fp_active else ""
    latest_symlink = out_dir / f"AnyKernel3-{branch}{tag_suffix}-latest.zip"
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
        "folkpatch": fp_active,
        "superkey": effective_superkey if fp_active else None,
    }


def package_kernel_artifacts(
    config: BuildConfig,
    kernel_preset: KernelPreset,
    package_format: str = "auto",  # auto, boot, anykernel, both
    image_path: Optional[Path] = None,
    boot_template_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    folkpatch_enabled: Optional[bool] = None,
    superkey: Optional[str] = None,
    custom_name: Optional[str] = None,
    patch_devicecheck: Optional[bool] = None,
) -> Dict[str, Any]:
    """Unified packaging dispatcher following the priority rule:
    - If OEM Boot template exists for the current KMI preset, default to packaging Fastboot Boot image only.
    - If no OEM Boot template exists, fallback to packaging AnyKernel3 zip only.
    - If caller requests 'both' or a specific format, honor that request.
    """
    tmpl = boot_template_path or kernel_preset.get_boot_template_abs_path(config.workspace_root)
    has_template = tmpl is not None and tmpl.exists()

    resolved_format = package_format.lower()
    auto_selected = False
    if resolved_format == "auto":
        auto_selected = True
        resolved_format = "boot" if has_template else "anykernel"

    results: Dict[str, Any] = {
        "requested_format": package_format,
        "resolved_format": resolved_format,
        "auto_selected": auto_selected,
        "preset_name": kernel_preset.name,
        "kmi": kernel_preset.path,
        "has_boot_template": has_template,
        "boot_template": str(tmpl) if tmpl else None,
        "boot_image": None,
        "anykernel": None,
        "folkpatch": folkpatch_enabled if folkpatch_enabled is not None else config.folkpatch.enabled,
        "superkey": superkey,
    }

    if resolved_format in ("boot", "both"):
        results["boot_image"] = package_boot_image(
            config=config,
            kernel_preset=kernel_preset,
            image_path=image_path,
            output_dir=output_dir,
            boot_template_path=tmpl,
            folkpatch_enabled=folkpatch_enabled,
            superkey=superkey,
            custom_boot_name=custom_name if resolved_format == "boot" else None,
        )

    if resolved_format in ("anykernel", "both"):
        results["anykernel"] = package_anykernel(
            config=config,
            kernel_preset=kernel_preset,
            image_path=image_path,
            output_dir=output_dir,
            custom_zip_name=custom_name if resolved_format == "anykernel" else None,
            patch_devicecheck=patch_devicecheck,
            folkpatch_enabled=folkpatch_enabled,
            superkey=superkey,
        )

    return results
