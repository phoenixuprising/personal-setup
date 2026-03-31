# personal-setup

Personal CachyOS desktop bootstrap, dotfiles, and local AI-tooling repository for rebuilding a machine with the same packages, services, shell setup, user configuration, and repo-local helper tools.

## What’s in this repo

- `setup.py`: interactive machine provisioning script (11 steps).
- `probe-hardware.py`: captures target-machine hardware into `hardware-info.toml`.
- `collect-secrets.py`: gathers credentials from the source machine into `secrets/` for USB transfer.
- `media_transcribe.py`: repo-local transcription tool exposed through the `media-transcribe` CLI.
- `packages-native.txt`, `packages-aur.txt`: package inventories for `pacman` and `yay`.
- `services-system.txt`, `services-user.txt`: systemd units to enable.
- `chezmoi-source/`: managed dotfiles and app configs.
- `system-config/`: machine-level config files copied into `/etc` and related paths.
- `chezmoi-source/dot_local/share/system-ai/ufw/`: canonical UFW rule files that `chezmoi apply` installs into `/etc/ufw/` via a sudo-backed script.
- `secrets/`: gitignored directory with credentials for transfer (created by `collect-secrets.py`).
- `pyproject.toml`, `uv.lock`: the repo-local Python tool environment managed with `uv`.

## Intended workflow

This repo assumes a fresh CachyOS install with Python 3.11+ and `chezmoi` used for user dotfiles. Hardware-specific packages are auto-detected from `hardware-info.toml`, credentials are transferred via a gitignored `secrets/` directory, and local tools are expected to run through the repo-managed `uv` environment.

**On the source machine** (before copying to USB):
```bash
uv run python collect-secrets.py     # gathers Claude, git, SSH credentials into secrets/
```

**On the target machine** (from USB):
```bash
uv run python probe-hardware.py      # detect hardware for driver auto-install
uv run python setup.py               # run all steps or pick individual ones
```

`setup.py` can run all steps or a single numbered step. It handles package installation, service enablement, uv tool installation, chezmoi setup, hostname/shell changes, and selected system config application.

For repo-local tools:
```bash
uv sync
uv run media-transcribe --help
```

Most tools are moving toward a common CLI shape with `--json` summaries and `--log-format text|json` support so AI agents and shell automation can consume them reliably.

## Roadmap direction

- Keep the current Python scripts practical for CachyOS/Linux today.
- Structure inventories and shell-outs so Debian and macOS support can be added later without a rewrite.
- Gradually migrate provisioning intent toward declarative tools such as Ansible, and possibly Terraform where it fits, while keeping this repo as the source of truth.

## Safety notes

- Review generated hardware data before installing GPU, microcode, or kernel-related packages.
- Expect privileged operations: `pacman`, `systemctl enable`, copying into `/etc`, and regenerating initramfs.
- `hardware-info.toml` is generated per-machine; review before committing host-specific data.
- Applying `chezmoi` or `system-config/` changes can overwrite existing local config.

## Validation

Use these checks before committing changes:

```bash
uv run python -m py_compile setup.py
uv run python -m py_compile probe-hardware.py
git diff --check
```

For dotfile changes, preview with `chezmoi diff` before applying.
