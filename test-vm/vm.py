#!/usr/bin/env python3
"""CachyOS test VM manager — libvirt + virt-manager CLI."""

import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import click
import libvirt

SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_DIR = SCRIPT_DIR.parent

VM_CONFIG = {
    "name": "cachyos-test",
    "ram_mb": 4096,
    "vcpus": 4,
    "disk_gb": 40,
    "firmware": "/usr/share/edk2/x64/OVMF_CODE.4m.fd",
    "nvram_template": "/usr/share/edk2/x64/OVMF_VARS.4m.fd",
    "disk_path": SCRIPT_DIR / "cachyos-test.qcow2",
    "nvram_path": SCRIPT_DIR / "cachyos-test_VARS.fd",
}

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def log_step(msg):
    click.echo(f"{GREEN}▶ {msg}{RESET}")


def log_warn(msg):
    click.echo(f"{YELLOW}⚠ {msg}{RESET}")


def log_error(msg):
    click.echo(f"{RED}✗ {msg}{RESET}")


def connect():
    """Connect to the system libvirt daemon."""
    conn = libvirt.open("qemu:///system")
    if conn is None:
        log_error("Failed to connect to libvirt. Is libvirtd running?")
        sys.exit(1)
    return conn


def lookup(conn):
    """Look up the test VM domain. Returns None if not defined."""
    try:
        return conn.lookupByName(VM_CONFIG["name"])
    except libvirt.libvirtError:
        return None


def require_vm(conn):
    """Look up the VM, exit if it doesn't exist."""
    dom = lookup(conn)
    if dom is None:
        log_error(f"VM '{VM_CONFIG['name']}' not found. Run 'create' first.")
        sys.exit(1)
    return dom


