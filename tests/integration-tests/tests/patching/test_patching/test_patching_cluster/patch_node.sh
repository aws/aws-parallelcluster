#!/bin/bash
#
# Patching script.
#
# Applies OS package updates using the native package manager, in one of four
# flavours (mandatory first argument):
#
#   minimal:        apply only the available *security* patches (smallest set).
#   full:           apply all available package updates (comprehensive upgrade).
#   minimal-capped: like minimal, but cap the kernel (see below).
#   full-capped:    like full, but cap the kernel (see below).
#
# Kernel packages are NOT excluded: if an update requires a newer kernel, the bump is
# accepted. A reboot after this script runs is required to activate a new kernel.
#
# The "-capped" variants additionally constrain the kernel so it is never bumped past the
# newest version the FSx Lustre client supports, which prevents FSx mounts from breaking
# after reboot when the client lags the kernel. Capping applies on Ubuntu (per-kernel
# lustre-client-modules package) and RHEL/Rocky (minor-pinned FSx repo); AL2/AL2023 ship
# the Lustre module in-tree with the kernel, so there is nothing to cap there.
#
# Usage: patch_node.sh <minimal|full|minimal-capped|full-capped>
#
# Supports dnf (AL2023/RHEL9/Rocky9), yum (AL2/RHEL8) and apt (Ubuntu).
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "ERROR: missing mandatory patching flavour argument (minimal|full|minimal-capped|full-capped)" >&2
    exit 1
fi
FLAVOUR="$1"
case "${FLAVOUR}" in
    minimal | full | minimal-capped | full-capped) ;;
    *)
        echo "ERROR: invalid patching flavour '${FLAVOUR}', expected one of: minimal, full, minimal-capped, full-capped" >&2
        exit 1
        ;;
esac

