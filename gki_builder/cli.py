import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.prompt import Confirm, Prompt

from .anykernel import package_anykernel
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
    print_package_success,
    print_system_status,
)

console = Console()


def get_preset(config: BuildConfig, kernel_name: Optional[str]) -> KernelPreset:
    name = kernel_name or config.default_kernel
    if name not in config.kernels:
        # Check if dir exists directly
        candidate_dir = config.workspace_root / name
        if candidate_dir.exists():
            return KernelPreset(
                name=name,
                path=name,
                build_system="kleaf",
                default_target="//common:kernel_aarch64_dist",
                default_lto="none",
                destdir="out/dist",
            )
        console.print(f"[red]Error: Unknown kernel '{name}'. Available: {list(config.kernels.keys())}[/red]")
        sys.exit(1)
    return config.kernels[name]


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context):
    """GKI Kernel Build & Packaging Suite."""
    if ctx.invoked_subcommand is None:
        interactive_menu()


@main.command()
@click.option("-k", "--kernel", default=None, help="Kernel tree name (default: from build_config.yaml)")
@click.option("-t", "--target", default=None, help="Bazel target (e.g. //common:kernel_aarch64_dist)")
@click.option("-l", "--lto", type=click.Choice(["none", "thin", "default", "full"]), default=None, help="LTO optimization mode (default: none)")
@click.option("-d", "--destdir", default=None, help="Output destination dir (default: out/dist)")
@click.option("-c", "--clean", is_flag=True, default=False, help="Clean Bazel build cache before building")
@click.option("--ak3/--no-ak3", default=True, help="Automatically package into AnyKernel3 zip after build")
@click.option("--patch-devicecheck/--no-patch-devicecheck", default=None, help="Patch AnyKernel3 devicecheck to 0 for generic GKI")
@click.option("--dry-run", is_flag=True, default=False, help="Print build commands without running")
def build(kernel, target, lto, destdir, clean, ak3, patch_devicecheck, dry_run):
    """Build the GKI kernel and optionally package AnyKernel3."""
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

    if ak3 and not dry_run:
        console.print("\n[bold cyan]📦 Proceeding to AnyKernel3 packaging...[/bold cyan]")
        try:
            ak_res = package_anykernel(
                config=config,
                kernel_preset=preset,
                patch_devicecheck=patch_devicecheck,
            )
            print_package_success(
                zip_path=ak_res["zip_path"],
                size=ak_res["size"],
                sha256=ak_res["sha256"],
                duration=ak_res["duration"],
            )
        except Exception as e:
            console.print(f"[bold red]❌ AnyKernel3 packaging failed: {e}[/bold red]")
            sys.exit(1)


@main.command()
@click.option("-k", "--kernel", default=None, help="Kernel tree name")
@click.option("-i", "--image", default=None, type=click.Path(path_type=Path), help="Explicit path to kernel Image")
@click.option("-o", "--output-dir", default=None, type=click.Path(path_type=Path), help="Output directory for zip")
@click.option("--name", "zip_name", default=None, help="Custom zip filename")
@click.option("--patch-devicecheck/--no-patch-devicecheck", default=None, help="Patch AnyKernel3 devicecheck to 0")
def package(kernel, image, output_dir, zip_name, patch_devicecheck):
    """Package existing built Image into AnyKernel3 zip without building."""
    print_banner()
    config = BuildConfig.load()
    preset = get_preset(config, kernel)

    console.print(f"[bold cyan]📦 Packaging AnyKernel3 for {preset.name}...[/bold cyan]")
    try:
        ak_res = package_anykernel(
            config=config,
            kernel_preset=preset,
            image_path=image,
            output_dir=output_dir,
            custom_zip_name=zip_name,
            patch_devicecheck=patch_devicecheck,
        )
        print_package_success(
            zip_path=ak_res["zip_path"],
            size=ak_res["size"],
            sha256=ak_res["sha256"],
            duration=ak_res["duration"],
        )
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
    console.print("  [1] 🚀 Quick Build (android16-6.12, lto=none, auto AnyKernel3 zip)")
    console.print("  [2] 📦 Package AnyKernel3 ZIP (from existing Image)")
    console.print("  [3] ⚙️  Custom Build (select target, lto, clean options)")
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
            ak_res = package_anykernel(config, preset)
            print_package_success(ak_res["zip_path"], ak_res["size"], ak_res["sha256"], ak_res["duration"])
    elif choice == "2":
        preset = get_preset(config, config.default_kernel)
        ak_res = package_anykernel(config, preset)
        print_package_success(ak_res["zip_path"], ak_res["size"], ak_res["sha256"], ak_res["duration"])
    elif choice == "3":
        # Custom build
        available = list(config.kernels.keys())
        k_choice = Prompt.ask("Kernel Tree", choices=available, default=config.default_kernel)
        preset = get_preset(config, k_choice)

        lto_choice = Prompt.ask("LTO Mode", choices=["none", "thin", "default", "full"], default="none")
        do_clean = Confirm.ask("Clean Bazel cache before build?", default=False)
        do_ak3 = Confirm.ask("Package into AnyKernel3 ZIP afterwards?", default=True)

        res = build_kernel(config, preset, lto=lto_choice, clean=do_clean)
        if res["success"]:
            print_build_success(res["duration"], res["artifacts"])
            if do_ak3:
                ak_res = package_anykernel(config, preset)
                print_package_success(ak_res["zip_path"], ak_res["size"], ak_res["sha256"], ak_res["duration"])
    elif choice == "4":
        preset = get_preset(config, config.default_kernel)
        kernel_path = preset.get_abs_path(config.workspace_root)
        run_bazel_clean(kernel_path)
    elif choice == "5":
        info.callback(kernel=None)


if __name__ == "__main__":
    main()
