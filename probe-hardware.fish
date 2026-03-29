#!/usr/bin/env fish
# Run this on the target machine to capture hardware info.
# Output: hardware-info.toml in the same directory as this script.

set -l SCRIPT_DIR (dirname (status filename))
set -l OUT "$SCRIPT_DIR/hardware-info.toml"

echo "Probing hardware..."

echo '# Hardware probe for CachyOS setup' > $OUT
echo "# Generated: "(date -Iseconds) >> $OUT
echo "" >> $OUT

# ─── CPU ───
echo "[cpu]" >> $OUT
set -l cpu_vendor (lscpu | grep 'Vendor ID' | awk -F: '{gsub(/^[ \t]+/, "", $2); print $2}')
set -l cpu_model (lscpu | grep 'Model name' | awk -F: '{gsub(/^[ \t]+/, "", $2); print $2}')
set -l cpu_cores (nproc)
echo "vendor = \"$cpu_vendor\"" >> $OUT
echo "model = \"$cpu_model\"" >> $OUT
echo "cores = $cpu_cores" >> $OUT
if string match -q '*AMD*' $cpu_vendor
    echo "microcode = \"amd-ucode\"" >> $OUT
else
    echo "microcode = \"intel-ucode\"" >> $OUT
end
echo "" >> $OUT

# ─── GPU ───
echo "[[gpu]]" >> $OUT
set -l gpu_lines (lspci | grep -iE 'VGA compatible|3D controller')
set -l gpu_index 0
for line in $gpu_lines
    if test $gpu_index -gt 0
        echo "" >> $OUT
        echo "[[gpu]]" >> $OUT
    end
    set -l pci_id (echo $line | awk '{print $1}')
    echo "pci_id = \"$pci_id\"" >> $OUT
    echo "description = \"$line\"" >> $OUT

    if string match -qi '*nvidia*' $line
        echo "vendor = \"nvidia\"" >> $OUT
        echo "driver_packages = [\"nvidia-utils\", \"nvidia-settings\", \"lib32-nvidia-utils\", \"opencl-nvidia\", \"lib32-opencl-nvidia\", \"libva-nvidia-driver\", \"egl-wayland\"]" >> $OUT
        # Check if it's a laptop (has both Intel/AMD + NVIDIA)
        if test (count $gpu_lines) -gt 1
            echo "hybrid = true" >> $OUT
            echo "hybrid_packages = [\"nvidia-prime\", \"supergfxctl\"]" >> $OUT
        else
            echo "hybrid = false" >> $OUT
        end
    else if string match -qi '*intel*' $line
        echo "vendor = \"intel\"" >> $OUT
        echo "driver_packages = [\"vulkan-intel\", \"lib32-vulkan-intel\", \"intel-media-driver\", \"vpl-gpu-rt\"]" >> $OUT
    else if string match -qi '*amd*' $line; or string match -qi '*radeon*' $line
        echo "vendor = \"amd\"" >> $OUT
        echo "driver_packages = [\"vulkan-radeon\", \"lib32-vulkan-radeon\", \"libva-mesa-driver\", \"lib32-libva-mesa-driver\"]" >> $OUT
    else
        echo "vendor = \"unknown\"" >> $OUT
        echo "driver_packages = []" >> $OUT
    end
    set gpu_index (math $gpu_index + 1)
end
echo "" >> $OUT

# ─── RAM ───
echo "[memory]" >> $OUT
set -l ram_kb (grep MemTotal /proc/meminfo | awk '{print $2}')
set -l ram_gb (math "round($ram_kb / 1048576)")
echo "total_gb = $ram_gb" >> $OUT
echo "" >> $OUT

# ─── Disks ───
set -l disk_index 0
for disk in (lsblk -dnpo NAME,SIZE,TYPE,ROTA,MODEL | grep ' disk ' | grep -v zram)
    set -l parts (string split ' ' -- (string trim $disk))
    set -l dname $parts[1]
    set -l dsize (lsblk -dnbo SIZE $dname | string trim)
    set -l dsize_gb (math "round($dsize / 1073741824)")
    set -l rotational (cat /sys/block/(basename $dname)/queue/rotational 2>/dev/null; or echo "?")
    set -l dmodel (lsblk -dnpo MODEL $dname | string trim)

    echo "[[disk]]" >> $OUT
    echo "device = \"$dname\"" >> $OUT
    echo "size_gb = $dsize_gb" >> $OUT
    if test "$rotational" = "0"
        echo "type = \"ssd\"" >> $OUT
    else if test "$rotational" = "1"
        echo "type = \"hdd\"" >> $OUT
    else
        echo "type = \"unknown\"" >> $OUT
    end
    echo "model = \"$dmodel\"" >> $OUT
    echo "" >> $OUT
    set disk_index (math $disk_index + 1)
end

# ─── Network ───
set -l nic_index 0
for iface in (command ls /sys/class/net | grep -v '^lo$')
    set -l itype "unknown"
    if test -d /sys/class/net/$iface/wireless
        set itype "wifi"
    else if test -e /sys/class/net/$iface/device
        set itype "ethernet"
    end
    echo "[[network]]" >> $OUT
    echo "interface = \"$iface\"" >> $OUT
    echo "type = \"$itype\"" >> $OUT
    set -l driver (readlink /sys/class/net/$iface/device/driver 2>/dev/null | xargs basename 2>/dev/null; or echo "unknown")
    echo "driver = \"$driver\"" >> $OUT
    echo "" >> $OUT
end

# ─── Motherboard ───
echo "[motherboard]" >> $OUT
set -l mb_vendor (cat /sys/class/dmi/id/board_vendor 2>/dev/null; or echo "unknown")
set -l mb_name (cat /sys/class/dmi/id/board_name 2>/dev/null; or echo "unknown")
set -l mb_version (cat /sys/class/dmi/id/board_version 2>/dev/null; or echo "unknown")
echo "vendor = \"$mb_vendor\"" >> $OUT
echo "name = \"$mb_name\"" >> $OUT
echo "version = \"$mb_version\"" >> $OUT
echo "" >> $OUT

# ─── System type ───
echo "[system]" >> $OUT
set -l chassis (hostnamectl --json=short 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('Chassis','unknown'))" 2>/dev/null; or echo "unknown")
echo "chassis = \"$chassis\"" >> $OUT
set -l firmware "unknown"
if test -d /sys/firmware/efi
    set firmware "uefi"
else
    set firmware "bios"
end
echo "firmware = \"$firmware\"" >> $OUT

echo ""
echo "Done. Hardware info written to: $OUT"
cat $OUT
