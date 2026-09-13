import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console

from .config import BuildConfig, KernelPreset
from .kernelsu import KernelSUManager, ksu_patch
from .patcher import SusfsPatcher
from .system_info import scan_kernel_artifacts

console = Console()


def run_bazel_clean(kernel_path: Path, dry_run: bool = False) -> bool:
    bazel_bin = kernel_path / "tools" / "bazel"
    if not bazel_bin.exists():
        console.print("[yellow]Bazel binary not found, skipping clean.[/yellow]")
        return False

    cmd = [str(bazel_bin), "clean", "--expunge"]
    if dry_run:
        console.print(f"[dim]Dry-run: Would run {' '.join(cmd)} in {kernel_path}[/dim]")
        return True

    try:
        console.print(f"[cyan]Running: {' '.join(cmd)}[/cyan]")
        ret = subprocess.run(cmd, cwd=kernel_path)
        return ret.returncode == 0
    except Exception as e:
        console.print(f"[red]Failed to run bazel clean: {e}[/red]")
        return False


def build_kernel(
    config: BuildConfig,
    kernel_preset: KernelPreset,
    target: Optional[str] = None,
    lto: Optional[str] = None,
    destdir: Optional[str] = None,
    clean: bool = False,
    extra_bazel_args: Optional[List[str]] = None,
    enable_ksu: bool = True,
    enable_susfs: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    kernel_path = kernel_preset.get_abs_path(config.workspace_root)
    if not kernel_path.exists():
        raise FileNotFoundError(f"Kernel directory not found: {kernel_path}")

    target = target or kernel_preset.default_target
    lto = lto or kernel_preset.default_lto
    destdir = destdir or kernel_preset.destdir

    # 0. 自动化特性管线：KernelSU 与 SuSFS 环境确保与更新
    if enable_ksu:
        ksu_mgr = KernelSUManager(kernel_path, dry_run=dry_run)
        if not ksu_mgr.ensure_installed_or_updated():
            console.print("[bold red]❌ KernelSU environment setup failed![/bold red]")
            return {"success": False, "duration": 0.0, "cmd": [], "artifacts": {}}

        if enable_susfs:
            susfs_patcher = SusfsPatcher(config.workspace_root)
            if not susfs_patcher.ensure_applied():
                console.print("[bold red]❌ SuSFS patch application failed![/bold red]")
                return {"success": False, "duration": 0.0, "cmd": [], "artifacts": {}}
        else:
            susfs_patcher = SusfsPatcher(config.workspace_root)
            susfs_patcher.ensure_reverted()
    else:
        # 禁用 KernelSU 时，回滚 SuSFS 并解绑驱动
        susfs_patcher = SusfsPatcher(config.workspace_root)
        susfs_patcher.ensure_reverted()
        ksu_mgr = KernelSUManager(kernel_path, dry_run=dry_run)
        ksu_mgr.disable()

    bazel_bin = kernel_path / "tools" / "bazel"
    build_sh = kernel_path / "build" / "build.sh"

    if clean:
        console.print("[bold yellow]🧹 Cleaning previous build artifacts...[/bold yellow]")
        if bazel_bin.exists():
            run_bazel_clean(kernel_path, dry_run=dry_run)

    # 1. 组装构建命令
    if bazel_bin.exists():
        cmd = [str(bazel_bin), "run"]
        if lto:
            cmd.append(f"--lto={lto}")
        if extra_bazel_args:
            cmd.extend(extra_bazel_args)
        cmd.append(target)
        cmd.extend(["--", f"--destdir={destdir}"])

        console.print(f"[bold cyan]🚀 Starting Bazel / Kleaf Build:[/bold cyan]")
        console.print(f"[white]Directory :[/white] {kernel_path}")
        console.print(f"[white]Command   :[/white] {' '.join(cmd)}\n")
    elif build_sh.exists():
        cmd = ["bash", str(build_sh)]
        console.print(f"[bold cyan]🚀 Starting Legacy build.sh:[/bold cyan] {' '.join(cmd)}")
    else:
        raise RuntimeError(f"No recognizable build system in {kernel_path}")

    # 2. Dry-run 模式直接返回，不触发实际编译
    if dry_run:
        if enable_ksu:
            ksu_mgr = KernelSUManager(kernel_path, dry_run=True)
            ksu_mgr.prepare()
        console.print(f"[bold green]Dry run completed. Command would be executed in:[/bold green] {kernel_path}")
        return {
            "success": True,
            "duration": 0.0,
            "cmd": cmd,
            "artifacts": scan_kernel_artifacts(kernel_path, destdir=destdir) if bazel_bin.exists() else {},
        }

    # 3. 实际构建执行：仅在 KernelSU 启用时包裹 JIT 热补丁与自动还原
    start_time = time.time()
    if enable_ksu:
        with ksu_patch(kernel_path):
            proc = subprocess.run(cmd, cwd=kernel_path)
    else:
        proc = subprocess.run(cmd, cwd=kernel_path)
    success = proc.returncode == 0

    duration = time.time() - start_time
    artifacts = scan_kernel_artifacts(kernel_path, destdir=destdir)

    return {
        "success": success,
        "duration": duration,
        "cmd": cmd,
        "artifacts": artifacts,
    }
