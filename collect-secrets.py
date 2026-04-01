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
  - Optional Tailscale auth key from 1Password
"""

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from tool_runtime import ToolRuntime

SCRIPT_DIR = Path(__file__).parent.resolve()
SECRETS_DIR = SCRIPT_DIR / "secrets"
ENCRYPTED_FILE = SCRIPT_DIR / "secrets.age"
OP_ITEM_TITLE = "system-ai Secrets Key"
TAILSCALE_AUTH_KEY_ITEM_TITLE = "system-ai Tailscale Auth Key"
RUNTIME = ToolRuntime("collect-secrets")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for secrets collection."""
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
    parser.add_argument(
        "--skip-git-commit",
        action="store_true",
        help="Encrypt secrets.age but do not create a git commit.",
    )
    return parser


def check_prerequisites():
    """Fail early if age or op are not available."""
    if not shutil.which("age"):
        RUNTIME.error("age not found — install with: pacman -S age")
        sys.exit(1)
    if not shutil.which("op"):
        RUNTIME.error("1Password CLI (op) not found — install from: https://1password.com/downloads/command-line/")
        sys.exit(1)
    # Check op is signed in
    result = subprocess.run(
        ["op", "account", "list", "--format=json"],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0 or not result.stdout.strip():
        RUNTIME.error("1Password CLI not signed in — run: eval $(op signin)")
        sys.exit(1)


def collect_file(src, dest_name, mode=0o600, dest_subdir=None):
    """Copy a file into secrets/, preserving nothing about the original path."""
    src = Path(src).expanduser()
    if not src.exists():
        RUNTIME.warn("Optional file not found", path=str(src))
        return False

    dest_dir = SECRETS_DIR / dest_subdir if dest_subdir else SECRETS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / dest_name

    shutil.copy2(src, dest)
    dest.chmod(mode)
    RUNTIME.info("Collected file", source=str(src), destination=str(dest.relative_to(SCRIPT_DIR)))
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
            RUNTIME.info(
                "Collected 1Password account list",
                destination=str(accounts_file.relative_to(SCRIPT_DIR)),
            )
            collected += 1
    except subprocess.TimeoutExpired:
        RUNTIME.warn("1Password CLI timed out — skipping account list")

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
            RUNTIME.info("Collected SSH public key", destination=str(pubkey_file.relative_to(SCRIPT_DIR)))
            collected += 1
    except subprocess.TimeoutExpired:
        RUNTIME.warn("1Password CLI timed out extracting SSH key")

    # Optional Tailscale auth key for unattended `tailscale up` on the target
    try:
        result = subprocess.run(
            ["op", "item", "get", TAILSCALE_AUTH_KEY_ITEM_TITLE, "--fields", "password", "--reveal"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            tailscale_key_file = SECRETS_DIR / "tailscale-auth-key.txt"
            tailscale_key_file.write_text(result.stdout.strip() + "\n")
            tailscale_key_file.chmod(0o600)
            RUNTIME.info(
                "Collected Tailscale auth key",
                destination=str(tailscale_key_file.relative_to(SCRIPT_DIR)),
            )
            collected += 1
    except subprocess.TimeoutExpired:
        RUNTIME.warn("1Password CLI timed out extracting Tailscale auth key")

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
        RUNTIME.info("Using existing age key from 1Password")
    else:
        # Generate new keypair
        result = subprocess.run(["age-keygen"], capture_output=True, text=True)
        if result.returncode != 0:
            RUNTIME.error("Failed to generate age keypair")
            sys.exit(1)
        identity = None
        for line in result.stdout.splitlines():
            if line.startswith("AGE-SECRET-KEY-"):
                identity = line.strip()
                break
        if not identity:
            RUNTIME.error("Failed to parse age keypair output")
            sys.exit(1)
        _store_identity_in_1password(identity)
        RUNTIME.info("Generated new age key and stored in 1Password")

    # Derive recipient (public key) from identity
    result = subprocess.run(
        ["age-keygen", "-y"],
        input=identity, capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        RUNTIME.error("Failed to derive public key from age identity")
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
        RUNTIME.info("Created secrets tarball")

        # Encrypt with age
        result = subprocess.run(
            ["age", "-r", recipient, "-o", str(ENCRYPTED_FILE), str(tarball_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            RUNTIME.error("age encryption failed", stderr=result.stderr.strip())
            sys.exit(1)
        RUNTIME.info("Encrypted secrets archive", destination=str(ENCRYPTED_FILE.relative_to(SCRIPT_DIR)))
    finally:
        tarball_path.unlink(missing_ok=True)

    # Clean up plaintext secrets/
    shutil.rmtree(SECRETS_DIR)
    RUNTIME.info("Removed plaintext secrets directory")


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
        RUNTIME.info("Updated 1Password item", title=OP_ITEM_TITLE)
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
        RUNTIME.info("Created 1Password item", title=OP_ITEM_TITLE)


def commit_secrets():
    """Stage and commit secrets.age."""
    # TODO: Split repo mutation from collection so CI and non-git users can reuse this script safely.
    subprocess.run(
        ["git", "add", str(ENCRYPTED_FILE)],
        cwd=SCRIPT_DIR, check=True,
    )
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet", str(ENCRYPTED_FILE)],
        cwd=SCRIPT_DIR,
    )
    if result.returncode == 0:
        RUNTIME.info("secrets.age unchanged — nothing to commit")
        return
    subprocess.run(
        ["git", "commit", "-m", "updated secrets."],
        cwd=SCRIPT_DIR, check=True,
    )
    RUNTIME.info("Committed secrets.age")


def main() -> int:
    """Collect, encrypt, and optionally commit transferable secrets."""
    global RUNTIME
    args = build_parser().parse_args()
    RUNTIME = ToolRuntime("collect-secrets", log_format=args.log_format, json_output=args.json)
    RUNTIME.info("Collecting and encrypting secrets")

    check_prerequisites()

    collected = collect_all()

    if not collected:
        RUNTIME.warn("No secrets found to collect")
        RUNTIME.emit_summary(ok=True, collected_item_count=0, committed=False, encrypted=False)
        return 0

    encrypt_secrets()
    committed = False
    if not args.skip_git_commit:
        commit_secrets()
        committed = True

    RUNTIME.record_event(
        "collect-secrets",
        count=collected,
        encrypted_file=str(ENCRYPTED_FILE),
        committed=committed,
    )
    if not args.json:
        print()
        RUNTIME.info("Secrets workflow completed", collected_item_count=collected, committed=committed)
        print()
    RUNTIME.emit_summary(
        ok=True,
        collected_item_count=collected,
        committed=committed,
        encrypted=True,
        encrypted_file=str(ENCRYPTED_FILE),
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        ToolRuntime("collect-secrets").warn("Interrupted")
        sys.exit(1)
