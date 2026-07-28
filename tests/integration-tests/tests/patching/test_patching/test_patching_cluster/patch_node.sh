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

# Recover the rpmdb in case a previously killed process left it corrupted (stale
# Berkeley DB locks on EL8/AL2 cause "rpmdb open failed" on every rpm/dnf/yum call).
# Gated on a probe query: if the rpmdb is usable, recovery is skipped entirely.
fix_rpmdb() {
    sudo rpm -q rpm >/dev/null 2>&1 && return 0
    echo "rpmdb is broken, rebuilding it"
    sudo rm -f /var/lib/rpm/__db.*
    sudo rpm --rebuilddb
}

# On RHEL/Rocky the AMI's aws-fsx repo is pinned to the minor release it was built on, so a
# patching kernel bump leaves no matching lustre kmod and FSx mounts fail after reboot..
# Before the reboot, and targeting the kernel about to boot, re-point the repo
# at the new minor and upgrade the client to that minor's newest build. 
# If the upgrade no-ops (same version, different .ko) reinstall to swap the module, 
# then fail if none resolves for the new kernel.
# https://docs.aws.amazon.com/fsx/latest/LustreGuide/install-lustre-client.html
refresh_lustre_client() {
    [[ -f /etc/yum.repos.d/aws-fsx.repo ]] || return 0
    local new_kernel
    new_kernel=$(rpm -q kernel --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort -V | tail -n1)
    modinfo -k "${new_kernel}" lustre >/dev/null 2>&1 && return 0
    sudo sed -i -E "s#(/el/)[0-9]+(\.[0-9]+)?#\1$(. /etc/os-release && echo "${VERSION_ID}")#" /etc/yum.repos.d/aws-fsx.repo
    sudo dnf clean metadata
    sudo dnf upgrade -y kmod-lustre-client lustre-client
    modinfo -k "${new_kernel}" lustre >/dev/null 2>&1 \
        || sudo dnf reinstall -y kmod-lustre-client lustre-client || true
    modinfo -k "${new_kernel}" lustre >/dev/null 2>&1 \
        || { echo "ERROR: no FSx Lustre client available for kernel ${new_kernel}" >&2; exit 1; }
}

echo "===== Starting system ${FLAVOUR} patching on $(hostname) ====="
# Report the running kernel before patching. The kernel after the reboot is
# reported separately once the node has rebooted (the reboot is mandatory to
# activate any new kernel).
echo "Kernel before patching: $(uname -r)"

if command -v dnf >/dev/null 2>&1; then
    echo "Detected dnf package manager"
    fix_rpmdb
    sudo dnf clean all
    sudo dnf makecache --refresh -y  || true
    if [[ "${FLAVOUR}" == "minimal" ]]; then
        # Apply only security errata. Kernel packages are allowed to be upgraded.
        sudo dnf upgrade --security -y
    else
        # Apply all available package updates.
        sudo dnf upgrade -y
    fi
elif command -v yum >/dev/null 2>&1; then
    echo "Detected yum package manager"
    fix_rpmdb
    sudo yum clean all
    sudo yum makecache -y || true
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

# The pinned-repo kmod mismatch is a RHEL/Rocky-only problem; AL2023 and Ubuntu get their
# Lustre client from non-pinned channels, so only run the fix-up there.
if [[ "$(. /etc/os-release && echo "${ID}")" =~ ^(rhel|rocky)$ ]]; then
    refresh_lustre_client
fi

echo "===== System ${FLAVOUR} patching completed on $(hostname) ====="
