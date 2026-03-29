# Repository Guidelines

## Project Structure & Module Organization
This repository is a personal CachyOS setup/bootstrap repo, not a single application. Top-level Python scripts drive setup and hardware capture: `setup.py` provisions a machine, `probe-hardware.py` regenerates the ignored `hardware-info.toml`, and `collect-secrets.py` gathers credentials for USB transfer. Package and service inventories live in `packages-*.txt`, `services-*.txt`, and `uv-tools.txt`. User-level dotfiles are stored under `chezmoi-source/`, with app configs in `chezmoi-source/dot_config/<app>/` and sensitive templates prefixed with `private_`. Machine-wide files that are copied into `/etc` or firewall paths live in `system-config/`. Credentials for transfer live in the gitignored `secrets/` directory.

## Build, Test, and Development Commands
There is no build step. Use lightweight validation commands before committing:

- `python3 -m py_compile setup.py` checks syntax for the main bootstrap script.
- `python3 -m py_compile probe-hardware.py` checks the hardware probe script.
- `python3 -m py_compile collect-secrets.py` checks the secret collector script.
- `python3 probe-hardware.py` captures current machine details into `hardware-info.toml`.
- `chezmoi diff` previews dotfile changes after syncing `chezmoi-source/` into `~/.local/share/chezmoi`.
- `git diff --check` catches whitespace and patch-format issues.

## Coding Style & Naming Conventions
Follow existing Python style: functions for each setup step, `pathlib.Path` for file operations, `subprocess` for system commands. Keep script output explicit and reviewable because many steps are privileged or hardware-specific. Preserve chezmoi naming conventions such as `dot_*` for normal dotfiles and `private_*` for secrets/templates. Use descriptive file names like `services-user.txt` and `packages-native.txt`; prefer adding a new inventory file over embedding long lists inside scripts.

## Testing Guidelines
This repo currently relies on syntax checks and manual verification rather than an automated test suite. For script changes, run `py_compile` and exercise the affected step on a non-critical machine or in a dry-run style review. For dotfile changes, inspect `chezmoi diff` output before applying. Document any manual verification in the PR when behavior changes system state.

## Commit & Pull Request Guidelines
Match the existing commit history: short, imperative, sentence-case summaries such as `Add hardware probe script for target machine`. Keep commits scoped to one concern. PRs should describe the target environment, call out hardware-sensitive changes, and list manual verification performed. Include screenshots only for visible UI/theme changes.

## Security & Configuration Tips
Do not commit rendered secrets, the `secrets/` directory, host-specific SSH material, or generated `hardware-info.toml`. Review any `rm -rf`, package, firewall, bootloader, or `/etc` changes carefully before merging.
