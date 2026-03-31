# Encrypted Secrets Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Encrypt `collect-secrets.py` output with `age` so it can be committed to GitHub, store the key in 1Password, and separate wallpapers into a new `collect-userdata.py` script.

**Architecture:** `collect-secrets.py` collects credentials into `secrets/`, tars and encrypts them to `secrets.age` using a fresh age keypair (identity stored in 1Password). `setup.py` retrieves the identity from 1Password to decrypt. Wallpapers move to `collect-userdata.py` → `userdata/` (unencrypted, gitignored, USB transfer).

**Tech Stack:** Python 3 (stdlib: subprocess, shutil, pathlib, tempfile, tarfile), `age`/`age-keygen` CLI, `op` CLI (1Password)

---

### File Map

- **Modify:** `collect-secrets.py` — remove wallpapers, add tar+encrypt+1Password storage
- **Create:** `collect-userdata.py` — wallpaper collection
- **Modify:** `setup.py:207-271` — add decrypt-before-install, move wallpaper source to `userdata/`
- **Modify:** `.gitignore` — add `userdata/`
- **Modify:** `packages-native.txt` — add `age`

---

### Task 1: Add `age` to `packages-native.txt`

**Files:**
- Modify: `packages-native.txt`

- [ ] **Step 1: Add age to package list**

Add `age` in alphabetical position in `packages-native.txt`.

- [ ] **Step 2: Verify**

Run: `grep '^age$' packages-native.txt`
Expected: `age`

- [ ] **Step 3: Commit**

```bash
git add packages-native.txt
git commit -m "Add age to native packages for secrets encryption"
```

---

### Task 2: Add `userdata/` to `.gitignore`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add userdata/ to .gitignore**

Add `userdata/` to `.gitignore`. The file should look like:

```
.claude/
hardware-info.toml

secrets/
userdata/
__pycache__/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "Add userdata/ to gitignore for non-secret user data"
```

---

### Task 3: Create `collect-userdata.py`

**Files:**
- Create: `collect-userdata.py`

- [ ] **Step 1: Write `collect-userdata.py`**

```python
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
```

- [ ] **Step 2: Make executable**

Run: `chmod +x collect-userdata.py`

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('collect-userdata.py', doraise=True)"`
Expected: No output (clean compile)

- [ ] **Step 4: Commit**

```bash
git add collect-userdata.py
git commit -m "Add collect-userdata.py for non-secret user data (wallpapers)"
```

---

### Task 4: Rewrite `collect-secrets.py` with encryption

**Files:**
- Modify: `collect-secrets.py`

- [ ] **Step 1: Rewrite `collect-secrets.py`**

Replace the entire file with:

```python
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


def encrypt_secrets():
    """Tar and encrypt secrets/ → secrets.age, store key in 1Password."""
    # Generate fresh age keypair
    result = subprocess.run(
        ["age-keygen"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        log_error("Failed to generate age keypair.")
        sys.exit(1)

    # Parse identity (secret key line from stdout) and recipient (from stderr)
    identity = None
    for line in result.stdout.splitlines():
        if line.startswith("AGE-SECRET-KEY-"):
            identity = line.strip()
            break
    recipient = None
    for line in result.stderr.splitlines():
        if line.startswith("Public key:"):
            recipient = line.split(":", 1)[1].strip()
            break

    if not identity or not recipient:
        log_error("Failed to parse age keypair output.")
        sys.exit(1)

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

    # Store identity in 1Password
    _store_identity_in_1password(identity)

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

    print()
    log_step(f"Done — {collected} item(s) encrypted in {ENCRYPTED_FILE.name}")
    print()
    print("  Next steps:")
    print("    1. Commit and push secrets.age to GitHub")
    print("    2. On the target machine, clone the repo and run: python3 setup.py")
    print("    3. Step 6 will decrypt and install secrets (requires 1Password sign-in)")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        log_warn("Interrupted.")
        sys.exit(1)
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('collect-secrets.py', doraise=True)"`
Expected: No output (clean compile)

- [ ] **Step 3: Commit**

```bash
git add collect-secrets.py
git commit -m "Rewrite collect-secrets to encrypt output with age and store key in 1Password"
```

---

### Task 5: Update `setup.py` step 6 to decrypt and change wallpaper source

**Files:**
- Modify: `setup.py:207-271`

- [ ] **Step 1: Add imports to `setup.py`**

Add `tarfile` and `tempfile` to the import block at the top of `setup.py` (line 16, after `import sys`):

```python
import sys
import tarfile
import tempfile
import tomllib
```

- [ ] **Step 2: Add `_decrypt_secrets()` helper above `step_install_secrets()`**

Insert this function before `step_install_secrets()` (after `_install_secret()`, around line 205):

```python
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
```

- [ ] **Step 3: Rewrite `step_install_secrets()` to handle decryption and new wallpaper source**

Replace the existing `step_install_secrets()` function (lines 207-271) with:

```python
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

    # Wallpapers — now from userdata/ instead of secrets/
    userdata_dir = SCRIPT_DIR / "userdata"
    wallpapers_src = userdata_dir / "wallpapers"
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
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -c "import py_compile; py_compile.compile('setup.py', doraise=True)"`
Expected: No output (clean compile)

- [ ] **Step 5: Commit**

```bash
git add setup.py
git commit -m "Update setup.py to decrypt secrets.age and install wallpapers from userdata/"
```

---

### Task 6: End-to-end verification

- [ ] **Step 1: Verify all scripts compile**

Run:
```bash
python3 -c "import py_compile; py_compile.compile('collect-secrets.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('collect-userdata.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('setup.py', doraise=True)"
```
Expected: No output (all clean)

- [ ] **Step 2: Verify .gitignore has correct entries**

Run: `cat .gitignore`
Expected output:
```
.claude/
hardware-info.toml

secrets/
userdata/
__pycache__/
```

- [ ] **Step 3: Verify age is in packages-native.txt**

Run: `grep '^age$' packages-native.txt`
Expected: `age`

- [ ] **Step 4: Run `collect-secrets.py` (live test)**

Run: `python3 collect-secrets.py`

Expected behavior:
1. Checks for `age` and `op` (should pass)
2. Collects credentials into `secrets/`
3. Generates age keypair
4. Creates `secrets.age`
5. Stores identity in 1Password as `"system-ai Secrets Key"`
6. Removes `secrets/`
7. `secrets.age` exists, `secrets/` does not

Verify: `ls -la secrets.age && test ! -d secrets && echo "PASS"`

- [ ] **Step 5: Verify 1Password item was created**

Run: `op item get "system-ai Secrets Key" --fields password --reveal`
Expected: An `AGE-SECRET-KEY-...` string

- [ ] **Step 6: Test decryption round-trip**

Run:
```bash
# Extract the key, decrypt, and verify contents
op item get "system-ai Secrets Key" --fields password --reveal > /tmp/test-identity.key
age -d -i /tmp/test-identity.key -o /tmp/test-secrets.tar secrets.age
tar tf /tmp/test-secrets.tar
rm /tmp/test-identity.key /tmp/test-secrets.tar
```
Expected: tar listing shows `secrets/` directory with collected files

- [ ] **Step 7: Run `collect-userdata.py` (live test)**

Run: `python3 collect-userdata.py`

Expected: Collects wallpapers into `userdata/wallpapers/`

Verify: `ls userdata/wallpapers/ | head -5`

- [ ] **Step 8: Commit secrets.age**

```bash
git add secrets.age
git commit -m "Add encrypted secrets bundle"
```
