# VM Test Environment — Alternatives

Reference for other approaches we considered, in case the current setup (libvirt + virt-manager + Python CLI) needs to change.

## Current: libvirt + virt-manager + Python CLI

- **Pros:** Native Linux stack, GUI via virt-manager, simple snapshot/reset with virsh, no extra abstraction layers
- **Cons:** Manual CachyOS install required once, Linux-only

## Alternative 1: Vagrant + vagrant-libvirt

Vagrant wraps libvirt and provides `vagrant up` / `vagrant destroy` / `vagrant ssh`.

- **Pros:** Standard workflow familiar to many devs, `.box` files are portable
- **Cons:** No official CachyOS box (must build one), vagrant-libvirt plugin can be finicky to install, adds a Ruby dependency, less control over VM XML config
- **When to switch:** If you need to share the test environment with others or want `Vagrantfile`-as-code portability

## Alternative 2: VirtualBox

Cross-platform hypervisor with its own GUI.

- **Pros:** Works on macOS/Windows/Linux, well-documented, Vagrant has first-class VirtualBox support
- **Cons:** Slower than KVM, kernel module conflicts with KVM, no nested virt on AMD without patches, Oracle licensing concerns
- **When to switch:** If you need to test on a non-Linux host

## Alternative 3: GNOME Boxes

Simple libvirt frontend focused on ease of use.

- **Pros:** Very simple UI, auto-downloads ISOs, integrates with GNOME
- **Cons:** Limited snapshot management, less control than virt-manager, no scripting interface
- **When to switch:** If virt-manager feels too complex for casual use

## Alternative 4: Headless QEMU + VNC/SPICE

Run QEMU directly without libvirt, expose display via VNC or SPICE socket.

- **Pros:** No libvirtd dependency, connect from any VNC client or `remote-viewer`, works over SSH tunnels
- **Cons:** Manual QEMU command lines are verbose, no snapshot management layer, need to manage networking yourself
- **When to switch:** If you want remote access to the VM display from another machine, or if libvirtd is causing issues

## Alternative 5: systemd-nspawn / containers

Lightweight OS-level virtualization (not a full VM).

- **Pros:** Near-native performance, instant boot, trivial snapshot via btrfs subvolumes
- **Cons:** Shares host kernel (can't test different kernels/bootloaders), no GUI desktop testing, CachyOS kernel patches not testable
- **When to switch:** If you only need to test package installation and config file placement, not the full desktop experience
