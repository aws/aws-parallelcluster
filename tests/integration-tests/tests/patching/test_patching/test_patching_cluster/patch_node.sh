#!/bin/bash
#
# Patching script.
#
# Applies OS package updates using the native package manager, in one of two
# flavours (mandatory first argument):
#
#   minimal: apply only the available *security* patches (smallest set).
#   full:    apply all available package updates (comprehensive upgrade).
#
# Kernel packages are intentionally NOT excluded in either flavour: if an update
# requires a newer kernel, the bump is accepted. A reboot after this script runs
# is required to activate a new kernel.
#
# Usage: patch_node.sh <minimal|full>
#
# Supports dnf (AL2023/RHEL9/Rocky9), yum (AL2/RHEL8) and apt (Ubuntu).
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "ERROR: missing mandatory patching flavour argument (minimal|full)" >&2
    exit 1
fi
FLAVOUR="$1"
if [[ "${FLAVOUR}" != "minimal" && "${FLAVOUR}" != "full" ]]; then
    echo "ERROR: invalid patching flavour '${FLAVOUR}', expected 'minimal' or 'full'" >&2
    exit 1
fi

echo "===== Starting system ${FLAVOUR} patching on $(hostname) ====="
# Report the running kernel before patching. The kernel after the reboot is
# reported separately once the node has rebooted (the reboot is mandatory to
# activate any new kernel).
echo "Kernel before patching: $(uname -r)"

if command -v dnf >/dev/null 2>&1; then
    echo "Detected dnf package manager"
    sudo dnf clean all
    sudo dnf makecache --refresh || true
    if [[ "${FLAVOUR}" == "minimal" ]]; then
        # Apply only security errata. Kernel packages are allowed to be upgraded.
        sudo dnf upgrade --security -y
    else
        # Apply all available package updates.
        sudo dnf upgrade -y
    fi
elif command -v yum >/dev/null 2>&1; then
    echo "Detected yum package manager"
    sudo yum clean all
    sudo yum makecache || true
    if [[ "${FLAVOUR}" == "minimal" ]]; then
        # update-minimal --security applies the smallest set of security errata.
        # Kernel bumps are allowed (no --exclude=kernel*).
        sudo yum update-minimal --security -y
    else
        # Apply all available package updates.
        sudo yum update -y
    fi
elif command -v apt-get >/dev/null 2>&1; then
    echo "Detected apt package manager"
    # Make apt non-interactive so no prompt blocks the upgrade (under a PTY with no
    # operator, any prompt would hang until the caller's timeout kills the command).
    # DEBIAN_FRONTEND is passed *through* sudo, which resets the environment by default,
    # so an exported var alone would not reach the root apt-get process.
    _envars=(DEBIAN_FRONTEND=noninteractive)
    sudo "${_envars[@]}" apt-get update -y
    if [[ "${FLAVOUR}" == "minimal" ]]; then
        # unattended-upgrades applies only the security pocket by default and will
        # upgrade linux-image-* (kernel) packages when needed.
        sudo "${_envars[@]}" apt-get install -y unattended-upgrades
        sudo "${_envars[@]}" unattended-upgrade -v
    else
        # Apply all available package updates, including kernel packages.
        sudo "${_envars[@]}" apt-get upgrade -y
    fi
else
    echo "ERROR: no supported package manager found (dnf/yum/apt-get)" >&2
    exit 1
fi

echo "===== System ${FLAVOUR} patching completed on $(hostname) ====="
