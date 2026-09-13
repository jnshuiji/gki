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


def print_package_results(res: Dict[str, Any]):
    kmi = res.get("kmi", "")
    auto_selected = res.get("auto_selected", False)
    has_boot_template = res.get("has_boot_template", False)

    content = Text()
    title = "[bold green]Packaging Complete[/bold green]"
    border_style = "green"

    content.append("✨ Kernel Artifacts Packaged Successfully!\n", style="bold green")

    if auto_selected:
        if has_boot_template:
            content.append(f"💡 Auto-selected [Fastboot Boot Image] because OEM template was detected for KMI ({kmi})\n\n", style="dim cyan")
        else:
            content.append(f"💡 Auto-selected [AnyKernel3 ZIP] because no OEM boot template was found for KMI ({kmi})\n\n", style="dim cyan")
    else:
        content.append("\n")

    boot_res = res.get("boot_image")
    if boot_res and not boot_res.get("error"):
        boot_path = boot_res["boot_path"]
        boot_size = boot_res["size"]
        content.append("⚡ [Fastboot Direct Flash (OEM Boot Image)]\n", style="bold yellow")
        content.append(f"  • File    : {boot_path}\n", style="bold white")
        content.append(f"  • Size    : {boot_size}  |  SHA256: {boot_res['sha256'][:16]}...\n", style="dim")
        content.append(f"  • Template: {boot_res.get('template_used', 'OEM Template')}\n", style="dim")
        content.append(f"  • Flash   : fastboot flash boot {boot_path}\n\n", style="bold green")

    ak_res = res.get("anykernel")
    if ak_res and not ak_res.get("error"):
        zip_path = ak_res["zip_path"]
        zip_size = ak_res["size"]
        content.append("📦 [Recovery / KernelSU / APatch (AnyKernel3 ZIP)]\n", style="bold yellow")
        content.append(f"  • File    : {zip_path}\n", style="bold white")
        content.append(f"  • Size    : {zip_size}  |  SHA256: {ak_res['sha256'][:16]}...\n", style="dim")
        content.append("  • Flash   : Install directly in KernelSU / APatch Manager or TWRP/Recovery\n\n", style="cyan")

    panel = Panel(content, title=title, border_style=border_style)
    console.print(panel)


def print_package_success(
    zip_path: Optional[str] = None,
    size: Optional[str] = None,
    sha256: Optional[str] = None,
    duration: float = 0.0,
    boot_image: Optional[Dict[str, Any]] = None,
):
    ak_dict = None
    if zip_path:
        ak_dict = {
            "zip_path": zip_path,
            "size": size,
            "sha256": sha256 or "",
            "duration": duration,
        }
    print_package_results({
        "boot_image": boot_image,
        "anykernel": ak_dict,
    })


def print_build_success(duration: float, artifacts: Dict[str, Optional[Dict[str, str]]]):
    content = Text()
    content.append(f"🚀 Kernel Build Completed in {duration:.1f}s!\n\n", style="bold green")
    image_info = artifacts.get("Image")
    if image_info:
        content.append(f"Image Size: {image_info['size']}\n", style="bold yellow")
        content.append(f"Location: {image_info['path']}\n", style="dim")
    panel = Panel(content, title="[bold green]Build Succeeded[/bold green]", border_style="green")
    console.print(panel)
