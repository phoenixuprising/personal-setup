#!/usr/bin/env python3
"""Collect non-secret user data into userdata/ for USB transfer.

Run this on the SOURCE machine before copying the repo to a USB drive.
The userdata/ directory is gitignored and contains large non-secret files
(wallpapers, etc.) that setup.py will install on the target machine.

Collected:
  - Wallpapers (~/Pictures/Wallpapers/)
"""

import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
USERDATA_DIR = SCRIPT_DIR / "userdata"

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def log_step(msg):
    print(f"{GREEN}▶ {msg}{RESET}")


def log_warn(msg):
    print(f"{YELLOW}⚠ {msg}{RESET}")


def main():
    print()
    print("Collecting user data for USB transfer...")
    print()

    USERDATA_DIR.mkdir(exist_ok=True)

    collected = 0

    # ─── Wallpapers ───
    wallpapers_src = Path("~/Pictures/Wallpapers").expanduser()
    if wallpapers_src.is_dir():
        wallpapers_dest = USERDATA_DIR / "wallpapers"
        wallpapers_dest.mkdir(parents=True, exist_ok=True)
        wp_count = 0
        for img in wallpapers_src.iterdir():
            if img.is_file():
                shutil.copy2(img, wallpapers_dest / img.name)
                wp_count += 1
        if wp_count:
            log_step(f"Collected {wp_count} wallpaper(s) → userdata/wallpapers/")
            collected += 1
    else:
        log_warn("No ~/Pictures/Wallpapers/ directory found — skipping wallpapers.")

    print()
    if collected:
        log_step(f"Done — {collected} item(s) collected in userdata/")
        print()
        print("  Next steps:")
        print("    1. Copy this repo (with userdata/) to your USB drive")
        print("    2. On the target machine, run: python3 setup.py")
    else:
        log_warn("No user data found to collect.")

    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        log_warn("Interrupted.")
        sys.exit(1)
