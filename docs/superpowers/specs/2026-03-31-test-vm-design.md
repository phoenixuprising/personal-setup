# Test VM Environment — Design Spec

## Purpose

Provide a repeatable test environment for `setup.py` using a CachyOS VM managed via libvirt/QEMU, with a GUI through virt-manager.

## Approach

Pure libvirt + Python CLI. No Vagrant. The CachyOS install is done manually once through virt-manager's GUI, then snapshotted as a reusable clean base. A Python CLI tool manages the full VM lifecycle.

## Prerequisites

Host packages (installed via pacman):
- `qemu-full` — QEMU hypervisor
- `libvirt` — VM management daemon
- `virt-manager` — GUI console
- `dnsmasq` — VM networking (NAT)
- `edk2-ovmf` — UEFI firmware (required by CachyOS + limine)

Host setup:
- User added to `libvirt` group
- `libvirtd.service` enabled and started

Python packages (`test-vm/requirements.txt`):
- `click`
- `libvirt-python`

## CLI Tool: `test-vm/vm.py`

Single-file Click CLI with the following subcommands:

### `create <iso-path>`

Creates and boots a new VM for manual CachyOS installation:
- Generates a 40GB qcow2 disk image at `test-vm/cachyos-test.qcow2`
- Defines a libvirt domain with:
  - **Name:** `cachyos-test`
  - **RAM:** 4096 MB
  - **CPUs:** 4
  - **Firmware:** UEFI via OVMF
  - **Disk:** virtio, backed by the qcow2 image
  - **CDROM:** the provided ISO path
  - **Network:** default NAT (virbr0)
  - **Filesystem:** 9p share of the repo root → `/mnt/system-ai` inside VM
  - **Video:** virtio GPU (for virt-manager display)
- Boots the VM and opens virt-manager
- Prints instructions: install CachyOS, then run `vm.py snapshot` when done

### `snapshot [name]`

Takes a named snapshot of the current VM state. Default name: `clean`.
Uses libvirt's internal snapshot API (stored inside the qcow2).

### `start`

Boots the VM (from current state, not a snapshot) and opens virt-manager.
Errors if VM is already running.

### `stop`

Graceful shutdown via libvirt. Waits briefly, then warns if still running.

### `ssh`

Looks up the VM's IP from the libvirt DHCP lease table, then execs `ssh phoenix@<ip>`.

### `reset [name]`

Reverts to the named snapshot (default: `clean`) and boots the VM.
Opens virt-manager after boot.

### `destroy`

Shuts down the VM if running, undefines it (including snapshots), and deletes the qcow2 disk image. Asks for confirmation first.

## VM Configuration

Hardcoded as a dict at the top of `vm.py`:

```python
VM_CONFIG = {
    "name": "cachyos-test",
    "ram_mb": 4096,
    "vcpus": 4,
    "disk_gb": 40,
    "firmware": "/usr/share/edk2/x64/OVMF_CODE.fd",
    "disk_path": SCRIPT_DIR / "cachyos-test.qcow2",
}
```

## Filesystem Sharing (9p)

The host's `system-ai` repo root is shared into the VM via virtio-9p:
- **Host path:** repo root (parent of `test-vm/`)
- **Mount tag:** `system-ai`
- **Guest mount point:** `/mnt/system-ai` (manual mount inside VM)

Inside the VM after CachyOS install:
```bash
sudo mount -t 9p -o trans=virtio system-ai /mnt/system-ai
```

This is a manual step during the initial install — once snapshotted, it persists.

## Workflow

1. Install prerequisites on host
2. Download CachyOS ISO (Niri edition)
3. `python test-vm/vm.py create ~/Downloads/cachyos-niri.iso`
4. Install CachyOS through virt-manager GUI (Niri desktop, btrfs, limine, user phoenix)
5. Mount 9p share, install any guest prerequisites
6. `python test-vm/vm.py snapshot clean`
7. Test: `python test-vm/vm.py ssh` → `cd /mnt/system-ai && python setup.py`
8. Reset: `python test-vm/vm.py reset` → clean slate, test again

## File Structure

```
test-vm/
  vm.py                 # CLI tool
  requirements.txt      # click, libvirt-python
  cachyos-test.qcow2    # VM disk (gitignored, created by vm.py)
```

Add to `.gitignore`: `test-vm/*.qcow2`

## Out of Scope

- Automated CachyOS installation (Calamares is GUI-only)
- Multi-VM support (single test VM is sufficient)
- CI integration
