import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime


def format_bytes(size: int) -> str:
    if size <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    val = float(size)
    while val >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1
    return f"{val:.1f} {units[unit_idx]}"


def get_system_resources(workspace_root: Path) -> Dict[str, str]:
    # CPU
    cpu_count = os.cpu_count() or 1

    # RAM from /proc/meminfo
    ram_total = "Unknown"
    ram_available = "Unknown"
    meminfo_path = Path("/proc/meminfo")
    if meminfo_path.exists():
        try:
            mem_data = {}
            for line in meminfo_path.read_text(encoding="utf-8").splitlines():
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    mem_data[key] = int(val) * 1024
            if "MemTotal" in mem_data:
                ram_total = format_bytes(mem_data["MemTotal"])
            if "MemAvailable" in mem_data:
                ram_available = format_bytes(mem_data["MemAvailable"])
        except Exception:
            pass

    # Disk space
    total, used, free = shutil.disk_usage(workspace_root)

    return {
        "cpu_count": str(cpu_count),
        "ram_total": ram_total,
        "ram_available": ram_available,
        "disk_total": format_bytes(total),
        "disk_free": format_bytes(free),
    }


def scan_kernel_artifacts(kernel_path: Path, destdir: str = "out/dist") -> Dict[str, Optional[Dict[str, str]]]:
    dist_dir = kernel_path / destdir
    results = {}

    interesting_files = [
        "Image",
        "vmlinux",
        "system_dlkm.erofs.img",
        "kernel_aarch64_dot_config",
        "init_ddk.zip",
    ]

    for fname in interesting_files:
        fpath = dist_dir / fname
        if fpath.exists():
            stat = fpath.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            results[fname] = {
                "size": format_bytes(stat.st_size),
                "mtime": mtime,
                "path": str(fpath),
            }
        else:
            results[fname] = None

    return results


def list_available_kernel_trees(workspace_root: Path) -> List[Dict[str, str]]:
    trees = []
    for item in workspace_root.iterdir():
        if item.is_dir() and not item.name.startswith((".", "tools", "out")):
            has_bazel = (item / "tools" / "bazel").exists()
            has_build_sh = (item / "build" / "build.sh").exists()
            if has_bazel or has_build_sh:
                trees.append({
                    "name": item.name,
                    "type": "Kleaf/Bazel" if has_bazel else "Legacy build.sh",
                    "path": str(item),
                })
    return trees