BASE_FLAVOUR="${FLAVOUR%-capped}"
[[ "${FLAVOUR}" == *-capped ]] && CAPPED=true || CAPPED=false

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
refresh_lustre_client_rhel() {
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

# On Ubuntu the FSx Lustre client kernel module ships as a per-kernel package
# (lustre-client-modules-<uname-r>), so a patching kernel bump leaves no matching
# module for the new kernel about to boot.
# Before the reboot, install the target kernel's module package, mirroring the
# cookbook's Ubuntu lustre setup.
# See https://docs.aws.amazon.com/fsx/latest/LustreGuide/install-lustre-client.html
refresh_lustre_client_debian() {
    [[ -f /etc/apt/sources.list.d/fsxlustreclientrepo.list ]] || return 0
    local new_kernel
    new_kernel=$(dpkg-query -W -f='${Package}\n' 'linux-image-*-aws' 2>/dev/null \
        | sed 's/^linux-image-//' | grep -E '^[0-9]' | sort -V | tail -n1)
    modinfo -k "${new_kernel}" lustre >/dev/null 2>&1 && return 0
    sudo DEBIAN_FRONTEND=noninteractive apt-get update -y
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
        "lustre-client-modules-${new_kernel}" lustre-client-modules-aws || true
    modinfo -k "${new_kernel}" lustre >/dev/null 2>&1 \
        || { echo "ERROR: no FSx Lustre client available for kernel ${new_kernel}" >&2; exit 1; }
}

# Cap the kernel on Ubuntu (used only by the "-capped" flavours). The FSx Lustre client is a
# per-kernel package (lustre-client-modules-<uname-r>), so the newest such package is the
# highest kernel Lustre supports. Install exactly that kernel and hold the kernel
# meta-packages so neither the security nor the full upgrade can pull a newer one. Assumes
# the apt cache is already refreshed. No-op when FSx Lustre is not configured.
cap_kernel_debian() {
    [[ -f /etc/apt/sources.list.d/fsxlustreclientrepo.list ]] || return 0
    local cap
    cap=$(apt-cache pkgnames lustre-client-modules- \
        | sed -n 's/^lustre-client-modules-\([0-9].*-aws\)$/\1/p' | sort -V | tail -n1)
    [[ -n "${cap}" ]] || { echo "ERROR: could not determine the max FSx Lustre-supported kernel" >&2; exit 1; }
    echo "Capping kernel to the max FSx Lustre-supported version: ${cap}"
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
        "linux-image-${cap}" "linux-headers-${cap}" "linux-modules-${cap}" "linux-modules-extra-${cap}"
    sudo apt-mark hold linux-aws linux-image-aws linux-headers-aws
}

# Cap the kernel on RHEL/Rocky (used only by the "-capped" flavours). FSx publishes the
# Lustre kmod per EL minor (/el/<major>.<minor>/), so a kernel is supported only if FSx ships
# a repo for that kernel's minor. Cap to the newest available kernel whose minor FSx already
# publishes and version-lock it so the upgrade stops there. AL2/AL2023 ship the Lustre module
# in-tree with the kernel, so there is nothing to cap. No-op when FSx Lustre is not configured.
cap_kernel_dnf() {
    local id
    id=$(. /etc/os-release && echo "${ID}")
    if [[ ! "${id}" =~ ^(rhel|rocky)$ ]]; then
        echo "Kernel cap not applicable on '${id}' (in-tree Lustre module); skipping cap"
        return 0
    fi
    [[ -f /etc/yum.repos.d/aws-fsx.repo ]] || return 0
    local maj arch cap
    maj=$(. /etc/os-release && echo "${VERSION_ID%%.*}")
    arch=$(uname -m)
    cap=$(sudo dnf -q repoquery kernel --qf '%{version}-%{release}.%{arch}\n' 2>/dev/null | sort -rV | while read -r k; do
        minor=$(printf '%s' "${k}" | sed -n "s/.*\.el${maj}_\([0-9]\+\)\..*/\1/p")
        [[ -n "${minor}" ]] || continue
        if curl -fsL -o /dev/null "https://fsx-lustre-client-repo.s3.amazonaws.com/el/${maj}.${minor}/${arch}/repodata/repomd.xml"; then
            echo "${k}"
            break
        fi
    done || true)
    [[ -n "${cap}" ]] || { echo "ERROR: could not determine the max FSx Lustre-supported kernel" >&2; exit 1; }
    echo "Capping kernel to the max FSx Lustre-supported version: ${cap}"
    sudo dnf install -y python3-dnf-plugin-versionlock
    sudo dnf versionlock add "kernel-${cap}" "kernel-core-${cap}" "kernel-modules-${cap}"
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
    if [[ "${CAPPED}" == "true" ]]; then
        cap_kernel_dnf
    fi
    if [[ "${BASE_FLAVOUR}" == "minimal" ]]; then
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
    if [[ "${CAPPED}" == "true" ]]; then
        # The yum path is AL2, which ships the Lustre module in-tree/co-released with the
        # kernel (RHEL/Rocky use the dnf path). Nothing to cap here.
        echo "Kernel cap not applicable on this platform (in-tree/co-released Lustre); skipping cap"
    fi
    if [[ "${BASE_FLAVOUR}" == "minimal" ]]; then
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
    # dpkg conffile options: keep locally-modified config files (e.g. efs-utils.conf); without
    # them dpkg prompts and aborts on EOF (DEBIAN_FRONTEND=noninteractive does not cover this).
    _dpkg_opts=(-o Dpkg::Options::="--force-confold" -o Dpkg::Options::="--force-confdef")
    sudo "${_envars[@]}" apt-get update -y
    if [[ "${CAPPED}" == "true" ]]; then
        cap_kernel_debian
    fi
    if [[ "${BASE_FLAVOUR}" == "minimal" ]]; then
        # unattended-upgrades applies only the security pocket by default and will
        # upgrade linux-image-* (kernel) packages when needed.
        sudo "${_envars[@]}" apt-get install -y unattended-upgrades
        sudo "${_envars[@]}" unattended-upgrade -v
    else
        # Apply all available package updates, including kernel packages.
        sudo "${_envars[@]}" apt-get upgrade -y "${_dpkg_opts[@]}"
    fi
else
    echo "ERROR: no supported package manager found (dnf/yum/apt-get)" >&2
    exit 1
fi

# A patching kernel bump can leave the FSx Lustre client without a module matching
# the kernel about to boot, which breaks FSx mounts after the reboot. Refresh the
# client per-OS: RHEL/Rocky re-point the minor-pinned repo, Ubuntu installs the
# per-kernel module package. AL2/AL2023 pull Lustre from non-pinned channels that
# already track the kernel, so they need no fix-up.
case "$(. /etc/os-release && echo "${ID}")" in
    rhel | rocky) refresh_lustre_client_rhel ;;
    ubuntu) refresh_lustre_client_debian ;;
    *) : ;;
esac

echo "===== System ${FLAVOUR} patching completed on $(hostname) ====="
