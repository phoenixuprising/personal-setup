# New Machine Setup Guide

Step-by-step instructions for setting up polaris-1 (or any new CachyOS machine) from a USB drive.

## Before you leave the source machine

1. **Collect secrets** from the current machine:
   ```
   python3 collect-secrets.py
   ```
   This grabs Claude credentials, git config, SSH config, your public key from 1Password, and 1Password account metadata into `secrets/`.

2. **Copy the entire repo** (including `secrets/`) to your USB drive.

## On the new machine

### Phase 1: Install CachyOS

1. Boot the CachyOS installer from USB/ISO.
2. Select **Niri** as the desktop environment.
3. Use **btrfs** with subvolumes (`@`, `@home`, `@root`, `@srv`, `@cache`, `@tmp`, `@log`).
4. Use **limine** as the bootloader.
5. Create user **phoenix** during install.
6. Complete install and reboot into the new system.

### Phase 2: Probe hardware

1. Mount the USB drive and open a terminal.
2. `cd` into the repo on the USB:
   ```
   cd /run/media/phoenix/<usb-label>/personal-setup
   ```
3. Probe the hardware:
   ```
   python3 probe-hardware.py
   ```
   This generates `hardware-info.toml` with your GPU drivers, CPU microcode, and other hardware-specific packages.

4. Review the output — confirm GPU vendor, disk layout, and network interfaces look correct.

### Phase 3: Run setup

```
uv run python setup.py
```

You can run all 13 steps at once (enter `y`) or pick individual steps by number.
For a non-interactive run that auto-accepts confirmations, use `uv run python setup.py -y`.
For machine-readable output, add `--json`.
Here's what each does:

| Step | What it does | Needs internet? |
|------|-------------|-----------------|
| 1 | Install native packages (pacman) + hardware drivers | Yes |
| 2 | Install AUR packages (yay) | Yes |
| 3 | Enable system services (bluetooth, NetworkManager, etc.) | No |
| 4 | Enable user services (pipewire, etc.) | No |
| 5 | Install uv tools (forgetful-ai, aider-chat, jcodemunch-mcp, command-help-parser if checked out locally) | Yes |
| 6 | Pull the default Ollama coding model (`qwen2.5-coder:14b`) | Yes |
| 7 | Install VS Code extensions (currently Continue) | No |
| 8 | Install secrets (Claude creds, git config, SSH keys, sshd) | No |
| 9 | Apply chezmoi dotfiles (fish config, alacritty, AI harness configs, etc.) | No |
| 10 | Keep current hostname or set a new one | No |
| 11 | Set default shell to fish | No |
| 12 | Apply system configs (mkinitcpio, locale, limine, Snapper) | No |
| 13 | Print post-install checklist | No |

**Recommended order if running step-by-step:** Run 1-2 first (needs network), then the rest.

### Phase 4: Post-install (manual)

After setup.py finishes, handle these manually:

1. **1Password:** `1password --setup` — sign in to unlock SSH agent + git signing.
2. **Browsers:** Sign in to Firefox / Chrome / Floorp and sync.
3. **Spotify:** Sign in with `spotify-player`.
4. **Signal:** Sign in to Signal Desktop.
5. **KDE Connect:** Pair with your phone.
6. **AI harnesses:**
   - `ollama list` should show `qwen2.5-coder:14b`
   - Set `OPENAI_API_KEY` in your shell for Aider.
   - Open VS Code once so Continue can finish first-run setup and let you pick active models per role.
7. **Reboot** and verify everything works.

`chezmoi apply` now also syncs the managed UFW rules into `/etc/ufw/` via a sudo-backed script. That includes both SSH and KDE Connect allow rules.

### Phase 5: Verify SSH access

From another machine where 1Password SSH agent is running:

```
ssh phoenix@polaris-1
```

sshd is configured for pubkey-only auth (no passwords, no root login). Your ed25519 public key from 1Password is already in `~/.ssh/authorized_keys`.

## Troubleshooting

- **No internet after install:** Run `sudo systemctl enable --now NetworkManager` manually, then start from step 1.
- **GPU issues:** Check `hardware-info.toml` has the right vendor/driver packages. Re-run `python3 probe-hardware.py` if needed.
- **SSH rejected:** Verify `~/.ssh/authorized_keys` exists and has your public key. Check `sudo systemctl status sshd` for errors.
- **Git signing fails:** 1Password must be signed in and unlocked — the SSH agent provides the signing key.
