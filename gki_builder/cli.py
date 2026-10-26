import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.prompt import Confirm, Prompt

from .anykernel import (
    package_anykernel,
    package_boot_image,
    package_kernel_artifacts,
)
from .config import BuildConfig, KernelPreset
from .kernel import build_kernel, run_bazel_clean
from .modules import ModuleManager
from .patcher import KernelPatchManager, SusfsPatcher
from .system_info import (
    get_system_resources,
    list_available_kernel_trees,
    scan_kernel_artifacts,
)
from .ui import (
    print_artifacts,
    print_banner,
    print_build_success,
    print_package_results,
    print_package_success,
    print_system_status,
)

console = Console()


def get_preset(config: BuildConfig, kernel_name: Optional[str]) -> KernelPreset:
    name = kernel_name or config.default_kernel
    if name not in config.kernels:
        console.print(f"[bold red]Kernel preset '{name}' not found in configuration![/bold red]")
        sys.exit(1)
    return config.kernels[name]


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """GKI Kernel Build & Packaging Suite."""
    if ctx.invoked_subcommand is None:
        interactive_menu()


@main.command()
@click.option("-k", "--kernel", default=None, help="Kernel tree name (default: from build_config.yaml)")
@click.option("-t", "--target", default=None, help="Bazel target (e.g. //common:kernel_aarch64_dist)")
@click.option("-l", "--lto", type=click.Choice(["none", "thin", "default", "full"]), default=None, help="LTO optimization mode (default: from preset in build_config.yaml)")
@click.option("-d", "--destdir", default=None, help="Output destination dir (default: out/dist)")
@click.option("-c", "--clean", is_flag=True, default=False, help="Clean Bazel build cache before building")
@click.option("--package/--no-package", "do_package", default=True, help="Automatically package artifacts after build")
@click.option("--format", "package_format", type=click.Choice(["auto", "boot", "anykernel", "both"]), default="auto", help="Packaging format (default: auto -> boot if OEM template exists, else anykernel)")
@click.option("--patch-devicecheck/--no-patch-devicecheck", default=None, help="Patch AnyKernel3 devicecheck to 0 for generic GKI")
@click.option("--boot-template", default=None, type=click.Path(path_type=Path), help="OEM boot.img template for Fastboot repacking")
@click.option("--ksu/--no-ksu", "enable_ksu", default=True, help="Enable & auto-update KernelSU (default: True)")
@click.option("--susfs/--no-susfs", "enable_susfs", default=True, help="Enable & auto-apply SuSFS addon (default: True)")
@click.option("--with-modules", is_flag=True, default=False, help="Automatically build & package companion modules after build")
@click.option("--dry-run", is_flag=True, default=False, help="Print build commands without running")
def build(kernel, target, lto, destdir, clean, do_package, package_format, patch_devicecheck, boot_template, enable_ksu, enable_susfs, with_modules, dry_run):
    """Build the GKI kernel and optionally package Boot Image or AnyKernel3."""
    print_banner()
    config = BuildConfig.load()
    preset = get_preset(config, kernel)

    console.print(f"[bold green]Selected Kernel:[/bold green] {preset.name} ({preset.path})\n")

    res = build_kernel(
        config=config,
        kernel_preset=preset,
        target=target,
        lto=lto,
        destdir=destdir,
        clean=clean,
        enable_ksu=enable_ksu,
        enable_susfs=enable_susfs,
        dry_run=dry_run,
    )

    if not res["success"]:
        console.print("[bold red]❌ Build failed! Please inspect logs above.[/bold red]")
        sys.exit(1)

    print_build_success(res["duration"], res["artifacts"])

    if do_package and not dry_run:
        console.print("\n[bold cyan]📦 Proceeding to artifact packaging...[/bold cyan]")
        try:
            pkg_res = package_kernel_artifacts(
                config=config,
                kernel_preset=preset,
                package_format=package_format,
                boot_template_path=boot_template,
                patch_devicecheck=patch_devicecheck,
            )
            print_package_results(pkg_res)
        except Exception as e:
            console.print(f"[bold red]❌ Packaging failed: {e}[/bold red]")
            sys.exit(1)

    if with_modules and not dry_run:
        console.print("\n[bold cyan]🧩 Triggering companion modules build...[/bold cyan]")
        mod_mgr = ModuleManager(workspace_root=config.workspace_root)
        mod_mgr.build_all()


