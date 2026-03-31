#!/usr/bin/env python3
"""Collect secrets and user data from the current machine into secrets/ for USB transfer.

Run this on the SOURCE machine before copying the repo to a USB drive.
The secrets/ directory is gitignored and contains credentials and user data
that setup.py will install on the target machine.

Collected:
  - Claude Code credentials (~/.claude/.credentials.json)
  - Git config (~/.gitconfig)
  - SSH config (~/.ssh/config, ~/.ssh/known_hosts)
  - SSH public key from 1Password (for authorized_keys on target)
  - 1Password account metadata
  - Wallpapers (~/Pictures/Wallpapers/)
"""

import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
SECRETS_DIR = SCRIPT_DIR / "secrets"

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def log_step(msg):
    print(f"{GREEN}▶ {msg}{RESET}")


def log_warn(msg):
    print(f"{YELLOW}⚠ {msg}{RESET}")


def log_error(msg):
    print(f"{RED}✗ {msg}{RESET}")


def collect_file(src, dest_name, mode=0o600, dest_subdir=None):
    """Copy a file into secrets/, preserving nothing about the original path."""
    src = Path(src).expanduser()
    if not src.exists():
        log_warn(f"Not found: {src}")
        return False

    dest_dir = SECRETS_DIR / dest_subdir if dest_subdir else SECRETS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / dest_name

    shutil.copy2(src, dest)
    dest.chmod(mode)
    log_step(f"Collected {src} → {dest.relative_to(SCRIPT_DIR)}")
    return True


def main():
    print()
    print("Collecting secrets for USB transfer...")
    print()

    SECRETS_DIR.mkdir(exist_ok=True)

    collected = 0

    # ─── Claude Code credentials ───
    if collect_file("~/.claude/.credentials.json", ".credentials.json"):
        collected += 1

    # ─── Git config ───
    if collect_file("~/.gitconfig", ".gitconfig", mode=0o644):
        collected += 1

    # ─── SSH config + known hosts (no private keys — those live in 1Password) ───
    for name in ("config", "known_hosts"):
        if collect_file(f"~/.ssh/{name}", name, dest_subdir="ssh"):
            collected += 1

    # ─── 1Password: account metadata + SSH public key ───
    if shutil.which("op"):
        try:
            result = subprocess.run(
                ["op", "account", "list", "--format=json"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                accounts_file = SECRETS_DIR / "op-accounts.json"
                accounts_file.write_text(result.stdout)
                accounts_file.chmod(0o600)
                log_step(f"Collected 1Password account list → {accounts_file.relative_to(SCRIPT_DIR)}")
                collected += 1
            else:
                log_warn("1Password CLI not signed in — skipping account export.")
        except subprocess.TimeoutExpired:
            log_warn("1Password CLI timed out — skipping.")

        # Extract SSH public key for authorized_keys on the target
        try:
            result = subprocess.run(
                ["op", "item", "get", "Personal - SSH Key", "--fields", "public key"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                ssh_dir = SECRETS_DIR / "ssh"
                ssh_dir.mkdir(parents=True, exist_ok=True)
                pubkey_file = ssh_dir / "authorized_keys"
                pubkey_file.write_text(result.stdout.strip() + "\n")
                pubkey_file.chmod(0o644)
                log_step(f"Collected SSH public key → {pubkey_file.relative_to(SCRIPT_DIR)}")
                collected += 1
            else:
                log_warn("Could not extract SSH public key from 1Password.")
        except subprocess.TimeoutExpired:
            log_warn("1Password CLI timed out extracting SSH key.")

    # ─── Wallpapers ───
    wallpapers_src = Path("~/Pictures/Wallpapers").expanduser()
    if wallpapers_src.is_dir():
        wallpapers_dest = SECRETS_DIR / "wallpapers"
        wallpapers_dest.mkdir(parents=True, exist_ok=True)
        wp_count = 0
        for img in wallpapers_src.iterdir():
            if img.is_file():
                shutil.copy2(img, wallpapers_dest / img.name)
                wp_count += 1
        if wp_count:
            log_step(f"Collected {wp_count} wallpaper(s) → secrets/wallpapers/")
            collected += 1
    else:
        log_warn("No ~/Pictures/Wallpapers/ directory found — skipping wallpapers.")

    # ─── Gitignore secrets/ ───
    gitignore = SCRIPT_DIR / ".gitignore"
    gitignore_text = gitignore.read_text() if gitignore.exists() else ""
    if "secrets/" not in gitignore_text:
        with open(gitignore, "a") as f:
            f.write("\nsecrets/\n")
        log_step("Added secrets/ to .gitignore")

    print()
    if collected:
        log_step(f"Done — {collected} item(s) collected in secrets/")
        print()
        print("  Next steps:")
        print("    1. Copy this repo (with secrets/) to your USB drive")
        print("    2. On the target machine, run: python3 setup.py")
        print("    3. Step 6 will install the secrets automatically")
    else:
        log_warn("No secrets found to collect.")

    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        log_warn("Interrupted.")
        sys.exit(1)
