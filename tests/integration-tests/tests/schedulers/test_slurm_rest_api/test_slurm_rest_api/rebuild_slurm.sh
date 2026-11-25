#!/bin/bash
#
# OnNodeStart custom action for the test_slurm_rest_api integration test.
#
# Rebuilds the Slurm installation shipped with ParallelCluster adding the http-parser
# plugin so that slurmrestd is actually functional. Intentionally scoped to the build
# step only: no Slurm service is started, no configuration file is touched.
#
# Steps:
#   1. Uninstall the existing Slurm installation.
#   2. Install http-parser from local sources.
#   3. Reconfigure Slurm with `--with-http-parser=/usr/local/` and `--enable-slurmrestd`
#      and reinstall.

set -ex

LOG_PREFIX="[rebuild_slurm]"
SLURM_PREFIX="/opt/slurm"

function log() { echo "${LOG_PREFIX} $*"; }
function fail() { echo "${LOG_PREFIX} ERROR: $*" >&2; exit 1; }

# Find a single directory matching a pattern under a base path.
function find_dir() {
  local base="$1" depth="$2" pattern="$3"
  local result
  result=$(find "${base}" -maxdepth "${depth}" -type d -name "${pattern}" 2>/dev/null | head -n1)
  [ -n "${result}" ] || fail "${pattern} not found under ${base}"
  echo "${result}"
}

log "Capturing installed Slurm version before rebuild"
pre_rebuild_version=$(${SLURM_PREFIX}/sbin/slurmd --version | awk '{print $2}')
[ -n "${pre_rebuild_version}" ] || fail "Could not determine the Slurm version from slurmd"
log "Installed Slurm version before rebuild: ${pre_rebuild_version}"

slurm_src_dir=$(find_dir /etc/chef/local-mode-cache/cache 1 'slurm-slurm-*')
log "Using Slurm sources at ${slurm_src_dir}"

cd "${slurm_src_dir}"

COOKBOOK_VENV=$(find_dir /opt/parallelcluster/pyenv/versions 3 cookbook_virtualenv)

log "Activating cookbook virtualenv at ${COOKBOOK_VENV}"
source "${COOKBOOK_VENV}/bin/activate"

log "Uninstalling current Slurm installation"
make uninstall

# Install http-parser from local sources into /usr/lib64 (AL2023 only)
if grep -q "Amazon Linux 2023" /etc/os-release; then
  log "Installing http-parser from local sources"
  http_parser_src=$(find_dir /opt/parallelcluster/sources 1 'http-parser-*')
  log "Using http-parser sources at ${http_parser_src}"
  make -C "${http_parser_src}" PREFIX=/usr/local uninstall || true
  make -C "${http_parser_src}"
  make -C "${http_parser_src}" PREFIX=/usr LIBDIR=/usr/lib64 install
fi

log "Reconfiguring Slurm with http-parser and slurmrestd"
./configure --prefix=${SLURM_PREFIX} \
            --with-pmix=/opt/pmix \
            --with-jwt=/opt/libjwt \
            --with-http-parser=/usr \
            --enable-slurmrestd

CORES=$(grep -c ^processor /proc/cpuinfo)
log "Rebuilding Slurm using ${CORES} cores"
make -j "${CORES}"
make install
make install-contrib

deactivate

# Sanity-check that the http-parser plugin is now linked against libhttp_parser.
ldd ${SLURM_PREFIX}/lib/slurm/http_parser_libhttp_parser.so | grep http_parser

# Sanity-check that the rebuild installed the exact same Slurm version.
log "Verifying the rebuilt Slurm version matches the source version"
post_rebuild_version=$(${SLURM_PREFIX}/sbin/slurmd --version | awk '{print $2}')
[ "${post_rebuild_version}" = "${pre_rebuild_version}" ] || fail "Slurm version mismatch after rebuild: before=${pre_rebuild_version} after=${post_rebuild_version}"
log "Slurm ${post_rebuild_version} reinstalled successfully"