@main.command()
@click.option("-k", "--kernel", default=None, help="Kernel tree name")
@click.option("-i", "--image", default=None, type=click.Path(path_type=Path), help="Explicit path to kernel Image")
@click.option("--format", "package_format", type=click.Choice(["auto", "boot", "anykernel", "both"]), default="auto", help="Package format (default: auto -> boot if OEM template exists, else anykernel)")
@click.option("-o", "--output-dir", default=None, type=click.Path(path_type=Path), help="Output directory")
@click.option("--name", "custom_name", default=None, help="Custom output filename")
@click.option("--patch-devicecheck/--no-patch-devicecheck", default=None, help="Patch AnyKernel3 devicecheck to 0")
@click.option("--boot-template", default=None, type=click.Path(path_type=Path), help="OEM boot.img template for Fastboot repacking")
def package(kernel, image, package_format, output_dir, custom_name, patch_devicecheck, boot_template):
    """Package built Image into Fastboot boot.img (if OEM template exists) or AnyKernel3 zip."""
    print_banner()
    config = BuildConfig.load()
    preset = get_preset(config, kernel)

    console.print(f"[bold cyan]📦 Packaging artifacts for {preset.name} (Format: {package_format})...[/bold cyan]")
    try:
        pkg_res = package_kernel_artifacts(
            config=config,
            kernel_preset=preset,
            package_format=package_format,
            image_path=image,
            boot_template_path=boot_template,
            output_dir=output_dir,
            custom_name=custom_name,
            patch_devicecheck=patch_devicecheck,
        )
        print_package_results(pkg_res)
    except Exception as e:
        console.print(f"[bold red]❌ Packaging failed: {e}[/bold red]")
        sys.exit(1)


@main.command()
@click.option("-k", "--kernel", default=None, help="Kernel tree name")
def clean(kernel):
    """Clean Bazel build outputs and cache."""
    config = BuildConfig.load()
    preset = get_preset(config, kernel)
    kernel_path = preset.get_abs_path(config.workspace_root)
    run_bazel_clean(kernel_path)


@main.command()
@click.option("-k", "--kernel", default=None, help="Kernel tree name")
def info(kernel):
    """Show system resources, detected trees, and build artifacts."""
    print_banner()
    config = BuildConfig.load()
    preset = get_preset(config, kernel)

    sys_res = get_system_resources(config.workspace_root)
    trees = list_available_kernel_trees(config.workspace_root)
    print_system_status(sys_res, trees)

    kernel_path = preset.get_abs_path(config.workspace_root)
    artifacts = scan_kernel_artifacts(kernel_path, destdir=preset.destdir)
    print_artifacts(artifacts)


@main.group()
def patch():
    """Manage kernel patches (e.g. SuSFS)."""
    pass


@patch.command("susfs")
@click.option("-k", "--kernel", default=None, help="Kernel tree name (default: from build_config.yaml)")
@click.option("--apply", "do_apply", is_flag=True, help="Apply SuSFS patches and inject source files")
@click.option("--revert", "do_revert", is_flag=True, help="Revert SuSFS patches and clean working trees")
@click.option("--status", "do_status", is_flag=True, help="Display SuSFS patch status")
@click.option("--check", "do_check", is_flag=True, help="Dry-run check if SuSFS patches apply cleanly")
def patch_susfs(kernel, do_apply, do_revert, do_status, do_check):
    """Manage SuSFS 2.3.0 patch integration for KernelSU & GKI Kernel."""
    config = BuildConfig.load()
    preset = get_preset(config, kernel)
    patcher = SusfsPatcher(workspace_root=config.workspace_root, kernel_preset=preset)

    if do_apply:
        if not patcher.apply():
            sys.exit(1)
    elif do_revert:
        if not patcher.revert():
            sys.exit(1)
    elif do_check:
        can_apply, msg = patcher.check()
        if can_apply:
            console.print(f"[bold green]✓ {msg}[/bold green]")
        else:
            console.print(f"[bold red]❌ {msg}[/bold red]")
            sys.exit(1)
    else:
        # Default or --status
        patcher.print_status()


