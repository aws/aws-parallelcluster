#!/bin/bash
# Rebuild the Pyxis SPANK plugin against the Slurm currently installed in /opt/slurm.
#
# Slurm version-stamps every plugin it loads and refuses one built for a different major release, and it does so
# before resolving any symbol. Because a plugstack load failure aborts plugin stack initialisation, a stale
# spank_pyxis.so does not merely break containerised jobs: every srun and sbatch on the cluster fails. So a
# cross-major Slurm upgrade requires rebuilding Pyxis, exactly as it requires rebuilding any other SPANK plugin.
#
# The plugin shipped in the ParallelCluster AMI lives in /usr/local/lib/slurm, which is each node's local root
# volume. Rebuilding there would only fix the node we run on, and every compute node launched afterwards would
# come up from the AMI with the stale plugin again. This script therefore installs the rebuilt plugin under
# /opt/slurm, which is NFS-exported to the whole cluster, and repoints plugstack.conf.d/pyxis.conf at it; the
# stale copy is left untouched and simply stops being referenced.

set -euo pipefail

readonly SLURM_PREFIX="${SLURM_PREFIX:-/opt/slurm}"
readonly SPANK_LIB_DIR="${SLURM_PREFIX}/lib/spank"
readonly SPANK_LIB="${SPANK_LIB_DIR}/spank_pyxis.so"
readonly PYXIS_CONF="${SLURM_PREFIX}/etc/plugstack.conf.d/pyxis.conf"
# The cookbook downloads the Pyxis source archive to this directory and leaves it there: the AMI keeps the sources
# of the dependencies it builds, and the image build reads their versions back from the file names. So the rebuild
# needs no download, which is also what makes it possible on a cluster without internet access.
readonly SOURCES_DIR="${SOURCES_DIR:-/opt/parallelcluster/sources}"
# ParallelCluster 3.16.0 ships Pyxis 0.24.0; older releases ship 0.20.0, which predates the SPANK API of the
# Slurm release we upgrade to. The archive in the AMI is used when it is at least this version, and downloaded
# otherwise.
readonly PYXIS_MIN_VERSION="0.24.0"
readonly PYXIS_VERSION="${PYXIS_VERSION:-${PYXIS_MIN_VERSION}}"
readonly PYXIS_URL="${PYXIS_URL:-https://github.com/NVIDIA/pyxis/archive/refs/tags/v${PYXIS_VERSION}.tar.gz}"
readonly BUILD_DIR="/opt/parallelcluster/tmp/pyxis-rebuild"

log() {
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
    log "ERROR: $*" >&2
    exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "Run this script as root"
[[ -f "${SLURM_PREFIX}/include/slurm/spank.h" ]] || \
    fail "Slurm SPANK headers are missing from ${SLURM_PREFIX}/include/slurm; nothing to build against"
[[ -f "${PYXIS_CONF}" ]] || fail "Expected the Pyxis plugstack configuration at ${PYXIS_CONF}"

log "Slurm headers found at ${SLURM_PREFIX}/include/slurm/spank.h"
log "Pyxis plugstack configuration before the rebuild: $(cat "${PYXIS_CONF}")"

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

# The newest archive the AMI shipped, if any. Nothing prunes this directory, so a node that has been through more
# than one cookbook run can hold several of them.
local_archive="$(find "${SOURCES_DIR}" -maxdepth 1 -type f -name 'pyxis-*.tar.gz' 2>/dev/null | sort -V | tail -n 1)"
if [[ -n "${local_archive}" ]]; then
    local_version="$(basename "${local_archive}")"
    local_version="${local_version#pyxis-}"
    local_version="${local_version%.tar.gz}"
    # sort -V puts the lower version first, so the minimum coming first means the local archive is new enough.
    if [[ "$(printf '%s\n%s\n' "${PYXIS_MIN_VERSION}" "${local_version}" | sort -V | head -n 1)" \
        != "${PYXIS_MIN_VERSION}" ]]; then
        log "The archive in ${SOURCES_DIR} is Pyxis ${local_version}, older than ${PYXIS_MIN_VERSION}, ignoring it"
        local_archive=""
    fi
fi

if [[ -n "${local_archive}" ]]; then
    pyxis_version="${local_version}"
    log "Building Pyxis ${pyxis_version} from the archive the AMI shipped: ${local_archive}"
    tar -xf "${local_archive}" -C "${BUILD_DIR}" --strip-components=1
else
    pyxis_version="${PYXIS_VERSION}"
    log "Downloading Pyxis ${pyxis_version} from ${PYXIS_URL}"
    curl --fail --location --silent --show-error --connect-timeout 10 --max-time 600 --retry 3 \
        --output "${BUILD_DIR}/pyxis.tar.gz" "${PYXIS_URL}"
    tar -xf "${BUILD_DIR}/pyxis.tar.gz" -C "${BUILD_DIR}" --strip-components=1
fi

log "Building Pyxis against ${SLURM_PREFIX}"
# CPPFLAGS is passed through the environment, which is how upstream documents pointing the build at a Slurm in a
# non-standard prefix. A command-line `make CPPFLAGS=...` assignment would instead override the flags the Pyxis
# Makefile appends to it.
CPPFLAGS="-I${SLURM_PREFIX}/include" make -C "${BUILD_DIR}" -j "$(getconf _NPROCESSORS_ONLN)"

# Locate the artefact rather than trusting the upstream install target, whose layout is not part of any
# interface we control.
built_lib="$(find "${BUILD_DIR}" -name 'spank_pyxis.so' -type f -print -quit)"
[[ -n "${built_lib}" ]] || fail "The Pyxis build produced no spank_pyxis.so"

install -d -m 755 "${SPANK_LIB_DIR}"
install -m 755 "${built_lib}" "${SPANK_LIB}"
log "Installed ${built_lib} as ${SPANK_LIB}"

# Replace only the path, so that any option the AMI configured on the line (runtime_path, container_scope, ...)
# survives the rewrite.
sed -i -E "s#[^[:space:]]*spank_pyxis\.so#${SPANK_LIB}#" "${PYXIS_CONF}"
grep -qF "${SPANK_LIB}" "${PYXIS_CONF}" || fail "Failed to repoint ${PYXIS_CONF} at ${SPANK_LIB}"
log "Pyxis plugstack configuration after the rebuild: $(cat "${PYXIS_CONF}")"

# slurmd and srun read plugstack.conf when they launch a step, so no daemon restart is needed; reconfigure only
# so that the change is visible in the controller logs alongside the rest of the upgrade.
# Absolute path because sudo resets PATH through secure_path, which does not include ${SLURM_PREFIX}/bin.
"${SLURM_PREFIX}/bin/scontrol" reconfigure

rm -rf "${BUILD_DIR}"
log "Successfully rebuilt Pyxis ${pyxis_version} against the installed Slurm"
