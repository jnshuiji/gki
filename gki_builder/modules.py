"""
modules.py - Generic Companion Module Management & Unified Build Subsystem.
Discovers and builds companion modules (e.g. kread, pochita) under modules/.
"""

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import BuildConfig

console = Console()


@dataclass
class ModuleInfo:
    name: str
    path: Path
    version: str
    version_code: str
    description: str
    has_ko: bool
    has_daemon: bool
    has_build_py: bool

    @classmethod
    def from_directory(cls, dir_path: Path) -> Optional["ModuleInfo"]:
        prop_file = dir_path / "module.prop"
        if not prop_file.exists():
            return None

        name = dir_path.name
        version = "1.0.0"
        version_code = "1"
        description = ""

        try:
            for line in prop_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("version="):
                    version = line.split("=", 1)[1].strip()
                elif line.startswith("versionCode="):
                    version_code = line.split("=", 1)[1].strip()
                elif line.startswith("description="):
                    description = line.split("=", 1)[1].strip()
                elif line.startswith("name="):
                    name = line.split("=", 1)[1].strip()
        except Exception:
            pass

        has_ko = (dir_path / "src").exists() or (dir_path / "BUILD.bazel").exists() or (dir_path / "Kbuild").exists()
        has_daemon = (dir_path / "daemon").exists()
        has_build_py = (dir_path / "build.py").exists()

        return cls(
            name=dir_path.name,
            path=dir_path,
            version=version,
            version_code=version_code,
            description=description,
            has_ko=has_ko,
            has_daemon=has_daemon,
            has_build_py=has_build_py,
        )


class ModuleManager:
    """Discovers, builds, and packages companion modules."""

    def __init__(self, workspace_root: Optional[Path] = None, output_dir: Optional[Path] = None):
        self.workspace_root = workspace_root or Path(__file__).resolve().parent.parent
        self.modules_dir = self.workspace_root / "modules"
        self.output_dir = output_dir or (self.workspace_root / "out" / "release" / "modules")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def discover(self) -> Dict[str, ModuleInfo]:
        """Discover all valid companion modules in modules/."""
        modules = {}
        if not self.modules_dir.exists():
            return modules

        for item in sorted(self.modules_dir.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                mod = ModuleInfo.from_directory(item)
                if mod:
                    modules[mod.name] = mod
        return modules

    def print_status_table(self):
        """Display an overview table of all detected companion modules."""
        modules = self.discover()
        table = Table(title="🧩 Detected GKI Companion Modules", border_style="cyan")
        table.add_column("Module ID", style="bold cyan")
        table.add_column("Version", justify="center")
        table.add_column("Components", justify="center")
        table.add_column("Build Engine", justify="center")
        table.add_column("Description", style="dim")

        if not modules:
            table.add_row("-", "-", "No modules found in modules/", "-", "-")
        else:
            for mod in modules.values():
                comps = []
                if mod.has_ko:
                    comps.append("[bold green]Kernel Module (.ko)[/bold green]")
                if mod.has_daemon:
                    comps.append("[bold yellow]Rust Daemon[/bold yellow]")
                if not comps:
                    comps.append("[dim]Magisk Scripts[/dim]")

                engine = "Python build.py" if mod.has_build_py else "Shell build.sh"
                table.add_row(
                    mod.name,
                    f"v{mod.version} ({mod.version_code})",
                    " + ".join(comps),
                    engine,
                    mod.description[:50] + ("..." if len(mod.description) > 50 else ""),
                )

        console.print(table)

    def build_module(
        self,
        name: str,
        target: str = "all",
        skip_daemon: bool = False,
        skip_ko: bool = False,
        do_package: bool = True,
    ) -> bool:
        """Build and package a specific companion module."""
        modules = self.discover()
        if name not in modules:
            console.print(f"[bold red]❌ Unknown module '{name}'. Available: {', '.join(modules.keys())}[/bold red]")
            return False

        mod = modules[name]
        console.print(f"\n[bold green]🚀 Building companion module: {mod.name} (v{mod.version})[/bold green]")

        # 1. Specialized builder for kread
        if mod.name == "kread" and mod.has_build_py:
            try:
                # Dynamic import or execution of modules/kread/build.py
                sys.path.insert(0, str(mod.path))
                from build import KreadBuilder

                builder = KreadBuilder(workspace_root=self.workspace_root)
                res = builder.run(
                    target=target,
                    skip_daemon=skip_daemon,
                    skip_ko=skip_ko,
                    do_package=do_package,
                    extra_out_dir=self.output_dir,
                )
                return res is not None or not do_package
            except Exception as e:
                console.print(f"[bold red]❌ Failed building kread module: {e}[/bold red]")
                return False

        # 2. Generic python build.py
        if mod.has_build_py:
            cmd = [sys.executable, str(mod.path / "build.py")]
            res = subprocess.run(cmd, cwd=mod.path)
            return res.returncode == 0

        # 3. Generic shell build.sh fallback
        build_sh = mod.path / "build.sh"
        if build_sh.exists():
            cmd = ["bash", str(build_sh)]
            res = subprocess.run(cmd, cwd=mod.path)
            return res.returncode == 0

        console.print(f"[yellow]⚠️  No build script found for module {mod.name}.[/yellow]")
        return False

    def build_all(
        self,
        target: str = "all",
        skip_daemon: bool = False,
        skip_ko: bool = False,
        do_package: bool = True,
    ) -> bool:
        """Build all detected companion modules."""
        modules = self.discover()
        if not modules:
            console.print("[yellow]No companion modules found in modules/[/yellow]")
            return True

        all_ok = True
        for mod_name in modules:
            ok = self.build_module(
                mod_name,
                target=target,
                skip_daemon=skip_daemon,
                skip_ko=skip_ko,
                do_package=do_package,
            )
            if not ok:
                all_ok = False
        return all_ok
