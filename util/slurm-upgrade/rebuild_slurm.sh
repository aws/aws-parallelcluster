#!/bin/bash
#
# Core step of a Slurm upgrade on an AWS ParallelCluster node: build the new release and swap it into
# /opt/slurm. It does not stop or start any daemon, and it does not stop the compute or login nodes.
#
# Run it as root, only after you have stopped the compute fleet and the Slurm daemons,
# and taken your backups. See the wiki page for the surrounding steps.

set -euo pipefail

SLURM_VERSION_NEW="${SLURM_VERSION_NEW:-slurm-25-11-8-1}"

readonly SOURCE_URL="${SLURM_SOURCE_URL:-https://github.com/SchedMD/slurm/archive/${SLURM_VERSION_NEW}.tar.gz}"

readonly PREFIX="/opt/slurm"
readonly CACHE_DIR="/etc/chef/local-mode-cache/cache"
readonly SOURCE_DIR="${CACHE_DIR}/slurm-${SLURM_VERSION_NEW}"
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail "Run this script as root"
[[ -d "${CACHE_DIR}" ]] || fail "The Chef cache directory ${CACHE_DIR} does not exist"
systemctl is-active --quiet slurmctld.service &&
    fail "slurmctld is still running. Stop the Slurm daemons before running this script."
systemctl is-active --quiet slurmdbd.service &&
    fail "slurmdbd is still running. Stop the Slurm daemons before running this script."

current_version=""
for binary in "${PREFIX}/sbin/slurmctld" "${PREFIX}/sbin/slurmdbd"; do
    [[ -x "${binary}" ]] || continue
    current_version="$("${binary}" -V 2>/dev/null |
        awk 'match($0, /[0-9]+\.[0-9]+\.[0-9]+/) { print substr($0, RSTART, RLENGTH); exit }' || true)"
    if [[ -n "${current_version}" ]]; then
        break
    fi
done
[[ -n "${current_version}" ]] || fail "Unable to determine the installed Slurm version"
log "Installed Slurm version: ${current_version}"

# The Chef cache holds the source tree the running version was built from, and its Makefile is what can uninstall that version cleanly.
current_source_dirs=()
while IFS= read -r line; do current_source_dirs+=("${line}"); done < <(
    find "${CACHE_DIR}" -mindepth 1 -maxdepth 1 -type d -name "slurm-slurm-${current_version//./-}-*"
)
((${#current_source_dirs[@]} == 1)) ||
    fail "Expected one source directory for Slurm ${current_version} under ${CACHE_DIR}, found ${#current_source_dirs[@]}"
current_source_dir="${current_source_dirs[0]}"
[[ -f "${current_source_dir}/Makefile" ]] || fail "${current_source_dir}/Makefile is missing"

# Build before uninstalling anything: a build failure then leaves the existing installation intact.
log "Downloading and building Slurm ${SLURM_VERSION_NEW}"
rm -rf "${SOURCE_DIR}"
curl --fail --location --silent --show-error --retry 3 \
    --output "${CACHE_DIR}/${SLURM_VERSION_NEW}.tar.gz" "${SOURCE_URL}"
gzip --test "${CACHE_DIR}/${SLURM_VERSION_NEW}.tar.gz" || fail "The downloaded archive is not a valid gzip archive"
tar -xf "${CACHE_DIR}/${SLURM_VERSION_NEW}.tar.gz" -C "${CACHE_DIR}"
[[ -d "${SOURCE_DIR}" ]] || fail "Expected the extracted source directory ${SOURCE_DIR}"

# The build toolchain ParallelCluster used for the shipped build lives in the cookbook virtual environment.
activate_paths=()
while IFS= read -r line; do activate_paths+=("${line}"); done < <(
    find /opt/parallelcluster/pyenv -type f -path '*/cookbook_virtualenv/bin/activate'
)
((${#activate_paths[@]} == 1)) || fail "Expected exactly one cookbook virtual environment"
# shellcheck disable=SC1090
source "${activate_paths[0]}"

(
    cd "${SOURCE_DIR}"
    # These are the same flags ParallelCluster builds the shipped Slurm with. Dropping any of them silently
    # removes a feature the cluster depends on, for example PMIx support or slurmrestd.
    ./configure --prefix="${PREFIX}" --with-pmix=/opt/pmix --with-jwt=/opt/libjwt --enable-slurmrestd
    make -j "$(getconf _NPROCESSORS_ONLN)"
)

log "Uninstalling Slurm ${current_version} and installing ${SLURM_VERSION_NEW}"
# make uninstall and make install do not touch ${PREFIX}/etc, so the cluster configuration is preserved.
make -C "${current_source_dir}" uninstall
(
    cd "${SOURCE_DIR}"
    make install
    make install-contrib
)
command -v deactivate >/dev/null 2>&1 && deactivate
ldconfig

log "Installed Slurm version is now $("${PREFIX}/sbin/slurmctld" -V)"
log "Start the Slurm daemons as described in the wiki, slurmdbd first."
