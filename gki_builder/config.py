from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class KernelPreset:
    name: str
    path: str
    build_system: str = "kleaf"
    default_target: str = "//common:kernel_aarch64_dist"
    default_lto: str = "none"
    destdir: str = "out/dist"
    image_relpath: str = "out/dist/Image"
    kernel_string: Optional[str] = None
    boot_template: Optional[str] = None

    def get_abs_path(self, workspace_root: Path = WORKSPACE_ROOT) -> Path:
        return workspace_root / self.path

    def get_image_abs_path(self, workspace_root: Path = WORKSPACE_ROOT) -> Path:
        return self.get_abs_path(workspace_root) / self.image_relpath

    def get_boot_template_abs_path(self, workspace_root: Path = WORKSPACE_ROOT) -> Optional[Path]:
        if self.boot_template:
            candidate = workspace_root / self.boot_template
            if candidate.exists():
                return candidate
        # KMI-based auto-detection in tools/boot_templates/
        kmi_candidates = [
            workspace_root / "tools" / "boot_templates" / self.path / "boot.img",
            workspace_root / "tools" / "boot_templates" / self.name.replace(" ", "_") / "boot.img",
            workspace_root / "tools" / "boot_templates" / "boot.img",
        ]
        for cand in kmi_candidates:
            if cand.exists():
                return cand
        return None


@dataclass
class AnyKernelConfig:
    enabled: bool = True
    template_dir: str = "tools/AnyKernel3"
    output_dir: str = "out/release/anykernel"
    zip_name_template: str = "AnyKernel3-{branch}-{timestamp}.zip"
    auto_patch_devicecheck: bool = True

    def get_template_abs_path(self, workspace_root: Path = WORKSPACE_ROOT) -> Path:
        return workspace_root / self.template_dir

    def get_output_abs_path(self, workspace_root: Path = WORKSPACE_ROOT) -> Path:
        return workspace_root / self.output_dir


@dataclass
class BootImageConfig:
    enabled: bool = True
    template_dir: str = "tools/boot_templates"
    output_dir: str = "out/release/boot"
    kptools_path: str = "tools/kptools/kptools"
    img_name_template: str = "boot_{branch}_{timestamp}.img"

    def get_output_abs_path(self, workspace_root: Path = WORKSPACE_ROOT) -> Path:
        return workspace_root / self.output_dir

    def get_template_dir_abs_path(self, workspace_root: Path = WORKSPACE_ROOT) -> Path:
        return workspace_root / self.template_dir

    def get_kptools_abs_path(self, workspace_root: Path = WORKSPACE_ROOT) -> Path:
        return workspace_root / self.kptools_path


@dataclass
class BuildConfig:
    workspace_root: Path = WORKSPACE_ROOT
    default_kernel: str = "android16-6.12"
    kernels: Dict[str, KernelPreset] = field(default_factory=dict)
    anykernel3: AnyKernelConfig = field(default_factory=AnyKernelConfig)
    boot_image: BootImageConfig = field(default_factory=BootImageConfig)

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "BuildConfig":
        if config_path is None:
            config_path = WORKSPACE_ROOT / "build_config.yaml"

        raw: Dict[str, Any] = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
            except Exception:
                pass

        default_kernel = raw.get("default_kernel", "android16-6.12")

        # Parse kernels
        kernels_data = raw.get("kernels", {})
        kernels: Dict[str, KernelPreset] = {}

        for k, v in kernels_data.items():
            if isinstance(v, dict):
                kernels[k] = KernelPreset(
                    name=v.get("name", k),
                    path=v.get("path", k),
                    build_system=v.get("build_system", "kleaf"),
                    default_target=v.get("default_target", "//common:kernel_aarch64_dist"),
                    default_lto=v.get("default_lto", "none"),
                    destdir=v.get("destdir", "out/dist"),
                    image_relpath=v.get("image_relpath", "out/dist/Image"),
                    kernel_string=v.get("kernel_string"),
                    boot_template=v.get("boot_template"),
                )

        if not kernels:
            kernels["android16-6.12"] = KernelPreset(
                name="Android 16 (Linux 6.12 GKI)",
                path="android16-6.12",
                build_system="kleaf",
                default_target="//common:kernel_aarch64_dist",
                default_lto="none",
                destdir="out/dist",
                image_relpath="out/dist/Image",
                boot_template="tools/boot_templates/android16-6.12/boot.img",
            )

        # Parse anykernel
        ak_data = raw.get("anykernel3", {})
        ak_config = AnyKernelConfig(
            enabled=ak_data.get("enabled", True),
            template_dir=ak_data.get("template_dir", "tools/AnyKernel3"),
            output_dir=ak_data.get("output_dir", "out/release/anykernel"),
            zip_name_template=ak_data.get("zip_name_template", "AnyKernel3-{branch}-{timestamp}.zip"),
            auto_patch_devicecheck=ak_data.get("auto_patch_devicecheck", True),
        )

        # Parse boot_image
        bi_data = raw.get("boot_image", {})
        bi_config = BootImageConfig(
            enabled=bi_data.get("enabled", True),
            template_dir=bi_data.get("template_dir", "tools/boot_templates"),
            output_dir=bi_data.get("output_dir", "out/release/boot"),
            kptools_path=bi_data.get("kptools_path", "tools/kptools/kptools"),
            img_name_template=bi_data.get("img_name_template", "boot_{branch}_{timestamp}.img"),
        )

        return cls(
            workspace_root=WORKSPACE_ROOT,
            default_kernel=default_kernel,
            kernels=kernels,
            anykernel3=ak_config,
            boot_image=bi_config,
        )

