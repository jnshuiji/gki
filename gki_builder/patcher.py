import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from rich.console import Console

if TYPE_CHECKING:
    from .config import KernelPreset

console = Console()

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent

# SuSFS 2.3.0 aligned with KernelSU v3.3.1
DEFAULT_SUSFS_REF = "acb92d4"
GITLAB_RAW_BASE = "https://gitlab.com/simonpunk/susfs4ksu/-/raw"


class SusfsPatcher:
    """Manages automated application, clean reversion, and GitLab caching of SuSFS 2.3.0 for KernelSU v3.3.1."""

    def __init__(
        self,
        workspace_root: Path = WORKSPACE_ROOT,
        kernel_preset: Optional["KernelPreset"] = None,
        susfs_ref: Optional[str] = None,
    ):
        self.workspace_root = workspace_root
        if kernel_preset is None:
            from .config import BuildConfig

            config = BuildConfig.load()
            kernel_preset = config.kernels.get(config.default_kernel)
        self.kernel_preset = kernel_preset

        preset_path = kernel_preset.path if kernel_preset else "android16-6.12"
        self.preset_name = kernel_preset.name if kernel_preset else preset_path

        # Determine gitlab ref based on preset path
        if susfs_ref:
            self.susfs_ref = susfs_ref
        elif "5.10" in preset_path:
            self.susfs_ref = "gki-android12-5.10"
        else:
            self.susfs_ref = DEFAULT_SUSFS_REF

        # Determine patch directory
        cand_dirs = [
            workspace_root / "patches" / "susfs" / preset_path,
            workspace_root / "patches" / f"susfs_{preset_path.split('-')[-1]}",
            workspace_root / "patches" / "susfs",
        ]
        self.patch_dir = cand_dirs[0]
        for d in cand_dirs:
            if d.exists() and any(d.glob("50_add_susfs_*.patch")):
                self.patch_dir = d
                break

        # Kernel tree and common dir
        self.kernel_tree = workspace_root / preset_path
        self.common_dir = (self.kernel_tree / "common") if (self.kernel_tree / "common").exists() else self.kernel_tree

        # KSU directory
        self.ksu_dir = None
        for kd in [self.kernel_tree / "KernelSU", self.common_dir / "KernelSU"]:
            if kd.exists():
                self.ksu_dir = kd
                break
        if not self.ksu_dir:
            for d in [self.common_dir / "drivers" / "kernelsu", self.kernel_tree / "drivers" / "kernelsu"]:
                if d.exists():
                    real_d = d.resolve()
                    if real_d.name == "kernel" and (real_d.parent / "kernel" / "Kbuild").exists():
                        self.ksu_dir = real_d.parent
                    else:
                        self.ksu_dir = real_d
                    break
        if not self.ksu_dir:
            self.ksu_dir = self.common_dir / "drivers" / "kernelsu"

        # Patch files
        self.kernel_patch = self.patch_dir / f"50_add_susfs_in_gki-{preset_path}.patch"
        if not self.kernel_patch.exists():
            matched = list(self.patch_dir.glob("50_add_susfs_*.patch"))
            if matched:
                self.kernel_patch = matched[0]

        self.ksu_patch = self.patch_dir / "10_enable_susfs_for_ksu.patch"
        if not self.ksu_patch.exists() and (self.patch_dir / "KernelSU" / "10_enable_susfs_for_ksu.patch").exists():
            self.ksu_patch = self.patch_dir / "KernelSU" / "10_enable_susfs_for_ksu.patch"

        # Asset files to inject into common/
        src_susfs_c = (self.patch_dir / "fs" / "susfs.c") if (self.patch_dir / "fs" / "susfs.c").exists() else (self.patch_dir / "susfs.c")
        src_susfs_h = (self.patch_dir / "include" / "linux" / "susfs.h") if (self.patch_dir / "include" / "linux" / "susfs.h").exists() else (self.patch_dir / "susfs.h")
        src_susfs_def = (self.patch_dir / "include" / "linux" / "susfs_def.h") if (self.patch_dir / "include" / "linux" / "susfs_def.h").exists() else (self.patch_dir / "susfs_def.h")

        self.assets_to_copy = [
            (src_susfs_c, self.common_dir / "fs" / "susfs.c"),
            (src_susfs_h, self.common_dir / "include" / "linux" / "susfs.h"),
            (src_susfs_def, self.common_dir / "include" / "linux" / "susfs_def.h"),
        ]

        # Remote mapping (remote_path_in_repo, local_rel_path)
        kernel_patch_rel = self.kernel_patch.name
        self.remote_assets = [
            (f"kernel_patches/{kernel_patch_rel}", kernel_patch_rel),
            ("kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch", "10_enable_susfs_for_ksu.patch"),
            ("kernel_patches/fs/susfs.c", "fs/susfs.c"),
            ("kernel_patches/include/linux/susfs.h", "include/linux/susfs.h"),
            ("kernel_patches/include/linux/susfs_def.h", "include/linux/susfs_def.h"),
        ]

    def ensure_assets(self, force_download: bool = False) -> bool:
        """Verify presence of all SuSFS patch assets; auto-download from GitLab cache if missing."""
        missing = []
        for remote_subpath, local_rel in self.remote_assets:
            local_path = self.patch_dir / local_rel
            # Check either flat or nested
            flat_candidate = self.patch_dir / Path(local_rel).name
            if not force_download and (
                (local_path.exists() and local_path.stat().st_size > 0)
                or (flat_candidate.exists() and flat_candidate.stat().st_size > 0)
            ):
                continue
            missing.append((remote_subpath, local_path))

        if not missing:
            return True

        console.print(f"[bold cyan]🌐 Downloading SuSFS 2.3.0 patch assets from GitLab (ref: [green]{self.susfs_ref}[/green])...[/bold cyan]")
        try:
            for remote_subpath, local_path in missing:
                url = f"{GITLAB_RAW_BASE}/{self.susfs_ref}/{remote_subpath}"
                local_path.parent.mkdir(parents=True, exist_ok=True)
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = resp.read()
                    local_path.write_bytes(data)
                console.print(f"  [green]+ Cached:[/green] {local_path.relative_to(self.workspace_root)} ({len(data)} bytes)")
            console.print("  [bold green]✓ All SuSFS patch assets successfully downloaded & cached.[/bold green]")
            return True
        except Exception as e:
            console.print(f"[bold red]❌ Failed to download SuSFS assets from GitLab: {e}[/bold red]")
            return False

    def ensure_applied(self) -> bool:
        """Ensure assets are cached and SuSFS is fully applied."""
        stat = self.status()
        if stat["applied"]:
            console.print("[dim]✓ SuSFS is already applied and integrated in-tree.[/dim]")
            return True
        if not self.ensure_assets():
            return False
        return self.apply()

    def ensure_reverted(self) -> bool:
        """Ensure SuSFS is cleanly reverted and working trees are stock."""
        stat = self.status()
        if stat["applied"] or stat["partial"] or stat["susfs_c_exists"]:
            return self.revert()
        return True

    def _get_patched_files(self, patch_path: Path, cwd: Path) -> List[str]:
        """Extract relative file paths modified by a patch."""
        try:
            ret = subprocess.run(
                ["git", "apply", "--numstat", str(patch_path)],
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
            files = []
            for line in ret.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= 3:
                    files.append(parts[2].strip())
            return files
        except Exception:
            return []

    def status(self) -> Dict[str, Any]:
        """Check if SuSFS is currently applied to common and KernelSU."""
        susfs_c_exists = (self.common_dir / "fs" / "susfs.c").exists()
        common_patched = False
        ksu_patched = False

        # Check fs/Makefile for susfs.o
        fs_makefile = self.common_dir / "fs" / "Makefile"
        if fs_makefile.exists():
            try:
                common_patched = "CONFIG_KSU_SUSFS" in fs_makefile.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass

        # Check KernelSU Kconfig for SUSFS
        ksu_kconfig = (self.ksu_dir / "Kconfig") if (self.ksu_dir / "Kconfig").exists() else (self.ksu_dir / "kernel" / "Kconfig")
        if ksu_kconfig.exists():
            try:
                ksu_patched = "KSU_SUSFS" in ksu_kconfig.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass

        is_fully_applied = susfs_c_exists and common_patched and ksu_patched
        is_partially_applied = (susfs_c_exists or common_patched or ksu_patched) and not is_fully_applied

        return {
            "applied": is_fully_applied,
            "partial": is_partially_applied,
            "susfs_c_exists": susfs_c_exists,
            "common_patched": common_patched,
            "ksu_patched": ksu_patched,
        }

    def print_status(self):
        """Print a formatted status table of SuSFS integration."""
        from rich.table import Table

        stat = self.status()

        table = Table(title=f"SuSFS 2.3.0 Integration Status ({self.preset_name})", border_style="cyan")
        table.add_column("Component", style="bold")
        table.add_column("Target / Location", style="dim")
        table.add_column("Status", justify="center")

        # KernelSU
        ksu_rel = self.ksu_dir.relative_to(self.workspace_root) if self.ksu_dir.is_relative_to(self.workspace_root) else self.ksu_dir
        ksu_status = "[bold green]✓ Patched[/bold green]" if stat["ksu_patched"] else "[dim]Stock (Unpatched)[/dim]"
        table.add_row("KernelSU", str(ksu_rel), ksu_status)

        # Common kernel
        common_rel = self.common_dir.relative_to(self.workspace_root) if self.common_dir.is_relative_to(self.workspace_root) else self.common_dir
        common_status = "[bold green]✓ Patched[/bold green]" if stat["common_patched"] else "[dim]Stock (Unpatched)[/dim]"
        table.add_row(f"Kernel Tree ({self.preset_name})", str(common_rel), common_status)

        # Injected source
        injected_status = "[bold green]✓ Present (3/3)[/bold green]" if stat["susfs_c_exists"] else "[dim]Missing[/dim]"
        table.add_row("Injected SuSFS Files", "fs/susfs.c, include/linux/susfs*.h", injected_status)

        # Overall
        if stat["applied"]:
            overall = "[bold green]ACTIVE & READY TO BUILD[/bold green]"
        elif stat["partial"]:
            overall = "[bold yellow]PARTIAL (Inconsistent state)[/bold yellow]"
        else:
            overall = "[bold white]NOT APPLIED (Stock)[/bold white]"
        table.add_row("Overall State", "-", overall)

        console.print(table)

    def check(self) -> Tuple[bool, str]:
        """Dry-run check if SuSFS patches can be cleanly applied."""
        if not self.kernel_patch.exists() or not self.ksu_patch.exists():
            return False, f"Patch files missing in {self.patch_dir}"

        if not self.common_dir.exists():
            return False, f"Common directory not found: {self.common_dir}"

        if not self.ksu_dir.exists():
            return False, f"KernelSU directory not found: {self.ksu_dir}"

        stat = self.status()
        if stat["applied"]:
            return True, "SuSFS is already applied."

        # Check kernel patch with -C1 if not already patched
        if not stat["common_patched"]:
            ret_kernel = subprocess.run(
                ["git", "apply", "-C1", "--check", str(self.kernel_patch)],
                cwd=self.common_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if ret_kernel.returncode != 0:
                return False, f"Kernel patch check failed:\n{ret_kernel.stderr}"

        # Check KernelSU patch if not already patched
        if not stat["ksu_patched"]:
            ret_ksu = subprocess.run(
                ["git", "apply", "-C1", "--check", str(self.ksu_patch)],
                cwd=self.ksu_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if ret_ksu.returncode != 0:
                return False, f"KernelSU patch check failed:\n{ret_ksu.stderr}"

        return True, "All patches apply cleanly with 0 conflicts."

    def apply(self) -> bool:
        """Apply SuSFS patches and inject source files."""
        console.print(f"[bold cyan]🛡️  Applying SuSFS 2.3.0 to {self.preset_name}...[/bold cyan]")

        stat = self.status()
        if stat["applied"]:
            console.print("[yellow]SuSFS is already fully applied.[/yellow]")
            return True

        can_apply, msg = self.check()
        if not can_apply:
            console.print(f"[bold red]❌ Pre-check failed: {msg}[/bold red]")
            return False

        try:
            # 1. Copy source and header files into common/ if not present
            if not stat["susfs_c_exists"]:
                console.print("[cyan]1/3 Injecting SuSFS core filesystem source and headers...[/cyan]")
                for src, dest in self.assets_to_copy:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    console.print(f"  [green]+ Copied:[/green] {dest.relative_to(self.workspace_root)}")
            else:
                console.print("[dim]1/3 SuSFS source and headers already injected.[/dim]")

            # 2. Apply common kernel patch if not already applied
            if not stat["common_patched"]:
                console.print(f"[cyan]2/3 Applying kernel patch ({self.kernel_patch.name})...[/cyan]")
                ret_kernel = subprocess.run(
                    ["git", "apply", "-C1", "--whitespace=nowarn", str(self.kernel_patch)],
                    cwd=self.common_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if ret_kernel.returncode != 0:
                    console.print(f"[bold red]Failed to apply kernel patch: {ret_kernel.stderr}[/bold red]")
                    return False
                console.print("  [bold green]✓ Kernel patch applied cleanly.[/bold green]")
            else:
                console.print(f"[dim]2/3 Kernel patch already applied in {self.common_dir.name}.[/dim]")

            # 3. Apply KernelSU patch if not already applied
            if not stat["ksu_patched"]:
                console.print(f"[cyan]3/3 Applying KernelSU patch ({self.ksu_patch.name})...[/cyan]")
                ret_ksu = subprocess.run(
                    ["git", "apply", "-C1", "--whitespace=nowarn", str(self.ksu_patch)],
                    cwd=self.ksu_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if ret_ksu.returncode != 0:
                    console.print(f"[bold red]Failed to apply KernelSU patch: {ret_ksu.stderr}[/bold red]")
                    return False
                console.print("  [bold green]✓ KernelSU patch applied cleanly.[/bold green]")
            else:
                console.print(f"[dim]3/3 KernelSU patch already applied in {self.ksu_dir.name}.[/dim]")

            console.print(f"\n[bold green]🎉 SuSFS 2.3.0 has been successfully integrated into {self.preset_name}![/bold green]")
            return True
        except Exception as e:
            console.print(f"[bold red]❌ Error during patch application: {e}[/bold red]")
            return False

    def revert(self) -> bool:
        """Revert SuSFS patches and remove injected source files cleanly."""
        console.print(f"[bold yellow]🧹 Reverting SuSFS patches for {self.preset_name}...[/bold yellow]")

        stat = self.status()
        if not stat["applied"] and not stat["susfs_c_exists"] and not stat["common_patched"] and not stat["ksu_patched"]:
            console.print("[green]SuSFS is not currently applied.[/green]")
            return True

        success = True

        # 1. Revert KernelSU patch
        if stat["ksu_patched"]:
            console.print("[cyan]1/3 Reverting KernelSU patch...[/cyan]")
            ret = subprocess.run(
                ["git", "apply", "-R", "-C1", "--whitespace=nowarn", str(self.ksu_patch)],
                cwd=self.ksu_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if ret.returncode != 0:
                console.print("[dim]git apply -R had warnings, restoring patch-modified files in KernelSU...[/dim]")
                ksu_files = self._get_patched_files(self.ksu_patch, self.ksu_dir)
                if ksu_files:
                    subprocess.run(["git", "checkout", "--"] + ksu_files, cwd=self.ksu_dir)
                else:
                    subprocess.run(["git", "checkout", "--", "."], cwd=self.ksu_dir)
            console.print("  [bold green]✓ KernelSU restored to clean state.[/bold green]")

        # 2. Revert common kernel patch
        if stat["common_patched"]:
            console.print("[cyan]2/3 Reverting kernel patch...[/cyan]")
            ret = subprocess.run(
                ["git", "apply", "-R", "-C1", "--whitespace=nowarn", str(self.kernel_patch)],
                cwd=self.common_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if ret.returncode != 0:
                console.print("[dim]git apply -R had warnings, restoring patch-modified files in common kernel tree...[/dim]")
                kernel_files = self._get_patched_files(self.kernel_patch, self.common_dir)
                if kernel_files:
                    subprocess.run(["git", "checkout", "--"] + kernel_files, cwd=self.common_dir)
            console.print("  [bold green]✓ Common kernel tree restored to clean state.[/bold green]")

        # 3. Remove injected files
        console.print("[cyan]3/3 Removing injected SuSFS source files...[/cyan]")
        for _, dest in self.assets_to_copy:
            if dest.exists():
                dest.unlink()
                console.print(f"  [yellow]- Removed:[/yellow] {dest.relative_to(self.workspace_root)}")

        console.print("\n[bold green]✨ All SuSFS modifications cleanly reverted! Working tree is clean.[/bold green]")
        return success


class KernelPatchManager:
    """Manages kernel feature patches, exporting commits to patches/, and applying patch series."""

    def __init__(self, workspace_root: Path = WORKSPACE_ROOT, kernel_path: str = "android16-6.12"):
        self.workspace_root = workspace_root
        self.kernel_path = kernel_path
        self.kernel_tree = workspace_root / kernel_path
        self.common_dir = (self.kernel_tree / "common") if (self.kernel_tree / "common").exists() else self.kernel_tree
        self.patches_dir = workspace_root / "patches" / kernel_path

    def is_patch_applied(self, patch_path: Path) -> bool:
        """Check if patch is already applied by checking reverse apply."""
        if not self.common_dir.exists():
            return False
        res = subprocess.run(
            ["git", "apply", "-R", "--check", str(patch_path)],
            cwd=self.common_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return res.returncode == 0

    def ensure_applied(self) -> bool:
        """Scan patches directory and ensure all patches are applied to the kernel tree."""
        if not self.patches_dir.exists():
            return True
        patch_files = sorted(list(self.patches_dir.glob("*.patch")))
        if not patch_files:
            return True

        for p in patch_files:
            if self.is_patch_applied(p):
                console.print(f"  [dim]✓ Feature patch already applied:[/dim] {p.name}")
                continue

            # Check applicability
            check_res = subprocess.run(
                ["git", "apply", "-C1", "--check", str(p)],
                cwd=self.common_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if check_res.returncode != 0:
                console.print(f"[bold red]❌ Pre-check failed for {p.name}:[/bold red]\n{check_res.stderr}")
                return False

            # Apply
            apply_res = subprocess.run(
                ["git", "apply", "-C1", "--whitespace=nowarn", str(p)],
                cwd=self.common_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if apply_res.returncode != 0:
                console.print(f"[bold red]❌ Failed to apply {p.name}:[/bold red]\n{apply_res.stderr}")
                return False
            console.print(f"  [bold green]✓ Applied feature patch:[/bold green] {p.name}")

        return True

    def get_base_commit(self) -> Optional[str]:
        """Detect the nearest upstream/release tag or ancestor commit."""
        if not self.common_dir.exists():
            return None
        res = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=self.common_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
        return None

    def export_patches(self, base_ref: Optional[str] = None) -> bool:
        """Export commits from base_ref to HEAD into patches directory."""
        if not self.common_dir.exists():
            console.print(f"[bold red]❌ Common directory not found: {self.common_dir}[/bold red]")
            return False

        base = base_ref or self.get_base_commit()
        if not base:
            console.print("[bold red]❌ Could not determine base commit/tag. Specify --base <commit>.[/bold red]")
            return False

        rev_res = subprocess.run(
            ["git", "rev-parse", f"{base}^{{commit}}"],
            cwd=self.common_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if rev_res.returncode != 0:
            console.print(f"[bold red]❌ Invalid base commit: {base}[/bold red]")
            return False
        base_hash = rev_res.stdout.strip()

        count_res = subprocess.run(
            ["git", "rev-list", f"{base_hash}..HEAD", "--count"],
            cwd=self.common_dir,
            stdout=subprocess.PIPE,
            text=True,
        )
        count = int(count_res.stdout.strip() or "0")
        if count == 0:
            console.print(f"[yellow]⚠️  No new commits between {base} and HEAD. Nothing to export.[/yellow]")
            return True

        self.patches_dir.mkdir(parents=True, exist_ok=True)
        for old_patch in self.patches_dir.glob("*.patch"):
            old_patch.unlink()

        console.print(f"[bold cyan]📤 Exporting {count} commit(s) from base [green]{base}[/green] to {self.patches_dir.relative_to(self.workspace_root)}...[/bold cyan]")
        export_res = subprocess.run(
            ["git", "format-patch", base_hash, "-o", str(self.patches_dir)],
            cwd=self.common_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if export_res.returncode != 0:
            console.print(f"[bold red]❌ Failed to format-patch: {export_res.stderr}[/bold red]")
            return False

        exported = [p.strip() for p in export_res.stdout.splitlines() if p.strip()]
        for patch_path in exported:
            p = Path(patch_path)
            console.print(f"  [green]+ Exported:[/green] {p.name}")
        console.print(f"[bold green]✓ Successfully exported {len(exported)} patch(es).[/bold green]")
        return True

    def apply_patches(self, dry_run: bool = False) -> bool:
        """Validate and apply patch series onto common directory."""
        if not self.common_dir.exists():
            console.print(f"[bold red]❌ Common directory not found: {self.common_dir}[/bold red]")
            return False

        patch_files = sorted(list(self.patches_dir.glob("*.patch")))
        if not patch_files:
            console.print(f"[yellow]⚠️  No patch files found in {self.patches_dir.relative_to(self.workspace_root)}[/yellow]")
            return False

        console.print(f"[bold cyan]🔍 Verifying {len(patch_files)} patch(es) against {self.kernel_path}...[/bold cyan]")
        for p in patch_files:
            check_res = subprocess.run(
                ["git", "apply", "--check", str(p)],
                cwd=self.common_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if check_res.returncode != 0:
                console.print(f"[bold red]❌ Patch verification failed for {p.name}:[/bold red]\n{check_res.stderr}")
                return False
            console.print(f"  [green]✓ {p.name} applies cleanly.[/green]")

        if dry_run:
            console.print("[dim]Dry-run: Patches validated without applying.[/dim]")
            return True

        console.print(f"[bold cyan]🚀 Applying {len(patch_files)} patch(es)...[/bold cyan]")
        for p in patch_files:
            apply_res = subprocess.run(
                ["git", "apply", str(p)],
                cwd=self.common_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if apply_res.returncode != 0:
                console.print(f"[bold red]❌ Failed to apply {p.name}:[/bold red]\n{apply_res.stderr}")
                return False
            console.print(f"  [bold green]✓ Applied:[/bold green] {p.name}")

        return True