def open_virt_manager():
    """Open virt-manager showing the VM console."""
    subprocess.Popen(
        ["virt-manager", "--connect", "qemu:///system",
         "--show-domain-console", VM_CONFIG["name"]],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def get_vm_ip(dom):
    """Get the VM's IP address from libvirt DHCP leases."""
    # Try the guest agent first, fall back to DHCP leases
    try:
        ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
        for iface in ifaces.values():
            for addr in iface.get("addrs", []):
                if addr["type"] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                    return addr["addr"]
    except libvirt.libvirtError:
        pass
    return None


def build_domain_xml(iso_path=None):
    """Build the libvirt domain XML for the test VM."""
    cfg = VM_CONFIG
    disk_path = str(cfg["disk_path"])
    ram_kb = cfg["ram_mb"] * 1024

    cdrom_xml = ""
    if iso_path:
        cdrom_xml = f"""
    <disk type='file' device='cdrom'>
      <driver name='qemu' type='raw'/>
      <source file='{iso_path}'/>
      <target dev='sda' bus='sata'/>
      <readonly/>
      <boot order='1'/>
    </disk>"""

    boot_order = "2" if iso_path else "1"

    return f"""<domain type='kvm'>
  <name>{cfg['name']}</name>
  <memory unit='KiB'>{ram_kb}</memory>
  <vcpu>{cfg['vcpus']}</vcpu>
  <os firmware='efi'>
    <type arch='x86_64' machine='q35'>hvm</type>
    <loader readonly='yes' type='pflash'>{cfg['firmware']}</loader>
    <nvram template='{cfg['nvram_template']}'>{cfg['nvram_path']}</nvram>
  </os>
  <features>
    <acpi/>
    <apic/>
  </features>
  <cpu mode='host-passthrough'/>
  <clock offset='utc'/>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' discard='unmap'/>
      <source file='{disk_path}'/>
      <target dev='vda' bus='virtio'/>
      <boot order='{boot_order}'/>
    </disk>{cdrom_xml}
    <interface type='network'>
      <source network='default'/>
      <model type='virtio'/>
    </interface>
    <filesystem type='mount' accessmode='passthrough'>
      <driver type='path'/>
      <source dir='{REPO_DIR}'/>
      <target dir='system-ai'/>
    </filesystem>
    <graphics type='spice' autoport='yes'/>
    <video>
      <model type='virtio' heads='1'/>
    </video>
    <channel type='unix'>
      <target type='virtio' name='org.qemu.guest_agent.0'/>
    </channel>
    <rng model='virtio'>
      <backend model='random'>/dev/urandom</backend>
    </rng>
  </devices>
</domain>"""


@click.group()
def cli():
    """Manage the CachyOS test VM."""
    pass


@cli.command()
@click.argument("iso_path", type=click.Path(exists=True, resolve_path=True))
def create(iso_path):
    """Create a new test VM and boot the CachyOS installer."""
    conn = connect()
    if lookup(conn) is not None:
        log_error(f"VM '{VM_CONFIG['name']}' already exists. Run 'destroy' first.")
        sys.exit(1)

    disk_path = VM_CONFIG["disk_path"]
    if not disk_path.exists():
        log_step(f"Creating {VM_CONFIG['disk_gb']}GB disk image...")
        subprocess.run(
            ["qemu-img", "create", "-f", "qcow2", str(disk_path),
             f"{VM_CONFIG['disk_gb']}G"],
            check=True, capture_output=True,
        )

    log_step("Defining VM...")
    xml = build_domain_xml(iso_path=iso_path)
    dom = conn.defineXML(xml)
    if dom is None:
        log_error("Failed to define VM.")
        sys.exit(1)

    log_step("Starting VM...")
    dom.create()

    open_virt_manager()

    log_step("VM booted with CachyOS ISO. Install CachyOS through the GUI.")
    click.echo()
    click.echo("  After installation:")
    click.echo("    1. Reboot into the installed system")
    click.echo("    2. Mount the shared repo inside the VM:")
    click.echo("         sudo mount -t 9p -o trans=virtio system-ai /mnt/system-ai")
    click.echo("    3. Snapshot the clean state:")
    click.echo(f"         python {SCRIPT_DIR}/vm.py snapshot")


@cli.command()
@click.argument("name", default="clean")
def snapshot(name):
    """Take a named snapshot (default: 'clean')."""
    conn = connect()
    dom = require_vm(conn)

    snap_xml = f"""<domainsnapshot>
  <name>{name}</name>
  <description>CachyOS test VM — {name}</description>
</domainsnapshot>"""

    dom.snapshotCreateXML(snap_xml)
    log_step(f"Snapshot '{name}' created.")


@cli.command()
def start():
    """Boot the VM and open virt-manager."""
    conn = connect()
    dom = require_vm(conn)

    if dom.isActive():
        log_warn("VM is already running.")
    else:
        dom.create()
        log_step("VM started.")

    open_virt_manager()


@cli.command()
def stop():
    """Gracefully shut down the VM."""
    conn = connect()
    dom = require_vm(conn)

    if not dom.isActive():
        log_warn("VM is not running.")
        return

    dom.shutdown()
    log_step("Shutdown signal sent. Waiting...")

    for _ in range(30):
        time.sleep(1)
        # Re-fetch state
        if not dom.isActive():
            log_step("VM stopped.")
            return

    log_warn("VM still running after 30s. Use 'destroy' to force stop, or wait.")


@cli.command()
def ssh():
    """SSH into the VM."""
    conn = connect()
    dom = require_vm(conn)

    if not dom.isActive():
        log_error("VM is not running.")
        sys.exit(1)

    ip = get_vm_ip(dom)
    if ip is None:
        log_error("Could not determine VM IP. Is the VM fully booted?")
        sys.exit(1)

    log_step(f"Connecting to {ip}...")
    sys.exit(subprocess.call(["ssh", f"phoenix@{ip}"]))


@cli.command()
@click.argument("name", default="clean")
def reset(name):
    """Revert to a snapshot and boot the VM."""
    conn = connect()
    dom = require_vm(conn)

    try:
        snap = dom.snapshotLookupByName(name)
    except libvirt.libvirtError:
        log_error(f"Snapshot '{name}' not found.")
        sys.exit(1)

    if dom.isActive():
        dom.destroy()  # force stop for revert

    dom.revertToSnapshot(snap)
    log_step(f"Reverted to snapshot '{name}'.")

    # revert may leave it stopped depending on snapshot type
    if not dom.isActive():
        dom.create()

    open_virt_manager()
    log_step("VM booted.")


@cli.command("destroy")
def destroy_vm():
    """Delete the VM, snapshots, and disk image."""
    conn = connect()
    dom = require_vm(conn)

    if not click.confirm(f"Delete VM '{VM_CONFIG['name']}' and all its data?"):
        return

    if dom.isActive():
        dom.destroy()

    # Delete all snapshots
    try:
        snap_names = dom.snapshotListNames()
        for snap_name in snap_names:
            snap = dom.snapshotLookupByName(snap_name)
            snap.delete()
    except libvirt.libvirtError:
        pass

    dom.undefineFlags(
        libvirt.VIR_DOMAIN_UNDEFINE_NVRAM
        | libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
    )

    disk_path = VM_CONFIG["disk_path"]
    if disk_path.exists():
        disk_path.unlink()
        log_step(f"Deleted {disk_path}")

    nvram_path = VM_CONFIG["nvram_path"]
    if nvram_path.exists():
        nvram_path.unlink()
        log_step(f"Deleted {nvram_path}")

    log_step("VM destroyed.")


if __name__ == "__main__":
    cli()
