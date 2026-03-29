#!/usr/bin/env python3
"""Probe hardware on target machine and generate hardware-info.toml.

Run on the target CachyOS machine. Outputs hardware-info.toml in the same
directory as this script, which setup.py reads to auto-detect driver packages.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()


def run(cmd):
    """Run a shell command and return stripped stdout."""
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True
    ).stdout.strip()


def read_sysfs(path, default="unknown"):
    """Read a sysfs/procfs file, returning default on failure."""
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


# ─── TOML writer (handles our specific schema) ───────────────────────────────


def _toml_value(v):
    """Serialize a Python value to a TOML literal."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"Unsupported TOML type: {type(v)}")


def write_toml(data, path):
    """Write a dict as TOML, preserving insertion order.

    Handles simple tables ([key]) and arrays of tables ([[key]]).
    """
    lines = [
        "# Hardware probe for CachyOS setup",
        f"# Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"[{key}]")
            for k, v in value.items():
                lines.append(f"{k} = {_toml_value(v)}")
            lines.append("")
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            for item in value:
                lines.append(f"[[{key}]]")
                for k, v in item.items():
                    lines.append(f"{k} = {_toml_value(v)}")
                lines.append("")
    Path(path).write_text("\n".join(lines))


# ─── Probe functions ─────────────────────────────────────────────────────────


def probe_cpu():
    info = {}
    for line in run("lscpu").splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            info[k.strip()] = v.strip()
    vendor = info.get("Vendor ID", "unknown")
    model = info.get("Model name", "unknown")
    cores = int(run("nproc"))
    microcode = "amd-ucode" if "AMD" in vendor else "intel-ucode"
    return {"vendor": vendor, "model": model, "cores": cores, "microcode": microcode}


def probe_gpus():
    lines = [
        l
        for l in run("lspci | grep -iE 'VGA compatible|3D controller'").splitlines()
        if l
    ]
    has_multiple = len(lines) > 1
    gpus = []

    for line in lines:
        pci_id = line.split()[0]
        gpu = {"pci_id": pci_id, "description": line}
        lower = line.lower()

        if "nvidia" in lower:
            gpu["vendor"] = "nvidia"
            gpu["driver_packages"] = [
                "nvidia-utils",
                "nvidia-settings",
                "lib32-nvidia-utils",
                "opencl-nvidia",
                "lib32-opencl-nvidia",
                "libva-nvidia-driver",
                "egl-wayland",
            ]
            if has_multiple:
                gpu["hybrid"] = True
                gpu["hybrid_packages"] = ["nvidia-prime", "supergfxctl"]
            else:
                gpu["hybrid"] = False
        elif "intel" in lower:
            gpu["vendor"] = "intel"
            gpu["driver_packages"] = [
                "vulkan-intel",
                "lib32-vulkan-intel",
                "intel-media-driver",
                "vpl-gpu-rt",
            ]
        elif "amd" in lower or "radeon" in lower:
            gpu["vendor"] = "amd"
            gpu["driver_packages"] = [
                "vulkan-radeon",
                "lib32-vulkan-radeon",
                "libva-mesa-driver",
                "lib32-libva-mesa-driver",
            ]
        else:
            gpu["vendor"] = "unknown"
            gpu["driver_packages"] = []

        gpus.append(gpu)
    return gpus


def probe_memory():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            ram_kb = int(line.split()[1])
            return {"total_gb": round(ram_kb / 1048576)}
    return {"total_gb": 0}


def probe_disks():
    disks = []
    lines = run(
        "lsblk -dnpo NAME,SIZE,TYPE,ROTA,MODEL | grep ' disk ' | grep -v zram"
    ).splitlines()

    for line in lines:
        if not line.strip():
            continue
        device = line.split()[0]
        size_bytes = int(run(f"lsblk -dnbo SIZE {device}"))
        size_gb = round(size_bytes / 1073741824)
        basename = os.path.basename(device)
        rotational = read_sysfs(f"/sys/block/{basename}/queue/rotational", "?")
        model = run(f"lsblk -dnpo MODEL {device}")

        if rotational == "0":
            disk_type = "ssd"
        elif rotational == "1":
            disk_type = "hdd"
        else:
            disk_type = "unknown"

        disks.append(
            {"device": device, "size_gb": size_gb, "type": disk_type, "model": model}
        )
    return disks


def probe_network():
    interfaces = []
    for iface in sorted(os.listdir("/sys/class/net")):
        if iface == "lo":
            continue

        if os.path.isdir(f"/sys/class/net/{iface}/wireless"):
            itype = "wifi"
        elif os.path.exists(f"/sys/class/net/{iface}/device"):
            itype = "ethernet"
        else:
            itype = "unknown"

        try:
            driver = os.path.basename(
                os.readlink(f"/sys/class/net/{iface}/device/driver")
            )
        except OSError:
            driver = "unknown"

        interfaces.append({"interface": iface, "type": itype, "driver": driver})
    return interfaces


def probe_motherboard():
    return {
        "vendor": read_sysfs("/sys/class/dmi/id/board_vendor"),
        "name": read_sysfs("/sys/class/dmi/id/board_name"),
        "version": read_sysfs("/sys/class/dmi/id/board_version"),
    }


def probe_system():
    try:
        output = run("hostnamectl --json=short")
        chassis = json.loads(output).get("Chassis", "unknown")
    except (json.JSONDecodeError, ValueError):
        chassis = "unknown"
    firmware = "uefi" if os.path.isdir("/sys/firmware/efi") else "bios"
    return {"chassis": chassis, "firmware": firmware}


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    print("Probing hardware...")

    data = {
        "cpu": probe_cpu(),
        "gpu": probe_gpus(),
        "memory": probe_memory(),
        "disk": probe_disks(),
        "network": probe_network(),
        "motherboard": probe_motherboard(),
        "system": probe_system(),
    }

    out_path = SCRIPT_DIR / "hardware-info.toml"
    write_toml(data, out_path)

    print()
    print(f"Done. Hardware info written to: {out_path}")
    print(out_path.read_text())


if __name__ == "__main__":
    main()
