#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kernel LSP (clangd & rust-analyzer) Configuration Generator & Synchronizer.

This script ensures both C and Rust language servers (LSP) have complete,
accurate cross-reference databases for the Linux kernel and custom modules.
"""

import os
import sys
import json
import subprocess
from pathlib import Path

WORKSPACE_ROOT = Path("/home/pochita/gki")
AOSP_ROOT = WORKSPACE_ROOT / "android16-6.12"
COMMON_SRC = AOSP_ROOT / "common"
PREBUILTS_ROOT = AOSP_ROOT / "prebuilts"

CLANG_BIN = PREBUILTS_ROOT / "clang/host/linux-x86/clang-r536225/bin/clangd"
RUST_SYSROOT = PREBUILTS_ROOT / "rust/linux-x86/1.82.0"
RUST_SRC = RUST_SYSROOT / "lib/rustlib/src/rust/library"
RUST_ANALYZER_BIN = RUST_SYSROOT / "bin/rust-analyzer"

COMPILE_COMMANDS_PATH = WORKSPACE_ROOT / "compile_commands.json"
RUST_PROJECT_PATH = WORKSPACE_ROOT / "rust-project.json"

# Common output dir from Bazel / Kleaf
KERNEL_OUT_DIR = AOSP_ROOT / "out/bazel/compdb/common"


def check_prerequisites():
    """Verify essential directories and tools exist."""
    print("🔍 [LSP Setup] Checking prerequisites...")
    if not AOSP_ROOT.is_dir():
        print(f"❌ Error: AOSP tree not found at {AOSP_ROOT}")
        sys.exit(1)
    if not CLANG_BIN.is_file():
        print(f"❌ Error: clangd not found at {CLANG_BIN}")
        sys.exit(1)
    if not RUST_ANALYZER_BIN.is_file():
        print(f"❌ Error: rust-analyzer not found at {RUST_ANALYZER_BIN}")
        sys.exit(1)
    print("✅ Prebuilt clangd and rust-analyzer verified.")

    # Ensure symlink android16-6.12/modules -> ../modules
    modules_link = AOSP_ROOT / "modules"
    if not modules_link.exists() and not modules_link.is_symlink():
        try:
            modules_link.symlink_to("../modules")
            print("🔗 Created symlink: android16-6.12/modules -> ../modules")
        except Exception as e:
            print(f"⚠️ Warning: Failed to create modules symlink: {e}")


def sync_compile_commands():
    """Ensure compile_commands.json contains custom C files in modules/."""
    print("\n📦 [C/C++ LSP] Synchronizing compile_commands.json...")
    if not COMPILE_COMMANDS_PATH.is_file():
        print("⚠️ compile_commands.json does not exist. Generating via Kleaf...")
        cmd = [
            str(AOSP_ROOT / "tools/bazel"),
            "run",
            "//common:kernel_aarch64_compile_commands",
            "--",
            str(COMPILE_COMMANDS_PATH)
        ]
        subprocess.check_call(cmd, cwd=str(AOSP_ROOT))

    with open(COMPILE_COMMANDS_PATH, "r", encoding="utf-8") as f:
        cc_entries = json.load(f)

    # Find template command for drivers
    template_cmd = None
    for entry in cc_entries:
        if "drivers/input/evdev.c" in entry.get("file", ""):
            template_cmd = entry.get("command", "")
            break
    if not template_cmd and len(cc_entries) > 0:
        template_cmd = cc_entries[0].get("command", "")

    # Scan for custom C files under modules/
    existing_files = {entry.get("file") for entry in cc_entries}
    modules_dir = WORKSPACE_ROOT / "modules"
    added_count = 0

    if modules_dir.is_dir() and template_cmd:
        for c_file in modules_dir.rglob("*.c"):
            abs_c_file = str(c_file.resolve())
            if abs_c_file not in existing_files:
                module_name = c_file.parent.parent.name
                obj_file = str(c_file.with_suffix(".o"))
                custom_cmd = template_cmd
                # Replace input file and output object
                custom_cmd = custom_cmd.replace("/home/pochita/gki/android16-6.12/common/drivers/input/evdev.c", abs_c_file)
                custom_cmd = custom_cmd.replace("drivers/input/evdev.o", obj_file)
                custom_cmd = custom_cmd.replace('-DKBUILD_MODNAME="evdev"', f'-DKBUILD_MODNAME="{module_name}"')
                custom_cmd += f" -I{c_file.parent}"

                cc_entries.append({
                    "directory": str(KERNEL_OUT_DIR),
                    "file": abs_c_file,
                    "command": custom_cmd
                })
                existing_files.add(abs_c_file)
                added_count += 1
                print(f"  + Added module C file: {c_file.relative_to(WORKSPACE_ROOT)}")

    if added_count > 0:
        with open(COMPILE_COMMANDS_PATH, "w", encoding="utf-8") as f:
            json.dump(cc_entries, f, indent=2)
        print(f"✅ compile_commands.json updated with {added_count} module file(s).")
    else:
        print(f"✅ compile_commands.json is up-to-date ({len(cc_entries)} files indexed).")


def sync_rust_project():
    """Generate and synchronize rust-project.json for rust-analyzer."""
    print("\n🦀 [Rust LSP] Synchronizing rust-project.json...")
    gen_script = COMMON_SRC / "scripts/generate_rust_analyzer.py"
    if not gen_script.is_file():
        print(f"❌ Error: {gen_script} not found")
        sys.exit(1)

    # Determine stable objtree with rustc_cfg
    candidate_objtrees = [
        AOSP_ROOT / "out/bazel/output_user_root/4659b195ad32548d32c7b26ad7e90588/execroot/_main/bazel-out/k8-fastbuild/bin/common/kernel_aarch64_config/out_dir",
        AOSP_ROOT / "out/bazel/compdb/common"
    ]
    objtree = None
    for cand in candidate_objtrees:
        if (cand / "include/generated/rustc_cfg").is_file():
            objtree = cand
            break

    if not objtree:
        # Fallback to creating a dummy rustc_cfg if not present
        dummy_dir = WORKSPACE_ROOT / "out/lsp_objtree"
        (dummy_dir / "include/generated").mkdir(parents=True, exist_ok=True)
        dummy_cfg = dummy_dir / "include/generated/rustc_cfg"
        if not dummy_cfg.is_file():
            dummy_cfg.write_text("CONFIG_RUST=y\nCONFIG_ARM64=y\n", encoding="utf-8")
        objtree = dummy_dir

    # Ensure proc-macro dylib (libmacros.so) is compiled for rust-analyzer
    lsp_rust_dir = WORKSPACE_ROOT / "out/lsp/rust"
    lsp_rust_dir.mkdir(parents=True, exist_ok=True)
    stable_libmacros = lsp_rust_dir / "libmacros.so"
    macros_src = COMMON_SRC / "rust/macros/lib.rs"

    if macros_src.is_file():
        if not stable_libmacros.is_file() or stable_libmacros.stat().st_mtime < macros_src.stat().st_mtime:
            print("  🔨 Compiling host proc-macro dylib (libmacros.so) for rust-analyzer...")
            build_cmd = [
                str(RUST_SYSROOT / "bin/rustc"),
                "--crate-type", "proc-macro",
                "--extern", "proc_macro",
                "--edition=2021",
                str(macros_src),
                "-o", str(stable_libmacros)
            ]
            try:
                subprocess.check_call(build_cmd)
                print("  ✅ libmacros.so compiled successfully.")
            except Exception as e:
                print(f"  ⚠️ Warning: Failed to compile libmacros.so: {e}")

    # Mirror libmacros.so to objtree/rust/libmacros.so
    objtree_rust_dir = objtree / "rust"
    objtree_rust_dir.mkdir(parents=True, exist_ok=True)
    objtree_libmacros = objtree_rust_dir / "libmacros.so"
    if stable_libmacros.is_file() and not objtree_libmacros.is_file():
        try:
            import shutil
            shutil.copy2(str(stable_libmacros), str(objtree_libmacros))
        except Exception as e:
            print(f"  ⚠️ Warning: Could not mirror libmacros.so to objtree: {e}")

    # Run kernel generate_rust_analyzer.py
    cmd = [
        sys.executable,
        str(gen_script),
        "2021",
        str(COMMON_SRC),
        str(objtree),
        str(RUST_SYSROOT),
        str(RUST_SRC)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ generate_rust_analyzer.py failed:\n{result.stderr}")
        sys.exit(1)

    rust_project = json.loads(result.stdout)

    # Point macros crate to stable libmacros.so if available
    for crate in rust_project.get("crates", []):
        if crate.get("display_name") == "macros":
            if stable_libmacros.is_file():
                crate["proc_macro_dylib_path"] = str(stable_libmacros)

    # Locate index of 'core' and 'kernel' crates
    core_idx = None
    kernel_idx = None
    for idx, crate in enumerate(rust_project.get("crates", [])):
        name = crate.get("display_name")
        if name == "core":
            core_idx = idx
        elif name == "kernel":
            kernel_idx = idx

    if core_idx is None or kernel_idx is None:
        print("⚠️ Warning: core or kernel crate not found in rust-project graph.")

    # Scan and link custom modules under modules/
    modules_dir = WORKSPACE_ROOT / "modules"
    existing_crate_names = {c.get("display_name") for c in rust_project.get("crates", [])}

    if modules_dir.is_dir():
        for rs_file in modules_dir.rglob("main.rs"):
            module_name = rs_file.parent.parent.name
            if module_name not in existing_crate_names:
                deps = []
                if core_idx is not None:
                    deps.append({"crate": core_idx, "name": "core"})
                if kernel_idx is not None:
                    deps.append({"crate": kernel_idx, "name": "kernel"})

                cfg = rust_project["crates"][kernel_idx]["cfg"] if kernel_idx is not None else []
                module_crate = {
                    "display_name": module_name,
                    "root_module": str(rs_file.resolve()),
                    "is_workspace_member": True,
                    "is_proc_macro": False,
                    "edition": "2021",
                    "deps": deps,
                    "cfg": cfg,
                    "env": {
                        "RUST_MODFILE": module_name
                    }
                }
                rust_project["crates"].append(module_crate)
                existing_crate_names.add(module_name)
                print(f"  + Added module Rust crate: {module_name} ({rs_file.relative_to(WORKSPACE_ROOT)})")

    with open(RUST_PROJECT_PATH, "w", encoding="utf-8") as f:
        json.dump(rust_project, f, indent=4)
    print(f"✅ rust-project.json updated ({len(rust_project['crates'])} crates linked).")


def main():
    check_prerequisites()
    sync_compile_commands()
    sync_rust_project()
    print("\n🎉 [All Done] LSP metadata synchronized successfully!")
    print("👉 Reload VS Code (Ctrl+Shift+P -> 'Developer: Reload Window') to activate.")


if __name__ == "__main__":
    main()
