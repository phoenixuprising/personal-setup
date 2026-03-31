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
python3 setup.py
```

You can run all 11 steps at once (enter `y`) or pick individual steps by number. Here's what each does:

| Step | What it does | Needs internet? |
|------|-------------|-----------------|
| 1 | Install native packages (pacman) + hardware drivers | Yes |
| 2 | Install AUR packages (yay) | Yes |
| 3 | Enable system services (bluetooth, NetworkManager, etc.) | No |
| 4 | Enable user services (pipewire, etc.) | No |
| 5 | Install uv tools (forgetful-ai, jcodemunch-mcp, command-help-parser if checked out locally) | Yes |
| 6 | Install secrets (Claude creds, git config, SSH keys, sshd) | No |
| 7 | Apply chezmoi dotfiles (fish config, alacritty, etc.) | No |
| 8 | Set hostname to polaris-1 | No |
| 9 | Set default shell to fish | No |
| 10 | Apply system configs (mkinitcpio, locale, limine, UFW) | No |
| 11 | Print post-install checklist | No |

**Recommended order if running step-by-step:** Run 1-2 first (needs network), then the rest.

### Phase 4: Post-install (manual)

After setup.py finishes, handle these manually:

1. **1Password:** `1password --setup` — sign in to unlock SSH agent + git signing.
2. **Browsers:** Sign in to Firefox / Chrome / Floorp and sync.
3. **Spotify:** Start the `spotifyd` user service and sign in with `spotify-player`.
4. **Signal:** Sign in to Signal Desktop.
5. **KDE Connect:** Pair with your phone.
6. **Snapper:** `sudo snapper -c root create-config /`
7. **UFW firewall:**
   ```
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw enable
   ```
8. **Reboot** and verify everything works.

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
