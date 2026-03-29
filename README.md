# personal-setup

Personal CachyOS desktop bootstrap and dotfiles repository for rebuilding a machine with the same packages, services, shell setup, and user configuration.

## What’s in this repo

- `setup.py`: interactive machine provisioning script (11 steps).
- `probe-hardware.py`: captures target-machine hardware into `hardware-info.toml`.
- `collect-secrets.py`: gathers credentials from the source machine into `secrets/` for USB transfer.
- `packages-native.txt`, `packages-aur.txt`: package inventories for `pacman` and `yay`.
- `services-system.txt`, `services-user.txt`: systemd units to enable.
- `chezmoi-source/`: managed dotfiles and app configs.
- `system-config/`: machine-level config files copied into `/etc` and related paths.
- `secrets/`: gitignored directory with credentials for transfer (created by `collect-secrets.py`).

## Intended workflow

This repo assumes a fresh CachyOS install with Python 3.11+ and `chezmoi` used for user dotfiles. Hardware-specific packages are auto-detected from `hardware-info.toml`, and credentials are transferred via a gitignored `secrets/` directory.

**On the source machine** (before copying to USB):
```bash
python3 collect-secrets.py     # gathers Claude, git, SSH credentials into secrets/
```

**On the target machine** (from USB):
```bash
python3 probe-hardware.py      # detect hardware for driver auto-install
python3 setup.py               # run all steps or pick individual ones
```

`setup.py` can run all steps or a single numbered step. It handles package installation, service enablement, uv tool installation, chezmoi setup, hostname/shell changes, and selected system config application.

## Safety notes

- Review generated hardware data before installing GPU, microcode, or kernel-related packages.
- Expect privileged operations: `pacman`, `systemctl enable`, copying into `/etc`, and regenerating initramfs.
- `hardware-info.toml` is generated per-machine; review before committing host-specific data.
- Applying `chezmoi` or `system-config/` changes can overwrite existing local config.

## Validation

Use these checks before committing changes:

```bash
python3 -m py_compile setup.py
python3 -m py_compile probe-hardware.py
git diff --check
```

For dotfile changes, preview with `chezmoi diff` before applying.
