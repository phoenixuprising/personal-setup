#!/usr/bin/env python3
"""Collect secrets and encrypt them into secrets.age for GitHub storage.

Run this on the SOURCE machine. Produces a single encrypted file (secrets.age)
that is safe to commit and push. The decryption key is stored in 1Password.

Requires: age, op (1Password CLI, signed in)

Collected:
  - Claude Code credentials (~/.claude/.credentials.json)
  - Git config (~/.gitconfig)
  - SSH config (~/.ssh/config, ~/.ssh/known_hosts)
  - SSH public key from 1Password (for authorized_keys on target)
  - 1Password account metadata
"""

import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
SECRETS_DIR = SCRIPT_DIR / "secrets"
ENCRYPTED_FILE = SCRIPT_DIR / "secrets.age"
OP_ITEM_TITLE = "system-ai Secrets Key"

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


def check_prerequisites():
    """Fail early if age or op are not available."""
    if not shutil.which("age"):
        log_error("age not found — install with: pacman -S age")
        sys.exit(1)
    if not shutil.which("op"):
        log_error("1Password CLI (op) not found — install from: https://1password.com/downloads/command-line/")
        sys.exit(1)
    # Check op is signed in
    result = subprocess.run(
        ["op", "account", "list", "--format=json"],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0 or not result.stdout.strip():
        log_error("1Password CLI not signed in — run: eval $(op signin)")
        sys.exit(1)


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


def collect_all():
    """Gather all secrets into the secrets/ directory. Returns item count."""
    # Clean any stale files from a previous run
    if SECRETS_DIR.exists():
        shutil.rmtree(SECRETS_DIR)
    SECRETS_DIR.mkdir()
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
    except subprocess.TimeoutExpired:
        log_warn("1Password CLI timed out — skipping account list.")

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
    except subprocess.TimeoutExpired:
        log_warn("1Password CLI timed out extracting SSH key.")

    return collected


def _get_or_create_key():
    """Retrieve existing age key from 1Password, or generate and store a new one.

    Returns (identity, recipient) tuple.
    """
    # Try to retrieve existing key
    result = subprocess.run(
        ["op", "item", "get", OP_ITEM_TITLE, "--fields", "password", "--reveal"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip().startswith("AGE-SECRET-KEY-"):
        identity = result.stdout.strip()
        log_step("Using existing age key from 1Password.")
    else:
        # Generate new keypair
        result = subprocess.run(["age-keygen"], capture_output=True, text=True)
        if result.returncode != 0:
            log_error("Failed to generate age keypair.")
            sys.exit(1)
        identity = None
        for line in result.stdout.splitlines():
            if line.startswith("AGE-SECRET-KEY-"):
                identity = line.strip()
                break
        if not identity:
            log_error("Failed to parse age keypair output.")
            sys.exit(1)
        _store_identity_in_1password(identity)
        log_step("Generated new age key and stored in 1Password.")

    # Derive recipient (public key) from identity
    result = subprocess.run(
        ["age-keygen", "-y"],
        input=identity, capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        log_error("Failed to derive public key from age identity.")
        sys.exit(1)
    recipient = result.stdout.strip()

    return identity, recipient


def encrypt_secrets():
    """Tar and encrypt secrets/ → secrets.age using key from 1Password."""
    identity, recipient = _get_or_create_key()

    # Create tarball of secrets/
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
        tarball_path = Path(tmp.name)

    try:
        with tarfile.open(tarball_path, "w") as tar:
            tar.add(SECRETS_DIR, arcname="secrets")
        log_step("Created secrets tarball.")

        # Encrypt with age
        result = subprocess.run(
            ["age", "-r", recipient, "-o", str(ENCRYPTED_FILE), str(tarball_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log_error(f"age encryption failed: {result.stderr}")
            sys.exit(1)
        log_step(f"Encrypted → {ENCRYPTED_FILE.relative_to(SCRIPT_DIR)}")
    finally:
        tarball_path.unlink(missing_ok=True)

    # Clean up plaintext secrets/
    shutil.rmtree(SECRETS_DIR)
    log_step("Removed plaintext secrets/ directory.")


def _store_identity_in_1password(identity):
    """Create or update the age identity in 1Password."""
    # Check if item already exists
    result = subprocess.run(
        ["op", "item", "get", OP_ITEM_TITLE, "--format=json"],
        capture_output=True, text=True, timeout=10,
    )

    if result.returncode == 0:
        # Item exists — update it
        subprocess.run(
            ["op", "item", "edit", OP_ITEM_TITLE, f"password={identity}"],
            capture_output=True, text=True, timeout=10,
            check=True,
        )
        log_step(f"Updated 1Password item: {OP_ITEM_TITLE}")
    else:
        # Item does not exist — create it
        subprocess.run(
            ["op", "item", "create",
             "--category=password",
             f"--title={OP_ITEM_TITLE}",
             f"password={identity}"],
            capture_output=True, text=True, timeout=10,
            check=True,
        )
        log_step(f"Created 1Password item: {OP_ITEM_TITLE}")


def commit_secrets():
    """Stage and commit secrets.age."""
    subprocess.run(
        ["git", "add", str(ENCRYPTED_FILE)],
        cwd=SCRIPT_DIR, check=True,
    )
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet", str(ENCRYPTED_FILE)],
        cwd=SCRIPT_DIR,
    )
    if result.returncode == 0:
        log_step("secrets.age unchanged — nothing to commit.")
        return
    subprocess.run(
        ["git", "commit", "-m", "updated secrets."],
        cwd=SCRIPT_DIR, check=True,
    )
    log_step("Committed secrets.age.")


def main():
    print()
    print("Collecting and encrypting secrets...")
    print()

    check_prerequisites()

    collected = collect_all()

    if not collected:
        log_warn("No secrets found to collect.")
        print()
        return

    encrypt_secrets()
    commit_secrets()

    print()
    log_step(f"Done — {collected} item(s) encrypted and committed.")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        log_warn("Interrupted.")
        sys.exit(1)
