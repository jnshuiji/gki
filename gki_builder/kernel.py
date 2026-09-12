import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console

from .config import BuildConfig, KernelPreset
from .system_info import scan_kernel_artifacts

console = Console()


def run_bazel_clean(kernel_path: Path, dry_run: bool = False) -> bool:
    bazel_bin = kernel_path / "tools" / "bazel"
    if not bazel_bin.exists():
        console.print(f"[red]Error: tools/bazel not found at {bazel_bin}[/red]")
        return False

    cmd = [str(bazel_bin), "clean"]
    console.print(f"[yellow]Executing: {' '.join(cmd)} (in {kernel_path})[/yellow]")

    if dry_run:
        console.print("[dim](Dry-run mode, skipped execution)[/dim]")
        return True

    try:
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
    dry_run: bool = False,
) -> Dict[str, Any]:
    kernel_path = kernel_preset.get_abs_path(config.workspace_root)
    if not kernel_path.exists():
        raise FileNotFoundError(f"Kernel directory not found: {kernel_path}")

    target = target or kernel_preset.default_target
    lto = lto or kernel_preset.default_lto
    destdir = destdir or kernel_preset.destdir

    # Check build system
    bazel_bin = kernel_path / "tools" / "bazel"
    build_sh = kernel_path / "build" / "build.sh"

    if clean:
        console.print("[bold yellow]🧹 Cleaning previous build artifacts...[/bold yellow]")
        if bazel_bin.exists():
            run_bazel_clean(kernel_path, dry_run=dry_run)

    start_time = time.time()

    if bazel_bin.exists():
        # Kleaf / Bazel build
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

        if dry_run:
            console.print("[bold green]Dry run completed. Command would be executed in:[/bold green] " + str(kernel_path))
            return {
                "success": True,
                "duration": 0.0,
                "cmd": cmd,
                "artifacts": scan_kernel_artifacts(kernel_path, destdir=destdir),
            }

        proc = subprocess.run(cmd, cwd=kernel_path)
        success = proc.returncode == 0
    elif build_sh.exists():
        # Legacy build.sh
        cmd = ["bash", str(build_sh)]
        console.print(f"[bold cyan]🚀 Starting Legacy build.sh:[/bold cyan] {' '.join(cmd)}")
        if dry_run:
            return {
                "success": True,
                "duration": 0.0,
                "cmd": cmd,
                "artifacts": {},
            }
        proc = subprocess.run(cmd, cwd=kernel_path)
        success = proc.returncode == 0
    else:
        raise RuntimeError(f"No recognizable build system (tools/bazel or build/build.sh) found in {kernel_path}")

    duration = time.time() - start_time
    artifacts = scan_kernel_artifacts(kernel_path, destdir=destdir)

    return {
        "success": success,
        "duration": duration,
        "cmd": cmd,
        "artifacts": artifacts,
    }