@patch.command("export")
@click.option("-k", "--kernel", default=None, help="Kernel tree name (default: from build_config.yaml)")
@click.option("-b", "--base", default=None, help="Base commit/tag to format patch from (default: auto-detected tag)")
def patch_export(kernel, base):
    """Export commits on current branch to patches/ directory."""
    config = BuildConfig.load()
    preset = get_preset(config, kernel)
    mgr = KernelPatchManager(workspace_root=config.workspace_root, kernel_path=preset.path)
    if not mgr.export_patches(base_ref=base):
        sys.exit(1)


@patch.command("apply")
@click.option("-k", "--kernel", default=None, help="Kernel tree name (default: from build_config.yaml)")
@click.option("--dry-run", is_flag=True, default=False, help="Verify patch applicability without applying")
def patch_apply(kernel, dry_run):
    """Validate and apply patch series onto the common kernel tree."""
    config = BuildConfig.load()
    preset = get_preset(config, kernel)
    mgr = KernelPatchManager(workspace_root=config.workspace_root, kernel_path=preset.path)
    if not mgr.apply_patches(dry_run=dry_run):
        sys.exit(1)


@main.group("module")
def module():
    """Manage GKI companion modules (kread, pochita, etc.)."""
    pass


@module.command("list")
def module_list():
    """List all detected companion modules and their status."""
    print_banner()
    config = BuildConfig.load()
    mgr = ModuleManager(workspace_root=config.workspace_root)
    mgr.print_status_table()


@module.command("build")
@click.argument("name", default="all")
@click.option("-t", "--target", type=click.Choice(["all", "5.10", "6.12"]), default="all", help="Target kernel (default: all)")
@click.option("--skip-daemon", is_flag=True, default=False, help="Skip compiling Rust daemon")
@click.option("--skip-ko", is_flag=True, default=False, help="Skip compiling kernel modules")
@click.option("--package/--no-package", "do_package", default=True, help="Automatically package into zip")
def module_build(name, target, skip_daemon, skip_ko, do_package):
    """Build companion module(s) [e.g. kread, pochita, or all]."""
    print_banner()
    config = BuildConfig.load()
    mgr = ModuleManager(workspace_root=config.workspace_root)
    if name == "all":
        ok = mgr.build_all(target=target, skip_daemon=skip_daemon, skip_ko=skip_ko, do_package=do_package)
    else:
        ok = mgr.build_module(name, target=target, skip_daemon=skip_daemon, skip_ko=skip_ko, do_package=do_package)
    if not ok:
        sys.exit(1)


@module.command("package")
@click.argument("name", default="all")
@click.option("-t", "--target", type=click.Choice(["all", "5.10", "6.12"]), default="all", help="Target kernel (default: all)")
def module_package(name, target):
    """Package companion module(s) into flashable zip."""
    print_banner()
    config = BuildConfig.load()
    mgr = ModuleManager(workspace_root=config.workspace_root)
    if name == "all":
        ok = mgr.build_all(target=target, skip_daemon=True, skip_ko=True, do_package=True)
    else:
        ok = mgr.build_module(name, target=target, skip_daemon=True, skip_ko=True, do_package=True)
    if not ok:
        sys.exit(1)


@main.command()
def menu():
    """Start interactive build menu."""
    interactive_menu()


