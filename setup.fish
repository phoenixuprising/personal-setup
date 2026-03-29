#!/usr/bin/env fish
# CachyOS Desktop Setup Script
# Replicates phoenix's machine configuration
#
# Usage: Run each step individually or the whole script.
# Requires: Fresh CachyOS install with Niri desktop selected.
#
# IMPORTANT: Review hardware-specific packages before running!
# This was captured from an Intel Ultra 9 275HX + RTX 5070 Ti Mobile laptop.
# Adjust GPU/driver packages for your target hardware.

set -g SCRIPT_DIR (dirname (status filename))

# ─── Colors ───
set -g GREEN  (set_color green)
set -g YELLOW (set_color yellow)
set -g RED    (set_color red)
set -g RESET  (set_color normal)

function log_step
    echo "$GREEN▶ $argv[1]$RESET"
end

function log_warn
    echo "$YELLOW⚠ $argv[1]$RESET"
end

function log_error
    echo "$RED✗ $argv[1]$RESET"
end

# ─── Step 1: Install native (pacman) packages ───
function step_install_native
    log_step "Installing native packages via pacman..."
    set -l pkgs (cat $SCRIPT_DIR/packages-native.txt | string trim | string match -rv '^\s*$')
    if test (count $pkgs) -eq 0
        log_error "No packages found in packages-native.txt"
        return 1
    end
    log_warn "Review packages-native.txt first — GPU/driver packages may differ for your hardware."
    log_warn "Hardware-specific packages to check: nvidia-*, intel-*, lib32-nvidia-*, lib32-vulkan-intel, vpl-gpu-rt, linux-cachyos-nvidia-open, linux-cachyos-lts-nvidia-open"
    echo ""
    read -P "Continue installing "(count $pkgs)" native packages? [y/N] " confirm
    if test "$confirm" != y -a "$confirm" != Y
        log_warn "Skipped native package install."
        return 0
    end
    sudo pacman -S --needed $pkgs
end

# ─── Step 2: Install AUR packages ───
function step_install_aur
    log_step "Installing AUR packages via yay..."
    set -l pkgs (cat $SCRIPT_DIR/packages-aur.txt | string trim | string match -rv '^\s*$')
    if test (count $pkgs) -eq 0
        log_error "No packages found in packages-aur.txt"
        return 1
    end
    echo "AUR packages: $pkgs"
    read -P "Continue installing "(count $pkgs)" AUR packages? [y/N] " confirm
    if test "$confirm" != y -a "$confirm" != Y
        log_warn "Skipped AUR package install."
        return 0
    end
    yay -S --needed $pkgs
end

# ─── Step 3: Enable system services ───
function step_enable_system_services
    log_step "Enabling system services..."
    set -l services (cat $SCRIPT_DIR/services-system.txt | string trim | string match -rv '^\s*$')
    for svc in $services
        # Skip getty@ and other template instances that are default
        if string match -q 'getty@*' $svc
            continue
        end
        echo "  Enabling $svc"
        sudo systemctl enable $svc
    end
    log_step "System services enabled."
end

# ─── Step 4: Enable user services ───
function step_enable_user_services
    log_step "Enabling user services..."
    set -l services (cat $SCRIPT_DIR/services-user.txt | string trim | string match -rv '^\s*$')
    for svc in $services
        echo "  Enabling $svc"
        systemctl --user enable $svc
    end
    log_step "User services enabled."
end

# ─── Step 5: Install uv tools ───
function step_install_uv_tools
    log_step "Installing uv tools..."
    if not command -q uv
        log_error "uv not found — install it first (should be in native packages)."
        return 1
    end
    uv tool install forgetful-ai
    uv tool install jcodemunch-mcp
    log_step "uv tools installed."
end

# ─── Step 6: Apply chezmoi dotfiles ───
function step_apply_chezmoi
    log_step "Applying chezmoi dotfiles..."
    if not command -q chezmoi
        log_error "chezmoi not found — install chezmoi-git from AUR first."
        return 1
    end

    # Initialize chezmoi from the bundled source
    set -l chezmoi_src $SCRIPT_DIR/chezmoi-source
    if not test -d $chezmoi_src
        log_error "chezmoi-source/ directory not found in repo."
        return 1
    end

    # Copy source to chezmoi's expected location
    set -l chezmoi_dir ~/.local/share/chezmoi
    if test -d $chezmoi_dir
        log_warn "Chezmoi source dir already exists at $chezmoi_dir"
        read -P "Overwrite? [y/N] " confirm
        if test "$confirm" != y -a "$confirm" != Y
            log_warn "Skipped chezmoi setup."
            return 0
        end
        rm -rf $chezmoi_dir
    end

    mkdir -p (dirname $chezmoi_dir)
    cp -r $chezmoi_src $chezmoi_dir

    # Initialize git in chezmoi source
    cd $chezmoi_dir
    git init
    git add -A
    git commit -m "Initial chezmoi source from personal-setup"
    cd -

    # Preview then apply
    log_step "Previewing chezmoi changes..."
    chezmoi diff
    echo ""
    read -P "Apply chezmoi dotfiles? [y/N] " confirm
    if test "$confirm" != y -a "$confirm" != Y
        log_warn "Skipped chezmoi apply. Run 'chezmoi apply' manually when ready."
        return 0
    end
    chezmoi apply
    log_step "Chezmoi dotfiles applied."
