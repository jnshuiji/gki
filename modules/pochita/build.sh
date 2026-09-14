#!/usr/bin/env python3
import os
import sys
import zipfile
from pathlib import Path

def main():
    module_dir = Path(__file__).resolve().parent
    root_dir = module_dir.parent.parent
    out_dir = root_dir / "out" / "release" / "modules"
    out_dir.mkdir(parents=True, exist_ok=True)

    version = "1.0.0"
    prop_file = module_dir / "module.prop"
    if prop_file.exists():
        for line in prop_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("version="):
                version = line.split("=", 1)[1].strip()
                break

    zip_name = f"pochita-{version}.zip"
    zip_path = out_dir / zip_name

    excluded_names = {".git", ".gitignore", ".DS_Store", "build.sh", zip_name}

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(module_dir):
            dirs[:] = [d for d in dirs if d not in excluded_names and not d.startswith(".")]
            for file in files:
                if file in excluded_names or file.endswith(".zip"):
                    continue
                file_path = Path(root) / file
                rel_path = file_path.relative_to(module_dir)
                zf.write(file_path, arcname=str(rel_path))

    print(f"Module package generated: {zip_path}")

if __name__ == "__main__":
    main()