def interactive_menu():
    print_banner()
    config = BuildConfig.load()

    console.print("[bold yellow]Choose an action:[/bold yellow]")
    console.print("  [1] 🚀 Quick Build & Package (Auto: Boot Image if OEM template exists, else AnyKernel)")
    console.print("  [2] 📦 Package Artifacts (Auto: Boot Image if OEM template exists, else AnyKernel)")
    console.print("  [3] ⚙️  Custom Build & Package (Target, LTO, Format)")
    console.print("  [4] 🧹 Clean Bazel Cache")
    console.print("  [5] ℹ️  System & Artifacts Status")
    console.print("  [6] 🛡️  SuSFS Patch Management (Status / Apply / Revert)")
    console.print("  [7] 🧩 Companion Modules (kread / pochita)")
    console.print("  [0] 🚪 Exit\n")

    choice = Prompt.ask("Select option", choices=["0", "1", "2", "3", "4", "5", "6", "7"], default="1")

    if choice == "0":
        console.print("[cyan]Goodbye![/cyan]")
        return
    elif choice == "1":
        preset = get_preset(config, config.default_kernel)
        res = build_kernel(config, preset, lto="none", clean=False, enable_ksu=True, enable_susfs=True)
        if res["success"]:
            print_build_success(res["duration"], res["artifacts"])
            pkg_res = package_kernel_artifacts(config, preset, package_format="auto")
            print_package_results(pkg_res)
    elif choice == "2":
        preset = get_preset(config, config.default_kernel)
        pkg_res = package_kernel_artifacts(config, preset, package_format="auto")
        print_package_results(pkg_res)
    elif choice == "3":
        # Custom build
        available = list(config.kernels.keys())
        k_choice = Prompt.ask("Kernel Tree", choices=available, default=config.default_kernel)
        preset = get_preset(config, k_choice)

        lto_choice = Prompt.ask("LTO Mode", choices=["none", "thin", "default", "full"], default="none")
        ksu_choice = Confirm.ask("Enable & auto-update KernelSU?", default=True)
        susfs_choice = False
        if ksu_choice:
            susfs_choice = Confirm.ask("Enable & auto-apply SuSFS addon?", default=True)

        do_clean = Confirm.ask("Clean Bazel cache before build?", default=False)
        do_pkg = Confirm.ask("Package artifacts afterwards?", default=True)

        pkg_format = "auto"
        if do_pkg:
            pkg_format = Prompt.ask(
                "Packaging Format",
                choices=["auto", "boot", "anykernel", "both"],
                default="auto",
            )

        res = build_kernel(
            config,
            preset,
            lto=lto_choice,
            clean=do_clean,
            enable_ksu=ksu_choice,
            enable_susfs=susfs_choice,
        )
        if res["success"]:
            print_build_success(res["duration"], res["artifacts"])
            if do_pkg:
                pkg_res = package_kernel_artifacts(
                    config=config,
                    kernel_preset=preset,
                    package_format=pkg_format,
                )
                print_package_results(pkg_res)
    elif choice == "4":
        preset = get_preset(config, config.default_kernel)
        kernel_path = preset.get_abs_path(config.workspace_root)
        run_bazel_clean(kernel_path)
    elif choice == "5":
        info.callback(kernel=None)
    elif choice == "6":
        available = list(config.kernels.keys())
        k_choice = Prompt.ask("Kernel Tree", choices=available, default=config.default_kernel)
        preset = get_preset(config, k_choice)
        patcher = SusfsPatcher(workspace_root=config.workspace_root, kernel_preset=preset)
        patcher.print_status()
        sub_choice = Prompt.ask(
            "Action",
            choices=["status", "apply", "revert", "check", "back"],
            default="status",
        )
        if sub_choice == "apply":
            patcher.apply()
        elif sub_choice == "revert":
            patcher.revert()
        elif sub_choice == "check":
            can_apply, msg = patcher.check()
            if can_apply:
                console.print(f"[bold green]✓ {msg}[/bold green]")
            else:
                console.print(f"[bold red]❌ {msg}[/bold red]")
    elif choice == "7":
        mgr = ModuleManager(workspace_root=config.workspace_root)
        mgr.print_status_table()
        sub = Prompt.ask("Action", choices=["build", "package", "back"], default="build")
        if sub == "build":
            target = Prompt.ask("Kernel Target", choices=["all", "5.10", "6.12"], default="all")
            mgr.build_all(target=target)
        elif sub == "package":
            target = Prompt.ask("Kernel Target", choices=["all", "5.10", "6.12"], default="all")
            mgr.build_all(target=target, skip_daemon=True, skip_ko=True, do_package=True)


if __name__ == "__main__":
    main()

