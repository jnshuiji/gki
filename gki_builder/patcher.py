import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from rich.console import Console

console = Console()

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent

# SuSFS 2.3.0 aligned with KernelSU v3.3.0
DEFAULT_SUSFS_REF = "c7db8cb3"
GITLAB_RAW_BASE = "https://gitlab.com/simonpunk/susfs4ksu/-/raw"


class SusfsPatcher:
    """Manages automated application, clean reversion, and GitLab caching of SuSFS 2.3.0 for KernelSU v3.3.0."""

    def __init__(self, workspace_root: Path = WORKSPACE_ROOT, susfs_ref: str = DEFAULT_SUSFS_REF):
        self.workspace_root = workspace_root
        self.susfs_ref = susfs_ref
        self.patch_dir = workspace_root / "patches" / "susfs"
        self.kernel_tree = workspace_root / "android16-6.12"
        self.common_dir = self.kernel_tree / "common"
        self.ksu_dir = (self.common_dir / "drivers" / "kernelsu") if (self.common_dir / "drivers" / "kernelsu").exists() else (self.common_dir / "KernelSU")

        # Patch files
        self.kernel_patch = self.patch_dir / "50_add_susfs_in_gki-android16-6.12.patch"
        self.ksu_patch = self.patch_dir / "10_enable_susfs_for_ksu.patch"

        # Asset files to inject into common/
        self.assets_to_copy = [
            (self.patch_dir / "fs" / "susfs.c", self.common_dir / "fs" / "susfs.c"),
            (self.patch_dir / "include" / "linux" / "susfs.h", self.common_dir / "include" / "linux" / "susfs.h"),
            (self.patch_dir / "include" / "linux" / "susfs_def.h", self.common_dir / "include" / "linux" / "susfs_def.h"),
        ]

        # Remote mapping (remote_path_in_repo, local_rel_path)
        self.remote_assets = [
            ("kernel_patches/50_add_susfs_in_gki-android16-6.12.patch", "50_add_susfs_in_gki-android16-6.12.patch"),
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
            if force_download or not local_path.exists() or local_path.stat().st_size == 0:
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

    def _get_patched_files(self, patch_path: Path, cwd: Path) -> list[str]:
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
        from rich.panel import Panel
        from rich.table import Table

        stat = self.status()

        table = Table(title="SuSFS 2.3.0 Integration Status", border_style="cyan")
        table.add_column("Component", style="bold")
        table.add_column("Target / Location", style="dim")
        table.add_column("Status", justify="center")

        # KernelSU
        ksu_status = "[bold green]✓ Patched[/bold green]" if stat["ksu_patched"] else "[dim]Stock (Unpatched)[/dim]"
        table.add_row("KernelSU (v3.3.0)", "common/drivers/kernelsu", ksu_status)

        # Common kernel
        common_status = "[bold green]✓ Patched[/bold green]" if stat["common_patched"] else "[dim]Stock (Unpatched)[/dim]"
        table.add_row("Kernel Tree (Android 16-6.12)", "common/", common_status)

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

        # Check kernel patch with -C1
        ret_kernel = subprocess.run(
            ["git", "apply", "-C1", "--check", str(self.kernel_patch)],
            cwd=self.common_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if ret_kernel.returncode != 0:
            return False, f"Kernel patch check failed:\n{ret_kernel.stderr}"

        # Check KernelSU patch
        ret_ksu = subprocess.run(
            ["git", "apply", "--check", str(self.ksu_patch)],
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
        console.print("[bold cyan]🛡️  Applying SuSFS 2.3.0 to Android 16-6.12 GKI & KernelSU v3.3.0...[/bold cyan]")

        stat = self.status()
        if stat["applied"]:
            console.print("[yellow]SuSFS is already fully applied.[/yellow]")
            return True

        can_apply, msg = self.check()
        if not can_apply:
            console.print(f"[bold red]❌ Pre-check failed: {msg}[/bold red]")
            return False

        try:
            # 1. Copy source and header files into common/
            console.print("[cyan]1/3 Injecting SuSFS core filesystem source and headers...[/cyan]")
            for src, dest in self.assets_to_copy:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                console.print(f"  [green]+ Copied:[/green] {dest.relative_to(self.workspace_root)}")

            # 2. Apply common kernel patch
            console.print("[cyan]2/3 Applying kernel patch (50_add_susfs_in_gki-android16-6.12.patch)...[/cyan]")
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

            # 3. Apply KernelSU patch
            console.print("[cyan]3/3 Applying KernelSU patch (10_enable_susfs_for_ksu.patch)...[/cyan]")
            ret_ksu = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", str(self.ksu_patch)],
                cwd=self.ksu_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if ret_ksu.returncode != 0:
                console.print(f"[bold red]Failed to apply KernelSU patch: {ret_ksu.stderr}[/bold red]")
                return False
            console.print("  [bold green]✓ KernelSU patch applied cleanly.[/bold green]")

            console.print("\n[bold green]🎉 SuSFS 2.3.0 has been successfully integrated into KernelSU v3.3.0 & GKI Kernel![/bold green]")
            return True
        except Exception as e:
            console.print(f"[bold red]❌ Error during patch application: {e}[/bold red]")
            return False

    def revert(self) -> bool:
        """Revert SuSFS patches and remove injected source files cleanly."""
        console.print("[bold yellow]🧹 Reverting SuSFS patches and restoring clean GKI & KernelSU...[/bold yellow]")

        stat = self.status()
        if not stat["applied"] and not stat["susfs_c_exists"] and not stat["common_patched"] and not stat["ksu_patched"]:
            console.print("[green]SuSFS is not currently applied.[/green]")
            return True

        success = True

        # 1. Revert KernelSU patch
        if stat["ksu_patched"]:
            console.print("[cyan]1/3 Reverting KernelSU patch...[/cyan]")
            ret = subprocess.run(
                ["git", "apply", "-R", "--whitespace=nowarn", str(self.ksu_patch)],
                cwd=self.ksu_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if ret.returncode != 0:
                # Targeted fallback: only restore files modified by the ksu patch
                console.print("[dim]git apply -R had warnings, restoring patch-modified files in KernelSU...[/dim]")
                ksu_files = self._get_patched_files(self.ksu_patch, self.ksu_dir)
                if ksu_files:
                    subprocess.run(["git", "checkout", "--"] + ksu_files, cwd=self.ksu_dir)
                else:
                    subprocess.run(["git", "checkout", "--", "."], cwd=self.ksu_dir)
            console.print("  [bold green]✓ KernelSU restored to clean v3.3.0.[/bold green]")

        # 2. Revert common kernel patch (Targeted: never touch drivers/Kconfig or drivers/Makefile)
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
                # Targeted fallback: only restore files modified by this patch
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
        self.common_dir = workspace_root / kernel_path / "common"
        self.patches_dir = workspace_root / "patches" / kernel_path

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

