#!/bin/bash
#
# Patching script.
#
# Applies all available *security* patches to the system using the native
# package manager. Kernel packages are intentionally NOT excluded: if a
# security fix requires a newer kernel, the bump is accepted. A reboot after
# this script runs is required to activate a new kernel.
#
# Supports dnf (AL2023/RHEL9/Rocky9), yum (AL2/RHEL8) and apt (Ubuntu).
set -euo pipefail

echo "===== Starting system security patching on $(hostname) ====="
# Report the running kernel before patching. The kernel after the reboot is
# reported separately once the node has rebooted (the reboot is mandatory to
# activate any new kernel).
echo "Kernel before patching: $(uname -r)"

if command -v dnf >/dev/null 2>&1; then
    echo "Detected dnf package manager"
    sudo dnf clean all
    sudo dnf makecache --refresh || true
    # Apply only security errata. Kernel packages are allowed to be upgraded.
    sudo dnf upgrade --security -y
elif command -v yum >/dev/null 2>&1; then
    echo "Detected yum package manager"
    sudo yum clean all
    sudo yum makecache || true
    # update-minimal --security applies the smallest set of security errata.
    # Kernel bumps are allowed (no --exclude=kernel*).
    sudo yum update-minimal --security -y
elif command -v apt-get >/dev/null 2>&1; then
    echo "Detected apt package manager"
    export DEBIAN_FRONTEND=noninteractive
    sudo apt-get update -y
    # unattended-upgrades applies only the security pocket by default and will
    # upgrade linux-image-* (kernel) packages when needed.
    sudo apt-get install -y unattended-upgrades
    sudo unattended-upgrade -v
else
    echo "ERROR: no supported package manager found (dnf/yum/apt-get)" >&2
    exit 1
fi

echo "===== System security patching completed on $(hostname) ====="
