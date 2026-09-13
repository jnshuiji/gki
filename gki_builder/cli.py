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
@click.option("-l", "--lto", type=click.Choice(["none", "thin", "default", "full"]), default=None, help="LTO optimization mode (default: none)")
@click.option("-d", "--destdir", default=None, help="Output destination dir (default: out/dist)")
@click.option("-c", "--clean", is_flag=True, default=False, help="Clean Bazel build cache before building")
@click.option("--package/--no-package", "do_package", default=True, help="Automatically package artifacts after build")
@click.option("--format", "package_format", type=click.Choice(["auto", "boot", "anykernel", "both"]), default="auto", help="Packaging format (default: auto -> boot if OEM template exists, else anykernel)")
@click.option("--patch-devicecheck/--no-patch-devicecheck", default=None, help="Patch AnyKernel3 devicecheck to 0 for generic GKI")
@click.option("--boot-template", default=None, type=click.Path(path_type=Path), help="OEM boot.img template for Fastboot repacking")
@click.option("--dry-run", is_flag=True, default=False, help="Print build commands without running")
def build(kernel, target, lto, destdir, clean, do_package, package_format, patch_devicecheck, boot_template, dry_run):
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
    console.print("  [0] 🚪 Exit\n")

    choice = Prompt.ask("Select option", choices=["0", "1", "2", "3", "4", "5"], default="1")

    if choice == "0":
        console.print("[cyan]Goodbye![/cyan]")
        return
    elif choice == "1":
        preset = get_preset(config, config.default_kernel)
        res = build_kernel(config, preset, lto="none", clean=False)
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
        do_clean = Confirm.ask("Clean Bazel cache before build?", default=False)
        do_pkg = Confirm.ask("Package artifacts afterwards?", default=True)

        pkg_format = "auto"
        if do_pkg:
            pkg_format = Prompt.ask(
                "Packaging Format",
                choices=["auto", "boot", "anykernel", "both"],
                default="auto",
            )

        res = build_kernel(config, preset, lto=lto_choice, clean=do_clean)
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


if __name__ == "__main__":
    main()
