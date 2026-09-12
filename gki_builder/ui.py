from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


def print_banner():
    banner_text = Text()
    banner_text.append("🤖 GKI Kernel Build & Packaging Suite\n", style="bold cyan")
    banner_text.append("Fast, automated, and streamlined workflow for Android Kernels", style="dim white")
    panel = Panel(banner_text, border_style="cyan", padding=(1, 2))
    console.print(panel)


def print_system_status(sys_info: Dict[str, str], trees: List[Dict[str, str]]):
    table = Table(title="💻 System Resources & Environment", border_style="blue", show_header=True)
    table.add_column("Item", style="bold yellow")
    table.add_column("Value", style="green")

    table.add_row("CPU Logical Cores", sys_info.get("cpu_count", "N/A"))
    table.add_row("RAM (Total / Available)", f"{sys_info.get('ram_total')} / {sys_info.get('ram_available')}")
    table.add_row("Disk (Free / Total)", f"{sys_info.get('disk_free')} / {sys_info.get('disk_total')}")

    console.print(table)

    tree_table = Table(title="🌳 Detected Kernel Source Trees", border_style="magenta", show_header=True)
    tree_table.add_column("Name", style="bold cyan")
    tree_table.add_column("Build Engine", style="white")
    tree_table.add_column("Path", style="dim")

    if trees:
        for t in trees:
            tree_table.add_row(t["name"], t["type"], t["path"])
    else:
        tree_table.add_row("None", "-", "-")

    console.print(tree_table)


def print_artifacts(artifacts: Dict[str, Optional[Dict[str, str]]]):
    table = Table(title="📦 Dist Artifacts Status", border_style="green", show_header=True)
    table.add_column("Artifact", style="bold cyan")
    table.add_column("Status", style="bold")
    table.add_column("Size", style="yellow")
    table.add_column("Last Modified", style="dim")

    for name, data in artifacts.items():
        if data:
            table.add_row(name, "[green]EXISTS[/green]", data["size"], data["mtime"])
        else:
            table.add_row(name, "[red]NOT BUILT[/red]", "-", "-")

    console.print(table)


def print_package_success(
    zip_path: str,
    size: str,
    sha256: str,
    duration: float,
    folkpatch: bool = False,
    superkey: Optional[str] = None,
):
    content = Text()
    title = "[bold magenta]Packaging Complete (FolkPatch Injected)[/bold magenta]" if folkpatch else "[bold green]Packaging Complete[/bold green]"
    border_style = "magenta" if folkpatch else "green"

    if folkpatch:
        content.append("🦊 AnyKernel3 Flashable ZIP Created with FolkPatch!\n\n", style="bold magenta")
    else:
        content.append("✨ AnyKernel3 Flashable ZIP Created Successfully!\n\n", style="bold green")

    content.append(f"📁 Output File : {zip_path}\n", style="bold white")
    content.append(f"📊 File Size   : {size}\n", style="yellow")
    content.append(f"⏱️  Duration    : {duration:.2f}s\n", style="cyan")
    if folkpatch:
        masked_key = superkey[:2] + "*" * (len(superkey) - 2) if superkey and len(superkey) > 2 else "****"
        content.append(f"🛡️  FolkPatch   : Injected (SuperKey: {masked_key})\n", style="bold cyan")
    content.append(f"🔑 SHA256     : {sha256}\n", style="dim magenta")
    panel = Panel(content, title=title, border_style=border_style)
    console.print(panel)


def print_build_success(duration: float, artifacts: Dict[str, Optional[Dict[str, str]]]):
    content = Text()
    content.append(f"🚀 Kernel Build Completed in {duration:.1f}s!\n\n", style="bold green")
    image_info = artifacts.get("Image")
    if image_info:
        content.append(f"Image Size: {image_info['size']}\n", style="bold yellow")
        content.append(f"Location: {image_info['path']}\n", style="dim")
    panel = Panel(content, title="[bold green]Build Succeeded[/bold green]", border_style="green")
    console.print(panel)
