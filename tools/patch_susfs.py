#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SuSFS 2.3.0 Patch Automation Tool for Android 16-6.12 GKI & KernelSU v3.3.0.

Usage:
  python3 tools/patch_susfs.py apply   # Check, copy source, and apply patches
  python3 tools/patch_susfs.py revert  # Revert patches and clean injected files
  python3 tools/patch_susfs.py status  # Show current SuSFS patch status
  python3 tools/patch_susfs.py check   # Dry-run test patch compatibility
"""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from gki_builder.patcher import SusfsPatcher
except ImportError as e:
    print(f"Error importing gki_builder: {e}", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Automated SuSFS 2.3.0 Patcher for KernelSU v3.3.0 & Android 16-6.12 GKI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=["apply", "revert", "status", "check", "fetch"],
        default="status",
        help="Action to perform (default: status)",
    )
    parser.add_argument("--apply", dest="flag_apply", action="store_true", help="Apply SuSFS patches")
    parser.add_argument("--revert", dest="flag_revert", action="store_true", help="Revert SuSFS patches")
    parser.add_argument("--status", dest="flag_status", action="store_true", help="Show SuSFS status")
    parser.add_argument("--check", dest="flag_check", action="store_true", help="Dry-run patch check")
    parser.add_argument("--fetch", dest="flag_fetch", action="store_true", help="Download/refresh patch cache from GitLab")

    args = parser.parse_args()

    # Determine action priority: flags override positional if given
    action = args.action
    if args.flag_apply:
        action = "apply"
    elif args.flag_revert:
        action = "revert"
    elif args.flag_check:
        action = "check"
    elif args.flag_fetch:
        action = "fetch"
    elif args.flag_status:
        action = "status"

    patcher = SusfsPatcher(workspace_root=PROJECT_ROOT)

    if action == "status":
        patcher.print_status()
    elif action == "fetch":
        success = patcher.ensure_assets(force_download=True)
        sys.exit(0 if success else 1)
    elif action == "check":
        patcher.ensure_assets()
        can_apply, msg = patcher.check()
        if can_apply:
            print(f"✓ {msg}")
            sys.exit(0)
        else:
            print(f"❌ {msg}", file=sys.stderr)
            sys.exit(1)
    elif action == "apply":
        success = patcher.ensure_applied()
        sys.exit(0 if success else 1)
    elif action == "revert":
        success = patcher.ensure_reverted()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