end

# ─── Step 7: Set hostname ───
function step_set_hostname
    log_step "Setting hostname..."
    set -l current (hostname)
    echo "  Current hostname: $current"
    read -P "Set hostname to polaris-1? [y/N] or type a different name: " choice
    switch $choice
        case y Y
            sudo hostnamectl set-hostname polaris-1
            log_step "Hostname set to polaris-1."
        case n N ''
            log_warn "Skipped hostname setup."
        case '*'
            sudo hostnamectl set-hostname $choice
            log_step "Hostname set to $choice."
    end
end

# ─── Step 8: Set default shell to fish ───
function step_set_fish_shell
    log_step "Setting default shell to fish..."
    if test $SHELL = /usr/bin/fish
        log_step "Fish is already the default shell."
        return 0
    end
    chsh -s /usr/bin/fish
    log_step "Default shell set to fish. Log out and back in for it to take effect."
end

# ─── Step 9: Apply system configs ───
function step_apply_system_configs
    log_step "Applying system configuration files..."
    set -l sysconf $SCRIPT_DIR/system-config
    if not test -d $sysconf
        log_error "system-config/ directory not found in repo."
        return 1
    end

    # mkinitcpio
    if test -f $sysconf/mkinitcpio.conf
        log_warn "Will overwrite /etc/mkinitcpio.conf"
        read -P "Apply mkinitcpio.conf? [y/N] " confirm
        if test "$confirm" = y -o "$confirm" = Y
            sudo cp $sysconf/mkinitcpio.conf /etc/mkinitcpio.conf
            sudo mkinitcpio -P
        end
    end

    # locale
    for f in locale.conf vconsole.conf
        if test -f $sysconf/$f
            echo "  Copying $f"
            sudo cp $sysconf/$f /etc/$f
        end
    end

    # limine bootloader
    if test -f $sysconf/limine.conf
        log_warn "Will overwrite /boot/limine.conf"
        read -P "Apply limine.conf? [y/N] " confirm
        if test "$confirm" = y -o "$confirm" = Y
            sudo cp $sysconf/limine.conf /boot/limine.conf
        end
    end

    # UFW rules
    if test -d $sysconf/ufw
        log_warn "Will overwrite /etc/ufw/ rules"
        read -P "Apply UFW rules? [y/N] " confirm
        if test "$confirm" = y -o "$confirm" = Y
            sudo cp $sysconf/ufw/*.rules /etc/ufw/
            sudo ufw reload
        end
    end

    log_step "System configs applied."
end

# ─── Step 10: Post-install reminders ───
function step_post_install
    log_step "Post-install checklist:"
    echo "  1. Log in to 1Password:  1password --setup"
    echo "  2. Log in to Firefox / Chrome / Floorp and sync"
    echo "  3. Log in to Spotify (spotifyd + spotify-player)"
    echo "  4. Log in to Signal Desktop"
    echo "  5. Set up SSH keys (check ~/.ssh/config applied by chezmoi)"
    echo "  6. Configure KDE Connect on phone"
    echo "  7. Set up Git credentials:  git config --global credential.helper store"
    echo "  8. Configure snapper for btrfs snapshots:"
    echo "       sudo snapper -c root create-config /"
    echo "  9. Review /etc/fstab — this machine uses btrfs subvolumes:"
    echo "       @      → /"
    echo "       @home  → /home"
    echo "       @root  → /root"
    echo "       @srv   → /srv"
    echo "       @cache → /var/cache"
    echo "       @tmp   → /var/tmp"
    echo "       @log   → /var/log"
    echo "       Options: defaults,noatime,compress=zstd:1"
    echo "  10. Set up UFW firewall rules:"
    echo "       sudo ufw default deny incoming"
    echo "       sudo ufw default allow outgoing"
    echo "       sudo ufw enable"
    echo ""
    log_step "Done! Reboot when ready."
end

# ─── Main ───
function main
    echo ""
    echo "╔══════════════════════════════════════════╗"
    echo "║    CachyOS Desktop Setup — phoenix       ║"
    echo "╚══════════════════════════════════════════╝"
    echo ""
    echo "Steps:"
    echo "  1. Install native packages (pacman)"
    echo "  2. Install AUR packages (yay)"
    echo "  3. Enable system services"
    echo "  4. Enable user services"
    echo "  5. Install uv tools"
    echo "  6. Apply chezmoi dotfiles"
    echo "  7. Set hostname (polaris-1)"
    echo "  8. Set default shell to fish"
    echo "  9. Apply system configs"
    echo "  10. Post-install checklist"
    echo ""
    read -P "Run all steps? [y/N] or enter step number: " choice

    switch $choice
        case y Y
            step_install_native
            step_install_aur
            step_enable_system_services
            step_enable_user_services
            step_install_uv_tools
            step_apply_chezmoi
            step_set_hostname
            step_set_fish_shell
            step_apply_system_configs
            step_post_install
        case 1; step_install_native
        case 2; step_install_aur
        case 3; step_enable_system_services
        case 4; step_enable_user_services
        case 5; step_install_uv_tools
        case 6; step_apply_chezmoi
        case 7; step_set_hostname
        case 8; step_set_fish_shell
        case 9; step_apply_system_configs
        case 10; step_post_install
        case '*'
            log_warn "Invalid choice. Run with a step number (1-10) or 'y' for all."
    end
end

main
