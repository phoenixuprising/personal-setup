#!/usr/bin/env python3
"""
CachyOS Desktop Setup Script — replicates phoenix's machine configuration.

Usage: Run each step individually or the whole script.
Requires: Fresh CachyOS install with Niri desktop selected.

Hardware-specific packages (GPU drivers, CPU microcode, kernel modules) are
auto-detected from hardware-info.toml. Run probe-hardware.py on the target first.
"""

import os
import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

from tool_runtime import ToolRuntime

SCRIPT_DIR = Path(__file__).parent.resolve()

# ─── Colors ──────────────────────────────────────────────────────────────────

ASSUME_YES = False
JSON_OUTPUT = False
STEP_RESULTS: list[dict[str, object]] = []
RUNTIME = ToolRuntime("setup")


def log_step(msg):
    RUNTIME.info(msg)


def log_warn(msg):
    RUNTIME.warn(msg)


def log_error(msg):
    RUNTIME.error(msg)


def confirm(prompt):
    """Ask for y/N confirmation."""
    if ASSUME_YES:
        print(f"{prompt}y")
        return True
    return input(prompt).strip().lower() in ("y", "yes")


def parse_args():
    """Parse CLI arguments for non-interactive setup execution."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="assume yes for confirmations and run all steps if no step is specified",
    )
    parser.add_argument(
        "step",
        nargs="?",
        help="step number to run, or 'all' to run every step",
    )
    parser.add_argument(
        "--log-format",
        choices=("text", "json"),
        default="text",
        help="Emit human-readable or JSON logs to stderr.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable run summary to stdout.",
    )
    return parser.parse_args()


def read_list(filename):
    """Read a text file with one entry per line, skipping blanks."""
    path = SCRIPT_DIR / filename
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


# ─── Hardware detection from TOML ────────────────────────────────────────────


def load_hardware():
    """Load hardware-info.toml, returns dict or None."""
    toml_path = SCRIPT_DIR / "hardware-info.toml"
    if not toml_path.exists():
        return None
    with open(toml_path, "rb") as f:
        return tomllib.load(f)


def get_hardware_packages(hw):
    """Extract hardware-specific package list from hardware data."""
    if hw is None:
        return []
    pkgs = set()
    mc = hw.get("cpu", {}).get("microcode")
    if mc:
        pkgs.add(mc)
    for gpu in hw.get("gpu", []):
        for p in gpu.get("driver_packages", []):
            pkgs.add(p)
        if gpu.get("hybrid"):
            for p in gpu.get("hybrid_packages", []):
                pkgs.add(p)
        if gpu.get("vendor") == "nvidia":
            pkgs.add("linux-cachyos-nvidia-open")
            pkgs.add("linux-cachyos-lts-nvidia-open")
    return sorted(pkgs)


def show_hardware_summary(hw):
    """Print a human-readable hardware summary."""
    cpu = hw.get("cpu", {})
    print(f"  CPU:    {cpu.get('model', '?')} ({cpu.get('cores', '?')} threads)")
    print(f"  RAM:    {hw.get('memory', {}).get('total_gb', '?')} GB")
    for gpu in hw.get("gpu", []):
        hybrid = " [hybrid]" if gpu.get("hybrid") else ""
        print(f"  GPU:    {gpu.get('vendor', '?')}{hybrid}  {gpu.get('description', '?')}")
    for d in hw.get("disk", []):
        print(
            f"  Disk:   {d.get('device', '?')} {d.get('size_gb', '?')}GB "
            f"{d.get('type', '?')} ({d.get('model', '?')})"
        )
    for n in hw.get("network", []):
        print(f"  Net:    {n.get('interface', '?')} ({n.get('type', '?')}, {n.get('driver', '?')})")
    mb = hw.get("motherboard", {})
    print(f"  Board:  {mb.get('vendor', '?')} {mb.get('name', '?')}")
    s = hw.get("system", {})
    print(f"  Type:   {s.get('chassis', '?')} / {s.get('firmware', '?')}")


# ─── Step 1: Install native (pacman) packages ───────────────────────────────


def step_install_native(hw):
    log_step("Installing native packages via pacman...")
    pkgs = read_list("packages-native.txt")
    if not pkgs:
        log_error("No packages found in packages-native.txt")
        return

    hw_pkgs = get_hardware_packages(hw)
    if hw_pkgs:
        log_step("Detected hardware:")
        show_hardware_summary(hw)
        print()
        print("  Hardware packages to install:")
        for p in hw_pkgs:
            print(f"    {p}")
        print()
        pkgs = pkgs + hw_pkgs
    else:
        log_warn("No hardware-info.toml found — hardware packages will NOT be installed.")
        log_warn("Run probe-hardware.py on the target machine for driver auto-detection.")
        print()

    if not confirm(f"Install {len(pkgs)} packages ({len(hw_pkgs)} hardware-specific)? [y/N] "):
        log_warn("Skipped native package install.")
        return
    subprocess.run(["sudo", "pacman", "-S", "--needed"] + pkgs)


# ─── Step 2: Install AUR packages ───────────────────────────────────────────


def step_install_aur():
    log_step("Installing AUR packages via yay...")
    pkgs = read_list("packages-aur.txt")
    if not pkgs:
        log_error("No packages found in packages-aur.txt")
        return
    print(f"AUR packages: {' '.join(pkgs)}")
    if not confirm(f"Continue installing {len(pkgs)} AUR packages? [y/N] "):
        log_warn("Skipped AUR package install.")
        return
    subprocess.run(["yay", "-S", "--needed"] + pkgs)


# ─── Step 3: Enable system services ─────────────────────────────────────────


def step_enable_system_services():
    log_step("Enabling system services...")
    for svc in read_list("services-system.txt"):
        if svc.startswith("getty@"):
            continue
        print(f"  Enabling {svc}")
        subprocess.run(["sudo", "systemctl", "enable", svc])
    log_step("System services enabled.")


# ─── Step 4: Enable user services ───────────────────────────────────────────


def step_enable_user_services():
    log_step("Enabling user services...")
    for svc in read_list("services-user.txt"):
        print(f"  Enabling {svc}")
        subprocess.run(["systemctl", "--user", "enable", svc])
    log_step("User services enabled.")


# ─── Step 5: Install uv tools ───────────────────────────────────────────────


def read_uv_tool_specs():
    """Read uv-tools.txt and return installable package specs."""
    specs = []
    for line in read_list("uv-tools.txt"):
        if line.startswith("-"):
            continue
        specs.append(line.split()[0])
    return specs


def step_install_uv_tools():
    log_step("Installing uv tools...")
    if not shutil.which("uv"):
        log_error("uv not found — install it first (should be in native packages).")
        return
    # TODO: Move this inventory to a stricter machine-readable format once Ansible/Terraform consumers appear.
    for spec in read_uv_tool_specs():
        subprocess.run(["uv", "tool", "install", spec])
        RUNTIME.record_event("install-uv-tool", spec=spec)

    command_help_parser_repo = Path.home() / "Developement" / "command-help-parser"
    if command_help_parser_repo.is_dir():
        subprocess.run(["uv", "tool", "install", "--editable", str(command_help_parser_repo)])
        RUNTIME.record_event("install-uv-tool", spec=str(command_help_parser_repo), editable=True)
    else:
        log_warn(f"Skipping local uv tool install; repo not found at {command_help_parser_repo}")
    log_step("uv tools installed.")


# ─── Step 6: Install secrets ─────────────────────────────────────────────────


def _install_secret(src, dest, label, mode=0o600):
    """Copy a secret file to its destination, prompting on overwrite."""
    if not src.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        log_warn(f"{label} already exists at {dest}")
        if not confirm("Overwrite? [y/N] "):
            log_warn(f"Skipped {label}.")
            return
    shutil.copy2(src, dest)
    dest.chmod(mode)
    log_step(f"{label} installed.")


ENCRYPTED_FILE = SCRIPT_DIR / "secrets.age"
OP_ITEM_TITLE = "system-ai Secrets Key"


def _decrypt_secrets():
    """Decrypt secrets.age → secrets/ using identity from 1Password."""
    if not shutil.which("age"):
        log_error("age not found — install with: pacman -S age")
        return False
    if not shutil.which("op"):
        log_error("1Password CLI (op) not found.")
        return False

    # Retrieve identity from 1Password
    result = subprocess.run(
        ["op", "item", "get", OP_ITEM_TITLE, "--fields", "password", "--reveal"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0 or not result.stdout.strip():
        log_error(f"Could not retrieve '{OP_ITEM_TITLE}' from 1Password. Are you signed in?")
        return False

    identity = result.stdout.strip()

    # Write identity to temp file for age -d -i
    tmp_identity = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as f:
            f.write(identity + "\n")
            tmp_identity = Path(f.name)
        tmp_identity.chmod(0o600)

        # Decrypt to a temp tarball, then extract
        with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp_tar:
            tmp_tar_path = Path(tmp_tar.name)

        result = subprocess.run(
            ["age", "-d", "-i", str(tmp_identity), "-o", str(tmp_tar_path), str(ENCRYPTED_FILE)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log_error(f"age decryption failed: {result.stderr}")
            tmp_tar_path.unlink(missing_ok=True)
            return False

        with tarfile.open(tmp_tar_path) as tar:
            tar.extractall(path=SCRIPT_DIR)
        tmp_tar_path.unlink(missing_ok=True)

        log_step("Decrypted secrets.age → secrets/")
        return True
    finally:
        if tmp_identity:
            tmp_identity.unlink(missing_ok=True)


def step_install_secrets():
    log_step("Installing secrets...")
    secrets_dir = SCRIPT_DIR / "secrets"
    decrypted = False

    # Decrypt if needed
    if not secrets_dir.is_dir():
        if ENCRYPTED_FILE.exists():
            decrypted = _decrypt_secrets()
            if not decrypted:
                return
        else:
            log_warn("No secrets/ directory or secrets.age found — run collect-secrets.py on the source machine first.")
            return

    home = Path.home()

    # Claude Code credentials
    _install_secret(
        secrets_dir / ".credentials.json",
        home / ".claude" / ".credentials.json",
        "Claude credentials",
    )

    # Git config
    _install_secret(
        secrets_dir / ".gitconfig",
        home / ".gitconfig",
        "Git config",
        mode=0o644,
    )

    # SSH config + known hosts + authorized_keys
    ssh_dir = secrets_dir / "ssh"
    if ssh_dir.is_dir():
        for name in ("config", "known_hosts"):
            _install_secret(
                ssh_dir / name,
                home / ".ssh" / name,
                f"SSH {name}",
            )
        _install_secret(
            ssh_dir / "authorized_keys",
            home / ".ssh" / "authorized_keys",
            "SSH authorized_keys",
            mode=0o644,
        )

    # 1Password account metadata (informational)
    op_accounts = secrets_dir / "op-accounts.json"
    if op_accounts.exists():
        print("  1Password accounts available — sign in with: 1password --setup")

    # Wallpapers — from userdata/
    wallpapers_src = SCRIPT_DIR / "userdata" / "wallpapers"
    if wallpapers_src.is_dir():
        wallpapers_dest = home / "Pictures" / "Wallpapers"
        wallpapers_dest.mkdir(parents=True, exist_ok=True)
        count = 0
        for img in wallpapers_src.iterdir():
            if img.is_file():
                dest = wallpapers_dest / img.name
                shutil.copy2(img, dest)
                count += 1
        if count:
            log_step(f"Installed {count} wallpaper(s) to {wallpapers_dest}")
    else:
        log_warn("No userdata/wallpapers/ found — skipping wallpaper install.")

    # Configure sshd for pubkey-only access
    _configure_sshd()

    # Clean up decrypted secrets
    if decrypted:
        shutil.rmtree(secrets_dir)
        log_step("Cleaned up decrypted secrets/ directory.")

    log_step("Secrets installed.")


SSHD_DROP_IN = """\
# Hardened sshd config — pubkey only, no root, no password
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AuthenticationMethods publickey
"""


def _configure_sshd():
    """Install a hardened sshd drop-in and enable the service."""
    # TODO: Split this into per-platform SSH providers once Debian/macOS support is added.
    dropin_dir = Path("/etc/ssh/sshd_config.d")
    dropin = dropin_dir / "99-personal-setup.conf"

    if dropin.exists():
        log_warn(f"sshd drop-in already exists at {dropin}")
        if not confirm("Overwrite? [y/N] "):
            log_warn("Skipped sshd configuration.")
            return
    else:
        if not confirm("Configure sshd (pubkey-only, no root, no password)? [y/N] "):
            log_warn("Skipped sshd configuration.")
            return

    # Write drop-in config
    subprocess.run(
        ["sudo", "tee", str(dropin)],
        input=SSHD_DROP_IN, text=True, stdout=subprocess.DEVNULL,
    )
    log_step("sshd hardened config installed.")

    # Enable and start sshd
    subprocess.run(["sudo", "systemctl", "enable", "--now", "sshd"])
    log_step("sshd enabled and started.")


# ─── Step 7: Apply chezmoi dotfiles ──────────────────────────────────────────


def step_apply_chezmoi():
    log_step("Applying chezmoi dotfiles...")
    if not shutil.which("chezmoi"):
        log_error("chezmoi not found — install chezmoi-git from AUR first.")
        return

    chezmoi_src = SCRIPT_DIR / "chezmoi-source"
    if not chezmoi_src.is_dir():
        log_error("chezmoi-source/ directory not found in repo.")
        return

    chezmoi_dir = Path.home() / ".local" / "share" / "chezmoi"
    chezmoi_dir.parent.mkdir(parents=True, exist_ok=True)

    if chezmoi_dir.is_symlink():
        if chezmoi_dir.resolve() == chezmoi_src.resolve():
            log_step("Symlink already points to chezmoi-source — nothing to do.")
        else:
            log_warn(f"Symlink exists but points to {chezmoi_dir.resolve()}")
            if not confirm("Replace with link to this repo's chezmoi-source? [y/N] "):
                log_warn("Skipped chezmoi setup.")
                return
            chezmoi_dir.unlink()
            chezmoi_dir.symlink_to(chezmoi_src.resolve())
            log_step(f"Symlink updated: {chezmoi_dir} → {chezmoi_src.resolve()}")
    elif chezmoi_dir.is_dir():
        log_warn(f"Chezmoi source dir already exists at {chezmoi_dir} (not a symlink)")
        if not confirm("Replace with symlink to this repo's chezmoi-source? [y/N] "):
            log_warn("Skipped chezmoi setup.")
            return
        shutil.rmtree(chezmoi_dir)
        chezmoi_dir.symlink_to(chezmoi_src.resolve())
        log_step(f"Replaced with symlink: {chezmoi_dir} → {chezmoi_src.resolve()}")
    else:
        chezmoi_dir.symlink_to(chezmoi_src.resolve())
        log_step(f"Created symlink: {chezmoi_dir} → {chezmoi_src.resolve()}")

    log_step("Previewing chezmoi changes...")
    subprocess.run(["chezmoi", "diff"])
    print()
    if not confirm("Apply chezmoi dotfiles? [y/N] "):
        log_warn("Skipped chezmoi apply. Run 'chezmoi apply' manually when ready.")
        return
    subprocess.run(["chezmoi", "apply"])
    log_step("Chezmoi dotfiles applied.")


# ─── Step 7: Set hostname ───────────────────────────────────────────────────


def step_set_hostname():
    log_step("Setting hostname...")
    current = subprocess.run(
        ["hostname"], capture_output=True, text=True
    ).stdout.strip()
    print(f"  Current hostname: {current}")
    if ASSUME_YES:
        subprocess.run(["sudo", "hostnamectl", "set-hostname", "polaris-1"])
        log_step("Hostname set to polaris-1.")
        return
    choice = input("Set hostname to polaris-1? [y/N] or type a different name: ").strip()

    if choice.lower() in ("y", "yes"):
        subprocess.run(["sudo", "hostnamectl", "set-hostname", "polaris-1"])
        log_step("Hostname set to polaris-1.")
    elif choice.lower() in ("n", "no", ""):
        log_warn("Skipped hostname setup.")
    else:
        subprocess.run(["sudo", "hostnamectl", "set-hostname", choice])
        log_step(f"Hostname set to {choice}.")


# ─── Step 8: Set default shell to fish ───────────────────────────────────────


def step_set_fish_shell():
    log_step("Setting default shell to fish...")
    if os.environ.get("SHELL") == "/usr/bin/fish":
        log_step("Fish is already the default shell.")
        return
    subprocess.run(["chsh", "-s", "/usr/bin/fish"])
    log_step("Default shell set to fish. Log out and back in for it to take effect.")


# ─── Step 9: Apply system configs ────────────────────────────────────────────


def _root_filesystem_type():
    """Return the filesystem type mounted at /, or None if it cannot be detected."""
    result = subprocess.run(
        ["findmnt", "-n", "-o", "FSTYPE", "/"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _configure_snapper_root():
    """Create the snapper root config when snapper is installed on a btrfs system."""
    if not shutil.which("snapper"):
        log_warn("snapper not found — skipping snapper root configuration.")
        return

    root_fs = _root_filesystem_type()
    if root_fs != "btrfs":
        detected = root_fs or "unknown"
        log_warn(f"Root filesystem is {detected}, not btrfs — skipping snapper root configuration.")
        return

    existing = subprocess.run(
        ["sudo", "snapper", "-c", "root", "list"],
        capture_output=True, text=True,
    )
    if existing.returncode == 0:
        log_step("Snapper root config already exists.")
        return

    if not confirm("Create snapper root config for /? [y/N] "):
        log_warn("Skipped snapper root configuration.")
        return

    result = subprocess.run(
        ["sudo", "snapper", "-c", "root", "create-config", "/"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        log_step("Snapper root config created.")
    else:
        stderr = result.stderr.strip() or "unknown error"
        log_warn(f"Snapper root config failed: {stderr}")


def step_apply_system_configs():
    log_step("Applying system configuration files...")
    sysconf = SCRIPT_DIR / "system-config"
    if not sysconf.is_dir():
        log_error("system-config/ directory not found in repo.")
        return

    # mkinitcpio
    mkinitcpio = sysconf / "mkinitcpio.conf"
    if mkinitcpio.exists():
        log_warn("Will overwrite /etc/mkinitcpio.conf")
        if confirm("Apply mkinitcpio.conf? [y/N] "):
            subprocess.run(["sudo", "cp", str(mkinitcpio), "/etc/mkinitcpio.conf"])
            subprocess.run(["sudo", "mkinitcpio", "-P"])

    # locale
    for f in ("locale.conf", "vconsole.conf"):
        src = sysconf / f
        if src.exists():
            print(f"  Copying {f}")
            subprocess.run(["sudo", "cp", str(src), f"/etc/{f}"])

    # limine bootloader
    limine = sysconf / "limine.conf"
    if limine.exists():
        log_warn("Will overwrite /boot/limine.conf")
        if confirm("Apply limine.conf? [y/N] "):
            subprocess.run(["sudo", "cp", str(limine), "/boot/limine.conf"])

    # SDDM display manager
    sddm = sysconf / "sddm.conf"
    if sddm.exists():
        log_warn("Will overwrite /etc/sddm.conf (sets astronaut theme + wayland)")
        if confirm("Apply sddm.conf? [y/N] "):
            subprocess.run(["sudo", "cp", str(sddm), "/etc/sddm.conf"])

    _configure_snapper_root()

    log_step("System configs applied.")


# ─── Step 10: Post-install reminders ─────────────────────────────────────────


def step_post_install():
    log_step("Post-install checklist:")
    checklist = """\
  1.  Log in to 1Password:  1password --setup
  2.  Log in to Firefox / Chrome / Floorp and sync
  3.  Log in with spotify-player
  4.  Log in to Signal Desktop
  5.  Pair KDE Connect on phone
  6.  Log in to Niri — Noctalia will auto-download plugins on first launch
        (plugin list managed via ~/.config/noctalia/plugins.json)"""
    print(checklist)
    print()
    log_step("Done! Reboot when ready.")


# ─── Pre-step: Snapper snapshot ───────────────────────────────────────────────


def pre_snapshot():
    """Create a btrfs snapshot before applying any changes."""
    if not shutil.which("snapper"):
        log_warn("snapper not found — skipping pre-setup snapshot.")
        return
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=SCRIPT_DIR, capture_output=True, text=True,
    )
    desc = f"Before setup.py ({sha.stdout.strip()})" if sha.returncode == 0 else "Before setup.py"
    result = subprocess.run(
        ["sudo", "snapper", "create", "--description", desc, "--print-number"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        log_step(f"Created snapper snapshot #{result.stdout.strip()}")
    else:
        log_warn(f"Snapper snapshot failed: {result.stderr.strip()}")


# ─── Main ────────────────────────────────────────────────────────────────────

STEP_NAMES = {
    1: "Install native packages (pacman) + auto-detected hardware drivers",
    2: "Install AUR packages (yay)",
    3: "Enable system services",
    4: "Enable user services",
    5: "Install uv tools",
    6: "Install secrets (Claude, git, SSH from USB)",
    7: "Apply chezmoi dotfiles",
    8: "Set hostname (polaris-1)",
    9: "Set default shell to fish",
    10: "Apply system configs",
    11: "Post-install checklist",
}


def run_step(step_id: int, func) -> None:
    """Run a setup step and record its structured result."""
    step_name = STEP_NAMES[step_id]
    RUNTIME.info("Running setup step", step=step_id, name=step_name)
    try:
        func()
    except Exception as exc:
        STEP_RESULTS.append({"step": step_id, "name": step_name, "status": "failed", "error": str(exc)})
        RUNTIME.record_event("setup-step", status="failed", step=step_id, name=step_name, error=str(exc))
        raise
    STEP_RESULTS.append({"step": step_id, "name": step_name, "status": "ok"})
    RUNTIME.record_event("setup-step", step=step_id, name=step_name)


def main():
    global ASSUME_YES, JSON_OUTPUT, RUNTIME
    args = parse_args()
    ASSUME_YES = args.yes
    JSON_OUTPUT = args.json
    RUNTIME = ToolRuntime("setup", log_format=args.log_format, json_output=args.json)
    # TODO: Replace this interactive step runner with a declarative execution plan that Ansible can consume later.

    print()
    print("╔══════════════════════════════════════════╗")
    print("║    CachyOS Desktop Setup — phoenix       ║")
    print("╚══════════════════════════════════════════╝")
    print()

    hw = load_hardware()
    if hw:
        log_step("Detected hardware (from hardware-info.toml):")
        show_hardware_summary(hw)
        print()
    else:
        log_warn("No hardware-info.toml found — run probe-hardware.py on the target first.")
        print()

    print("Steps:")
    for num, desc in STEP_NAMES.items():
        print(f"  {num:>2}. {desc}")
    print()

    if args.step:
        choice = args.step.strip()
    elif ASSUME_YES:
        choice = "y"
    else:
        choice = input("Run all steps? [y/N] or enter step number: ").strip()

    steps = {
        "1": lambda: step_install_native(hw),
        "2": step_install_aur,
        "3": step_enable_system_services,
        "4": step_enable_user_services,
        "5": step_install_uv_tools,
        "6": step_install_secrets,
        "7": step_apply_chezmoi,
        "8": step_set_hostname,
        "9": step_set_fish_shell,
        "10": step_apply_system_configs,
        "11": step_post_install,
    }

    if choice.lower() in ("y", "yes", "all"):
        pre_snapshot()
        RUNTIME.record_event("pre-snapshot")
        for step_id, fn in ((int(key), value) for key, value in steps.items()):
            run_step(step_id, fn)
    elif choice in steps:
        pre_snapshot()
        RUNTIME.record_event("pre-snapshot")
        run_step(int(choice), steps[choice])
    else:
        log_warn("Invalid choice. Run with a step number (1-11) or 'y' for all.")

    if JSON_OUTPUT:
        RUNTIME.emit_summary(
            ok=True,
            assume_yes=ASSUME_YES,
            selected=choice,
            steps=STEP_RESULTS,
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        RUNTIME.warn("Interrupted.")
        sys.exit(1)
