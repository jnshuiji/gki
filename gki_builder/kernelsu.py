import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from rich.console import Console

console = Console()


class KernelSUManager:
    """Manages KernelSU version calculation and JIT Kbuild patching for Bazel builds."""

    def __init__(self, kernel_path: Path, dry_run: bool = False):
        self.kernel_path = kernel_path
        self.dry_run = dry_run
        self.ksu_repo: Optional[Path] = self._find_ksu_repo()
        self.kbuild_path: Optional[Path] = self._find_kbuild_path()
        self.original_kbuild_content: Optional[str] = None
        self.patched: bool = False

    def _find_ksu_repo(self) -> Optional[Path]:
        candidates = [
            self.kernel_path / "common" / "drivers" / "kernelsu",
            self.kernel_path / "drivers" / "kernelsu",
            self.kernel_path / "common" / "KernelSU",
            self.kernel_path / "KernelSU",
        ]
        for cand in candidates:
            if cand.exists() and (cand / "Kbuild").exists():
                return cand
            if cand.exists() and (cand / "kernel" / "Kbuild").exists():
                return cand
        return None

    def _find_driver_dir(self) -> Optional[Path]:
        driver_dirs = [
            self.kernel_path / "common" / "drivers",
            self.kernel_path / "drivers",
        ]
        for d in driver_dirs:
            if d.exists() and d.is_dir():
                return d
        return None

    def _find_kbuild_path(self) -> Optional[Path]:
        if not self.ksu_repo:
            return None
        if (self.ksu_repo / "Kbuild").exists():
            return self.ksu_repo / "Kbuild"
        if (self.ksu_repo / "kernel" / "Kbuild").exists():
            return self.ksu_repo / "kernel" / "Kbuild"
        symlink_candidate = self.kernel_path / "common" / "drivers" / "kernelsu" / "Kbuild"
        if symlink_candidate.exists():
            return symlink_candidate
        return None

    def _ensure_driver_wired(self) -> bool:
        """Wire driver symlink and Makefile/Kconfig if not already wired."""
        driver_dir = self._find_driver_dir()
        if not driver_dir:
            console.print(f"[bold red]❌ Driver directory not found in {self.kernel_path}[/bold red]")
            return False

        symlink_path = driver_dir / "kernelsu"

        # Check symlink or real directory
        if not symlink_path.exists():
            try:
                rel_target = Path("../KernelSU/kernel")
                symlink_path.symlink_to(rel_target)
                console.print(f"  [green]+ Linked:[/green] {symlink_path.relative_to(self.kernel_path)} -> {rel_target}")
            except Exception as e:
                console.print(f"[yellow]⚠️  Failed to create symlink: {e}[/yellow]")

        # Modify drivers/Makefile
        makefile = driver_dir / "Makefile"
        if makefile.exists():
            mf_content = makefile.read_text(encoding="utf-8")
            if "obj-$(CONFIG_KSU)" not in mf_content:
                mf_content = mf_content.rstrip() + "\n\nobj-$(CONFIG_KSU) += kernelsu/\n"
                makefile.write_text(mf_content, encoding="utf-8")
                console.print(f"  [green]+ Wired:[/green] Added obj-$(CONFIG_KSU) to {makefile.relative_to(self.kernel_path)}")

        # Modify drivers/Kconfig
        kconfig = driver_dir / "Kconfig"
        if kconfig.exists():
            kc_content = kconfig.read_text(encoding="utf-8")
            if 'source "drivers/kernelsu/Kconfig"' not in kc_content:
                if "endmenu" in kc_content:
                    kc_content = kc_content.replace("endmenu", 'source "drivers/kernelsu/Kconfig"\nendmenu', 1)
                else:
                    kc_content += '\nsource "drivers/kernelsu/Kconfig"\n'
                kconfig.write_text(kc_content, encoding="utf-8")
                console.print(f"  [green]+ Wired:[/green] Added source \"drivers/kernelsu/Kconfig\" to {kconfig.relative_to(self.kernel_path)}")

        # Refresh paths
        self.kbuild_path = self._find_kbuild_path()
        return True

    def ensure_installed_or_updated(self, target_ref: str = "latest_tag") -> bool:
        """Ensure KernelSU is installed/updated and wired into drivers."""
        # 1. Check if KernelSU is already built-in in-tree
        if self.ksu_repo and self.ksu_repo.exists() and ((self.ksu_repo / "Kbuild").exists() or (self.ksu_repo / "kernel" / "Kbuild").exists()):
            if not (self.ksu_repo / ".git").exists():
                console.print(f"[dim]✓ KernelSU is built-in (in-tree integrated at {self.ksu_repo.relative_to(self.kernel_path)})[/dim]")
                return True

        # 2. Check if KernelSU repository exists, clone if missing
        if not self.ksu_repo or not self.ksu_repo.exists() or not (self.ksu_repo / ".git").exists():
            target_dir = self.kernel_path / "common" / "KernelSU" if (self.kernel_path / "common").exists() else self.kernel_path / "KernelSU"
            console.print(f"[bold cyan]📥 KernelSU repository not found locally. Cloning from GitHub...[/bold cyan]")
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            res = subprocess.run(
                ["git", "clone", "https://github.com/tiann/KernelSU.git", str(target_dir)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if res.returncode != 0:
                console.print(f"[bold red]❌ Failed to clone KernelSU: {res.stderr}[/bold red]")
                return False
            self.ksu_repo = target_dir
            console.print(f"  [bold green]✓ KernelSU cloned to:[/bold green] {self.ksu_repo.relative_to(self.kernel_path)}")

        # 3. Fetch tags and determine latest stable release tag
        try:
            subprocess.run(
                ["git", "fetch", "--tags", "origin"],
                cwd=self.ksu_repo,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        except Exception:
            pass

        target_tag = target_ref
        if target_ref == "latest_tag":
            tag_res = subprocess.run(
                ["git", "tag", "-l", "v*", "--sort=-v:refname"],
                cwd=self.ksu_repo,
                stdout=subprocess.PIPE,
                text=True,
            )
            tags = [t.strip() for t in tag_res.stdout.splitlines() if t.strip()]
            if tags:
                target_tag = tags[0]
            else:
                target_tag = "main"

        # 4. Check current checked out commit or tag
        current_tag_res = subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=self.ksu_repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        current_tag = current_tag_res.stdout.strip() if current_tag_res.returncode == 0 else ""

        if current_tag != target_tag:
            console.print(f"[cyan]🔄 Updating KernelSU to stable release [bold green]{target_tag}[/bold green] (current: {current_tag or 'custom'})...[/cyan]")
            ret = subprocess.run(
                ["git", "checkout", target_tag],
                cwd=self.ksu_repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if ret.returncode != 0:
                console.print(f"[yellow]⚠️  Checkout {target_tag} warning: {ret.stderr.strip()}[/yellow]")
            else:
                console.print(f"  [bold green]✓ KernelSU checked out at {target_tag}.[/bold green]")
        else:
            console.print(f"[dim]✓ KernelSU is already at latest stable release: {target_tag}[/dim]")

        # 5. Ensure .git/info/exclude ignores ksu_version
        exclude_file = self.ksu_repo / ".git" / "info" / "exclude"
        if exclude_file.exists():
            content = exclude_file.read_text(encoding="utf-8", errors="ignore")
            if "ksu_version" not in content:
                exclude_file.write_text(content.rstrip() + "\nksu_version\n", encoding="utf-8")

        # 6. Wire driver symlink and Makefile/Kconfig
        return self._ensure_driver_wired()

    def disable(self) -> bool:
        """Safely detach KernelSU from the kernel tree when disabled."""
        console.print("[dim]🔌 Disabling KernelSU integration in drivers...[/dim]")
        driver_dir = self._find_driver_dir()
        if not driver_dir:
            return True

        symlink_path = driver_dir / "kernelsu"
        if symlink_path.is_symlink() or symlink_path.exists():
            try:
                symlink_path.unlink()
                console.print(f"  [dim]- Unlinked:[/dim] {symlink_path.relative_to(self.kernel_path)}")
            except Exception:
                pass

        makefile = driver_dir / "Makefile"
        if makefile.exists():
            content = makefile.read_text(encoding="utf-8")
            if "obj-$(CONFIG_KSU)" in content:
                import re
                cleaned = re.sub(r"\n?obj-\$\(CONFIG_KSU\)\s*\+=\s*kernelsu/?\n?", "\n", content)
                makefile.write_text(cleaned, encoding="utf-8")

        kconfig = driver_dir / "Kconfig"
        if kconfig.exists():
            content = kconfig.read_text(encoding="utf-8")
            if 'source "drivers/kernelsu/Kconfig"' in content:
                import re
                cleaned = re.sub(r'\n?source\s+"drivers/kernelsu/Kconfig"\n?', "\n", content)
                kconfig.write_text(cleaned, encoding="utf-8")

        return True

    def get_git_version(self) -> Optional[int]:
        if not self.ksu_repo:
            return None
        if not (self.ksu_repo / ".git").exists():
            # In-tree build with fixed version (v3.3.0: 30000 + 2601)
            return 32601
        try:
            ret = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=self.ksu_repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
            count = int(ret.stdout.strip())
            # KernelSU v3.x version scheme: 30000 + git commit count
            return 30000 + count
        except Exception as e:
            console.print(f"[yellow]⚠️  [KernelSU] Failed to read git commit count: {e}[/yellow]")
            return 32601

    def prepare(self) -> Optional[int]:
        """JIT patch Kbuild with exact git version before Bazel build starts."""
        if not self.ksu_repo or not self.kbuild_path:
            return None

        ksu_version = self.get_git_version()
        if not ksu_version:
            return None

        # If in-tree and not a separate git repo, Kbuild is already committed with flags
        if not (self.ksu_repo / ".git").exists():
            console.print(f"[dim][KernelSU Built-in][/dim] Version fixed in-tree: [bold green]{ksu_version}[/bold green]")
            return ksu_version

        if self.dry_run:
            console.print(
                f"[dim][KernelSU JIT][/dim] Detected KSU_VERSION: [bold green]{ksu_version}[/bold green] "
                f"(Dry-run: Kbuild in {self.ksu_repo.name} will be JIT-patched during real build)"
            )
            return ksu_version

        try:
            content = self.kbuild_path.read_text(encoding="utf-8")
            self.original_kbuild_content = content

            # Replace fallback ccflags-y += -DKSU_VERSION=16 with dynamic version and Clang 19 compat flags
            # -Wno-pointer-bool-conversion: Silences benign function pointer truthiness warning under Android 16 Clang
            clang_compat_flags = "-Wno-pointer-bool-conversion"
            target_fallback = "ccflags-y += -DKSU_VERSION=16"
            replacement = f"ccflags-y += -DKSU_VERSION={ksu_version} {clang_compat_flags}"

            if target_fallback in content:
                patched_content = content.replace(target_fallback, replacement, 1)
                self.kbuild_path.write_text(patched_content, encoding="utf-8")
                self.patched = True
                console.print(
                    f"[bold cyan]🔍 [KernelSU JIT][/bold cyan] Injected [bold green]KSU_VERSION={ksu_version}[/bold green] "
                    f"and [dim]{clang_compat_flags}[/dim] into Kbuild (will auto-restore after build)"
                )
            else:
                # If fallback line pattern not found, log notice
                console.print(f"[dim][KernelSU JIT] Kbuild already customized or target fallback line not matched.[/dim]")

            return ksu_version
        except Exception as e:
            console.print(f"[red]❌ [KernelSU JIT] Failed to patch Kbuild: {e}[/red]")
            return None

    def cleanup(self) -> None:
        """Restore Kbuild immediately after build, preserving clean working tree / SuSFS patch state."""
        if not self.patched or not self.kbuild_path:
            return

        try:
            if self.original_kbuild_content is not None:
                self.kbuild_path.write_text(self.original_kbuild_content, encoding="utf-8")

            self.patched = False
            console.print(f"[dim]🧹 [KernelSU JIT] Restored {self.kbuild_path.name} (working tree clean)[/dim]")
        except Exception as e:
            console.print(f"[yellow]⚠️  [KernelSU JIT] Failed to restore Kbuild: {e}[/yellow]")


@contextmanager
def kernelsu_build_context(kernel_path: Path, dry_run: bool = False) -> Generator[KernelSUManager, None, None]:
    """Context manager ensuring KernelSU Kbuild is JIT patched during build and safely restored afterwards."""
    manager = KernelSUManager(kernel_path, dry_run=dry_run)
    manager.prepare()
    try:
        yield manager
    finally:
        manager.cleanup()


# Short concise alias
ksu_patch = kernelsu_build_context

