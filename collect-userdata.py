#!/usr/bin/env python3
"""Collect non-secret user data into userdata/ for USB transfer.

Run this on the SOURCE machine before copying the repo to a USB drive.
The userdata/ directory is gitignored and contains large non-secret files
(wallpapers, etc.) that setup.py will install on the target machine.

Collected:
  - Wallpapers (~/Pictures/Wallpapers/)
"""

import argparse
import shutil
import sys
from pathlib import Path

from tool_runtime import ToolRuntime

SCRIPT_DIR = Path(__file__).parent.resolve()
USERDATA_DIR = SCRIPT_DIR / "userdata"


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for userdata collection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log-format",
        choices=("text", "json"),
        default="text",
        help="Emit human-readable or JSON logs to stderr.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable summary to stdout.",
    )
    return parser


def main() -> int:
    """Collect non-secret user data into the repo-local userdata directory."""
    args = build_parser().parse_args()
    runtime = ToolRuntime("collect-userdata", log_format=args.log_format, json_output=args.json)
    runtime.info("Collecting user data for USB transfer")
    # TODO: Move userdata collection to an inventory file so sources stay declarative.

    USERDATA_DIR.mkdir(exist_ok=True)

    collected = 0
    wallpaper_count = 0

    # ─── Wallpapers ───
    wallpapers_src = Path("~/Pictures/Wallpapers").expanduser()
    if wallpapers_src.is_dir():
        wallpapers_dest = USERDATA_DIR / "wallpapers"
        wallpapers_dest.mkdir(parents=True, exist_ok=True)
        for img in wallpapers_src.iterdir():
            if img.is_file():
                shutil.copy2(img, wallpapers_dest / img.name)
                wallpaper_count += 1
        if wallpaper_count:
            runtime.info("Collected wallpapers", count=wallpaper_count, destination="userdata/wallpapers")
            runtime.record_event(
                "collect-wallpapers",
                count=wallpaper_count,
                destination=str(wallpapers_dest),
            )
            collected += 1
    else:
        runtime.warn("No ~/Pictures/Wallpapers/ directory found — skipping wallpapers")

    if collected and not args.json:
        print()
        print(f"Done — {collected} item(s) collected in userdata/")
        print("  Next steps:")
        print("    1. Copy this repo (with userdata/) to your USB drive")
        print("    2. On the target machine, run: uv run python setup.py")
    else:
        runtime.warn("No user data found to collect")

    runtime.emit_summary(
        ok=True,
        collected_item_count=collected,
        wallpaper_count=wallpaper_count,
        output_dir=str(USERDATA_DIR),
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        ToolRuntime("collect-userdata").warn("Interrupted")
        sys.exit(1)
