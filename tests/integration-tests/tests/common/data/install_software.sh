#!/bin/bash
# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Private integration-test installer for disposable AWS ParallelCluster 3.16.0 clusters.
# This follows the AWS ParallelCluster Slurm upgrade wiki procedure and is not for production use.
#
# Cross-major upgrades are supported, within the compatibility window Slurm documents at
# https://slurm.schedmd.com/upgrades.html. They are irreversible: slurmdbd converts the accounting database
# and slurmctld converts StateSaveLocation on first start, and a downgraded daemon refuses to read either.
#
# Structure: write_wiki_step_4_script() holds a verbatim copy of the script the wiki page publishes as Step 4, and
# run_wiki_step_4_script() runs it through the documented SLURM_VERSION_NEW and SLURM_SOURCE_URL interface, so the
# published script is what the integration tests exercise. Everything else in this file is the work the page leaves
# to the operator: detecting the host role and the Region, resolving the source archive for the partition, checking
# the compatibility window (page: Before you begin), stopping the daemons and the ParallelCluster managers (Step 2),
# taking the installation and state backups (Step 3), starting everything back with the accounting migration gated
# on slurmdbd being ready (Step 5) and validating the result (Step 7).
#
# Not covered here, and left to the pytest test that calls this installer: stopping and starting the compute fleet
# (Steps 1 and 6), the job, MPI and login-node checks (Step 7 items 4 and 6), scaling login nodes down (Appendix E),
# rebuilding plugins (Appendix B) and rolling back (Appendix D). The accounting database backup of Step 3.2 is not
# taken at all, because these clusters are disposable.

set -euo pipefail

readonly TARGET_SOURCE_NAME="slurm-25-11-8-1"
readonly TARGET_RUNTIME_VERSION="25.11.8"
readonly TARGET_MAJOR_VERSION="25.11"
# Majors that Slurm 25.11 can be upgraded from in place, newest first. Since 24.11 the window is the previous
# three majors. Keep this in sync with the target release: see the compatibility table in the upgrade guide.
readonly TARGET_COMPATIBLE_MAJORS="25.11 25.05 24.11 24.05"
readonly CACHE_DIR="/etc/chef/local-mode-cache/cache"
# Where the Step 4 script of the upgrade wiki page is written before it is run, under the name the page uses.
readonly REBUILD_SCRIPT="${CACHE_DIR}/rebuild_slurm.sh"
readonly DEFAULT_BUCKET="aws-parallelcluster-dev-build-dependencies"
readonly DEFAULT_ARCHIVE_KEY="archives/dependencies/slurm/${TARGET_SOURCE_NAME}.tar.gz"
readonly ADC_ARCHIVE_KEY="${DEFAULT_BUCKET}/${DEFAULT_ARCHIVE_KEY}"
readonly INSTALL_PREFIX="/opt/slurm"
readonly DEFAULT_SLURMDBD_LOG="/var/log/slurmdbd.log"
readonly DEFAULT_SLURMDBD_PORT="6819"
readonly SLURMDBD_DROPIN_DIR="/etc/systemd/system/slurmdbd.service.d"
readonly SLURMDBD_DROPIN="${SLURMDBD_DROPIN_DIR}/zz-pcluster-upgrade-timeout.conf"
# The accounting database conversion can take tens of minutes on a large job table.
readonly SLURMDBD_READY_ATTEMPTS=360
readonly SLURMDBD_READY_INTERVAL=10
ALLOW_UNSUPPORTED_UPGRADE="${PCLUSTER_ALLOW_UNSUPPORTED_SLURM_UPGRADE:-0}"
CROSS_MAJOR_UPGRADE=0

ROLE=""
REGION=""
ARTIFACT_BUCKET=""
ARTIFACT_KEY=""
ARTIFACT_REGION=""
SUPERVISORCTL=""
CURRENT_VERSION=""
CURRENT_SOURCE_DIR=""
ARCHIVE_PATH="${CACHE_DIR}/${TARGET_SOURCE_NAME}.tar.gz"
BACKUP_TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP_PATH="/opt/slurm_backup_${BACKUP_TIMESTAMP}.tar.gz"
STATE_BACKUP_PATH="/opt/slurm_state_backup_${BACKUP_TIMESTAMP}.tar.gz"
SLURMCTLD_WAS_ACTIVE=0
SLURMDBD_WAS_ACTIVE=0
SLURMRESTD_WAS_ACTIVE=0
CLUSTERSTATUSMGTD_WAS_RUNNING=0
CLUSTERMGTD_WAS_RUNNING=0

log() {
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
    log "ERROR: $*" >&2
    exit 1
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

unit_exists() {
    systemctl cat "$1" >/dev/null 2>&1
}

unit_is_active() {
    systemctl is-active --quiet "$1"
}

# An unset key is a normal outcome, so the failing grep must not become the exit status of the function: under
# `pipefail` that status propagates out of the command substitution at every call site and, being an assignment,
# aborts the installer instead of yielding the empty value the callers are written to handle.
slurm_conf_value() {
    local key="$1"
    local file="$2"

    [[ -f "${file}" ]] || return 0
    { grep -iE "^[[:space:]]*${key}[[:space:]]*=" "${file}" 2>/dev/null || true; } | tail -n 1 | \
        sed -E 's/^[^=]*=[[:space:]]*//; s/[[:space:]]*(#.*)?$//'
}

# slurmdbd settings live in whichever of the two files ParallelCluster wrote for this cluster.
slurmdbd_conf_value() {
    local key="$1"
    local value=""
    local file

    for file in "${INSTALL_PREFIX}/etc/slurm_parallelcluster_slurmdbd.conf" "${INSTALL_PREFIX}/etc/slurmdbd.conf"; do
        value="$(slurm_conf_value "${key}" "${file}")"
        if [[ -n "${value}" ]]; then
            break
        fi
    done
    printf '%s\n' "${value}"
}

slurmdbd_log_file() {
    local value

    value="$(slurmdbd_conf_value LogFile)"
    printf '%s\n' "${value:-${DEFAULT_SLURMDBD_LOG}}"
}

slurmdbd_port() {
    local value

    value="$(slurmdbd_conf_value DbdPort)"
    printf '%s\n' "${value:-${DEFAULT_SLURMDBD_PORT}}"
}

slurmctld_log_file() {
    slurm_conf_value SlurmctldLogFile "${INSTALL_PREFIX}/etc/slurm.conf"
}

log_length() {
    local log_file="$1"

    if [[ -n "${log_file}" && -f "${log_file}" ]]; then
        wc -l <"${log_file}"
    else
        printf '0\n'
    fi
}

remove_slurmdbd_start_timeout_override() {
    [[ -f "${SLURMDBD_DROPIN}" ]] || return 0
    log "Restoring the slurmdbd systemd start timeout"
    rm -f "${SLURMDBD_DROPIN}"
    rmdir --ignore-fail-on-non-empty "${SLURMDBD_DROPIN_DIR}" 2>/dev/null || true
    systemctl daemon-reload || true
}

dump_diagnostics() {
    local log_file

    for log_file in "$(slurmdbd_log_file)" "$(slurmctld_log_file)"; do
        [[ -n "${log_file}" && -f "${log_file}" ]] || continue
        log "Last 50 lines of ${log_file}:"
        tail -n 50 "${log_file}" >&2 || true
    done
}

on_exit() {
    local status=$?

    remove_slurmdbd_start_timeout_override || true
    if ((status != 0)); then
        log "Installer failed with status ${status}, collecting Slurm logs"
        dump_diagnostics || true
    fi
}

trap on_exit EXIT

# Reads the installed version from the first daemon binary that is present: slurmctld on a head node, slurmdbd on
# an external accounting node. Which binaries exist depends on the cluster, so neither one alone is dependable, and
# the caller is not required to have detected the role yet. `|| true` keeps a binary that fails to run from turning
# the assignment into an errexit abort, so the loop can fall through to the next candidate.
runtime_version() {
    local binary
    local version=""

    for binary in "${INSTALL_PREFIX}/sbin/slurmctld" "${INSTALL_PREFIX}/sbin/slurmdbd"; do
        [[ -x "${binary}" ]] || continue
        version="$("${binary}" -V 2>/dev/null |
            awk 'match($0, /[0-9]+\.[0-9]+\.[0-9]+/) { print substr($0, RSTART, RLENGTH); exit }' || true)"
        if [[ -n "${version}" ]]; then
            break
        fi
    done
    printf '%s\n' "${version}"
}

head_node_layout_present() {
    [[ -f /etc/parallelcluster/parallelcluster_supervisord.conf ]]
}

detect_role() {
    # A head node with accounting disabled can be missing slurmdbd, and an external accounting node has no
    # slurmctld, so either binary is enough to prove that Slurm is installed here.
    [[ -x "${INSTALL_PREFIX}/sbin/slurmctld" || -x "${INSTALL_PREFIX}/sbin/slurmdbd" ]] || \
        fail "Existing Slurm installation not found under ${INSTALL_PREFIX}"

    if unit_is_active slurmctld.service; then
        ROLE="head"
        SLURMCTLD_WAS_ACTIVE=1
    elif head_node_layout_present; then
        fail "This is a head node, but slurmctld is not active"
    elif unit_is_active slurmdbd.service; then
        ROLE="external_dbd"
        SLURMDBD_WAS_ACTIVE=1
    else
        fail "This host is neither an active ParallelCluster head node nor an active external SlurmDBD node"
    fi

    if [[ "${ROLE}" == "head" ]] && unit_is_active slurmdbd.service; then
        SLURMDBD_WAS_ACTIVE=1
    fi
    if unit_exists slurmrestd.service && unit_is_active slurmrestd.service; then
        SLURMRESTD_WAS_ACTIVE=1
    fi

    log "Detected host role: ${ROLE}"
}

detect_region() {
    local token=""
    local identity_document=""

    REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
    if [[ -z "${REGION}" ]]; then
        token="$(curl -fsS --connect-timeout 2 --max-time 5 --retry 2 \
            -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 300' \
            http://169.254.169.254/latest/api/token || true)"
        if [[ -n "${token}" ]]; then
            REGION="$(curl -fsS --connect-timeout 2 --max-time 5 --retry 2 \
                -H "X-aws-ec2-metadata-token: ${token}" \
                http://169.254.169.254/latest/meta-data/placement/region || true)"
            if [[ -z "${REGION}" ]]; then
                identity_document="$(curl -fsS --connect-timeout 2 --max-time 5 --retry 2 \
                    -H "X-aws-ec2-metadata-token: ${token}" \
                    http://169.254.169.254/latest/dynamic/instance-identity/document || true)"
                REGION="$(sed -n 's/.*"region"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
                    <<<"${identity_document}")"
            fi
        fi
    fi

    [[ "${REGION}" =~ ^[a-z0-9-]+$ ]] || fail "Unable to determine the AWS Region"
    log "Using AWS Region: ${REGION}"
}

resolve_artifact_location() {
    # The bucket name is the same in every partition, but the bucket is not: each partition has its own copy, in the
    # Region where the development infrastructure of that partition runs, and it is only reachable from inside that
    # partition. So the Region to talk to S3 in is a property of the bucket, not of the cluster under test.
    case "${REGION}" in
        us-iso-*)
            ARTIFACT_BUCKET="draco-parallelcluster-dca-artifacts"
            ARTIFACT_KEY="${ADC_ARCHIVE_KEY}"
            ARTIFACT_REGION="${REGION}"
            ;;
        us-isob-*)
            ARTIFACT_BUCKET="draco-parallelcluster-lck-artifacts"
            ARTIFACT_KEY="${ADC_ARCHIVE_KEY}"
            ARTIFACT_REGION="${REGION}"
            ;;
        *)
            ARTIFACT_BUCKET="${DEFAULT_BUCKET}"
            ARTIFACT_KEY="${DEFAULT_ARCHIVE_KEY}"
            case "${REGION}" in
                us-gov-*) ARTIFACT_REGION="us-gov-west-1" ;;
                cn-*) ARTIFACT_REGION="cn-north-1" ;;
                *) ARTIFACT_REGION="us-east-1" ;;
            esac
            ;;
    esac
    log "Using source artifact s3://${ARTIFACT_BUCKET}/${ARTIFACT_KEY} in Region ${ARTIFACT_REGION}"
}

artifact_https_url() {
    local domain
    case "${ARTIFACT_REGION}" in
        cn-*) domain="amazonaws.com.cn" ;;
        us-iso-*) domain="c2s.ic.gov" ;;
        us-isob-*) domain="sc2s.sgov.gov" ;;
        *) domain="amazonaws.com" ;;
    esac
    printf 'https://%s.s3.%s.%s/%s\n' "${ARTIFACT_BUCKET}" "${ARTIFACT_REGION}" "${domain}" "${ARTIFACT_KEY}"
}

source_archive_is_usable() {
    [[ -s "${ARCHIVE_PATH}" ]] && gzip --test "${ARCHIVE_PATH}" 2>/dev/null
}

download_source_archive() {
    local url
    local curl_options=(--fail --location --silent --show-error --connect-timeout 10 --max-time 1800 --retry 3)

    # An archive that is already in place is used as it is: on a host with no read access to the artifact bucket,
    # copying the source archive to ${ARCHIVE_PATH} beforehand is the only way to run this installer.
    if source_archive_is_usable; then
        log "Using the Slurm source archive already present at ${ARCHIVE_PATH}"
        log "Source archive SHA-256: $(sha256sum "${ARCHIVE_PATH}" | awk '{print $1}')"
        return 0
    fi

    rm -f "${ARCHIVE_PATH}"
    if command_exists aws && \
        aws s3 cp "s3://${ARTIFACT_BUCKET}/${ARTIFACT_KEY}" "${ARCHIVE_PATH}" \
            --region "${ARTIFACT_REGION}" --only-show-errors; then
        :
    else
        url="$(artifact_https_url)"
        if [[ -n "${AWS_CA_BUNDLE:-}" ]]; then
            curl_options+=(--cacert "${AWS_CA_BUNDLE}")
        elif [[ -f "/etc/pki/${REGION}/certs/ca-bundle.pem" ]]; then
            curl_options+=(--cacert "/etc/pki/${REGION}/certs/ca-bundle.pem")
        fi
        curl "${curl_options[@]}" --output "${ARCHIVE_PATH}" "${url}"
    fi

    [[ -s "${ARCHIVE_PATH}" ]] || fail "Downloaded Slurm source archive is empty"
    # A host with no read access to the artifact bucket gets an error document instead of a tarball, and the HTTPS
    # fallback does not always report that as a transfer failure. Reject it here, while the running Slurm is still
    # installed, rather than discovering it from tar once the uninstall has already happened.
    source_archive_is_usable || \
        fail "Downloaded Slurm source archive is not a gzip archive, it starts with: $(head -c 200 "${ARCHIVE_PATH}")"
    log "Source archive SHA-256: $(sha256sum "${ARCHIVE_PATH}" | awk '{print $1}')"
}

capture_manager_state() {
    local -a supervisorctl_paths=()
    local status_output

    [[ "${ROLE}" == "head" ]] || return 0
    mapfile -t supervisorctl_paths < <(find /opt/parallelcluster/pyenv -type f \
        -path '*/cookbook_virtualenv/bin/supervisorctl' -print)
    ((${#supervisorctl_paths[@]} == 1)) || fail "Expected exactly one ParallelCluster supervisorctl"
    SUPERVISORCTL="${supervisorctl_paths[0]}"

    # supervisorctl exits non-zero when the process it is asked about is not RUNNING, and a trailing failing
    # `[[ ... ]] &&` would make this function return non-zero, which under `set -e` aborts the installer before
    # anything is done. Both are therefore written so that a stopped manager is a normal outcome.
    status_output="$("${SUPERVISORCTL}" status clusterstatusmgtd || true)"
    if [[ "${status_output}" == *"RUNNING"* ]]; then
        CLUSTERSTATUSMGTD_WAS_RUNNING=1
    fi
    status_output="$("${SUPERVISORCTL}" status clustermgtd || true)"
    if [[ "${status_output}" == *"RUNNING"* ]]; then
        CLUSTERMGTD_WAS_RUNNING=1
    fi
    log "Managers running before the upgrade: clusterstatusmgtd=${CLUSTERSTATUSMGTD_WAS_RUNNING}" \
        "clustermgtd=${CLUSTERMGTD_WAS_RUNNING}"
}

# Pre-flight for the same lookup the wiki script does: it needs exactly one source tree for the installed version
# to uninstall it, and finding out here means the check fails while the cluster is still serving jobs instead of
# after the daemons have been stopped. The wiki script repeats the lookup itself, and that copy is the one that
# drives the uninstall.
find_current_source_directory() {
    local version_pattern="${CURRENT_VERSION//./-}"
    local -a source_dirs=()

    mapfile -t source_dirs < <(find "${CACHE_DIR}" -mindepth 1 -maxdepth 1 -type d \
        -name "slurm-slurm-${version_pattern}-*" -print)
    ((${#source_dirs[@]} == 1)) || \
        fail "Expected one source directory for installed Slurm ${CURRENT_VERSION}, found ${#source_dirs[@]}"
    CURRENT_SOURCE_DIR="${source_dirs[0]}"
    [[ -f "${CURRENT_SOURCE_DIR}/Makefile" ]] || fail "Current Slurm source Makefile is missing"
}

assert_upgrade_supported() {
    local current_major="${CURRENT_VERSION%.*}"
    local major

    if [[ "${current_major}" == "${TARGET_MAJOR_VERSION}" ]]; then
        return 0
    fi

    CROSS_MAJOR_UPGRADE=1
    log "Cross-major Slurm upgrade: ${CURRENT_VERSION} -> ${TARGET_RUNTIME_VERSION}"
    log "WARNING: slurmdbd converts the accounting database and slurmctld converts StateSaveLocation in place."
    log "WARNING: this cannot be undone. Restore an RDS snapshot and ${STATE_BACKUP_PATH} to go back."

    for major in ${TARGET_COMPATIBLE_MAJORS}; do
        if [[ "${current_major}" == "${major}" ]]; then
            return 0
        fi
    done

    if [[ "${ALLOW_UNSUPPORTED_UPGRADE}" == "1" ]]; then
        log "WARNING: ${current_major} is outside the compatibility window of Slurm ${TARGET_MAJOR_VERSION};"
        log "WARNING: continuing because PCLUSTER_ALLOW_UNSUPPORTED_SLURM_UPGRADE=1. The daemons are expected"
        log "WARNING: to refuse to start, and running jobs and job accounting are expected to be lost."
        return 0
    fi

    fail "Slurm ${TARGET_MAJOR_VERSION} supports in-place upgrades only from ${TARGET_COMPATIBLE_MAJORS// /, };" \
        "found ${CURRENT_VERSION}. Upgrade through an intermediate release, or set" \
        "PCLUSTER_ALLOW_UNSUPPORTED_SLURM_UPGRADE=1 to attempt it anyway."
}

warn_about_external_plugins() {
    local -a plugins=()

    ((CROSS_MAJOR_UPGRADE)) || return 0
    mapfile -t plugins < <(grep -hE '^[[:space:]]*(optional|required)' \
        "${INSTALL_PREFIX}/etc/plugstack.conf" "${INSTALL_PREFIX}"/etc/plugstack.conf.d/* 2>/dev/null | \
        grep -oE '/[^[:space:]]+\.so' | sort -u)
    ((${#plugins[@]})) || return 0

    log "WARNING: libslurm changes with every major release, so these SPANK plugins were built against the"
    log "WARNING: previous Slurm version and may need to be recompiled: ${plugins[*]}"
}

stop_services() {
    log "Stopping ParallelCluster managers and Slurm daemons"
    if (( CLUSTERSTATUSMGTD_WAS_RUNNING )); then
        "${SUPERVISORCTL}" stop clusterstatusmgtd
    fi
    if (( CLUSTERMGTD_WAS_RUNNING )); then
        "${SUPERVISORCTL}" stop clustermgtd
    fi
    if (( SLURMRESTD_WAS_ACTIVE )); then
        systemctl stop slurmrestd
    fi
    if (( SLURMCTLD_WAS_ACTIVE )); then
        systemctl stop slurmctld
    fi
    if (( SLURMDBD_WAS_ACTIVE )); then
        systemctl stop slurmdbd
    fi
}

install_slurmdbd_start_timeout_override() {
    log "Removing the slurmdbd systemd start timeout for the accounting database migration"
    mkdir -p "${SLURMDBD_DROPIN_DIR}"
    cat >"${SLURMDBD_DROPIN}" <<'DROPIN'
# Added temporarily by the ParallelCluster integration-test Slurm installer, and removed once slurmdbd is up.
# On the first start after a major upgrade slurmdbd converts the accounting database, which can take tens of
# minutes. If systemd reaches its start timeout first it kills slurmdbd mid-conversion and the accounting data
# is lost, so the timeout is disabled for the duration of the upgrade.
[Service]
TimeoutStartSec=infinity
DROPIN
    systemctl daemon-reload
}

# slurmdbd opens its RPC port only once the accounting database is ready, so a listening socket means the
# migration finished. Unlike the log line this does not depend on LogFile being set, and unlike a connect probe
# it asks the kernel rather than the daemon, so it works whatever address DbdHost resolves to and leaves no
# half-finished connection for slurmdbd to log about. Without ss the caller falls back to the log line alone.
slurmdbd_is_listening() {
    local port="$1"

    [[ "${port}" =~ ^[0-9]+$ ]] || return 1
    command_exists ss || return 1
    ss -Hltn "sport = :${port}" 2>/dev/null | grep -q .
}

wait_for_slurmdbd() {
    local since="$1"
    local log_file
    local port
    local attempt

    log_file="$(slurmdbd_log_file)"
    port="$(slurmdbd_port)"
    for ((attempt = 1; attempt <= SLURMDBD_READY_ATTEMPTS; attempt++)); do
        if tail -n "+$((since + 1))" "${log_file}" 2>/dev/null | grep -q 'slurmdbd version .* started'; then
            log "slurmdbd completed the accounting database migration"
            return 0
        fi
        # A cluster that logs to syslog never writes ${log_file}, and waiting for a line that cannot appear
        # would burn the whole timeout on a slurmdbd that came up fine.
        if slurmdbd_is_listening "${port}"; then
            log "slurmdbd is listening on port ${port} after the accounting database migration"
            return 0
        fi
        if ! unit_is_active slurmdbd.service; then
            log "slurmdbd is no longer active while waiting for the accounting database migration"
            return 1
        fi
        if ((attempt % 6 == 1)); then
            log "Waiting for slurmdbd to finish the accounting database migration (attempt ${attempt})"
        fi
        sleep "${SLURMDBD_READY_INTERVAL}"
    done
    log "slurmdbd was still not ready after $((SLURMDBD_READY_ATTEMPTS * SLURMDBD_READY_INTERVAL)) seconds" \
        "(watched ${log_file} and port ${port})"
    return 1
}

start_services() {
    local slurmdbd_log_offset

    log "Starting Slurm daemons and ParallelCluster managers"
    if (( SLURMDBD_WAS_ACTIVE )); then
        slurmdbd_log_offset="$(log_length "$(slurmdbd_log_file)")"
        install_slurmdbd_start_timeout_override
        systemctl start slurmdbd
        # slurmctld must not start until slurmdbd is done: Slurm requires slurmdbd to be at the same or a
        # higher major release than slurmctld, and a slurmdbd busy converting the database answers nothing.
        wait_for_slurmdbd "${slurmdbd_log_offset}" || fail "slurmdbd did not complete the database migration"
        remove_slurmdbd_start_timeout_override
    fi
    if (( SLURMCTLD_WAS_ACTIVE )); then
        systemctl start slurmctld
    fi
    if (( SLURMRESTD_WAS_ACTIVE )); then
        systemctl start slurmrestd
    fi
    if (( CLUSTERSTATUSMGTD_WAS_RUNNING )); then
        "${SUPERVISORCTL}" start clusterstatusmgtd
    fi
    if (( CLUSTERMGTD_WAS_RUNNING )); then
        "${SUPERVISORCTL}" start clustermgtd
    fi
}

wait_for_controller() {
    local attempt
    for ((attempt = 1; attempt <= 30; attempt++)); do
        if "${INSTALL_PREFIX}/bin/scontrol" ping 2>/dev/null | grep -q 'is UP'; then
            return 0
        fi
        sleep 10
    done
    return 1
}

validate_services() {
    local installed_version
    installed_version="$(runtime_version)"
    [[ "${installed_version}" == "${TARGET_RUNTIME_VERSION}" ]] || \
        fail "Installed Slurm version ${installed_version:-unknown} does not match ${TARGET_RUNTIME_VERSION}"

    if (( SLURMDBD_WAS_ACTIVE )); then
        unit_is_active slurmdbd.service || fail "slurmdbd is not active"
        # Reading the accounting database proves the schema conversion completed, not merely that the daemon
        # is up. sacctmgr needs slurm.conf, which only the head node has.
        if [[ "${ROLE}" == "head" ]]; then
            "${INSTALL_PREFIX}/bin/sacctmgr" -n show clusters >/dev/null 2>&1 || \
                fail "sacctmgr cannot read the accounting database after the upgrade"
        fi
    fi
    if (( SLURMCTLD_WAS_ACTIVE )); then
        unit_is_active slurmctld.service || fail "slurmctld is not active"
        wait_for_controller || fail "slurmctld did not become responsive"
    fi
    if (( SLURMRESTD_WAS_ACTIVE )); then
        unit_is_active slurmrestd.service || fail "slurmrestd is not active"
    fi
    if (( CLUSTERSTATUSMGTD_WAS_RUNNING )); then
        "${SUPERVISORCTL}" status clusterstatusmgtd | grep -q RUNNING || fail "clusterstatusmgtd is not running"
    fi
    if (( CLUSTERMGTD_WAS_RUNNING )); then
        "${SUPERVISORCTL}" status clustermgtd | grep -q RUNNING || fail "clustermgtd is not running"
    fi
}

backup_state_save_location() {
    local state_dir

    # slurmctld rewrites StateSaveLocation to the new format on first start, so the pre-upgrade contents are
    # the only way back. The daemons are already stopped here, which makes the copy consistent.
    state_dir="$(slurm_conf_value StateSaveLocation "${INSTALL_PREFIX}/etc/slurm.conf")"
    if [[ -z "${state_dir}" || ! -d "${state_dir}" ]]; then
        log "WARNING: StateSaveLocation '${state_dir:-unset}' not found, skipping the Slurm state backup"
        return 0
    fi

    log "Backing up StateSaveLocation ${state_dir} to ${STATE_BACKUP_PATH}"
    tar -czf "${STATE_BACKUP_PATH}" -C "$(dirname "${state_dir}")" "$(basename "${state_dir}")"
}

# Step 3 of the wiki page, which the page leaves to the operator. The daemons are already stopped when this runs,
# so both archives are consistent, and slurmctld rewrites StateSaveLocation to the new format on its first start,
# which makes these two archives the only way back to the version being replaced.
backup_installation_and_state() {
    log "Backing up ${INSTALL_PREFIX} to ${BACKUP_PATH}"
    tar -czf "${BACKUP_PATH}" -C /opt slurm
    tar -tzf "${BACKUP_PATH}" >/dev/null || fail "The installation backup archive is not readable"
    backup_state_save_location
}

# Writes the Step 4 script of the Slurm upgrade wiki page to disk.
#
# Everything between the two REBUILD_SLURM_SH markers below is a verbatim copy of the script that page tells
# customers to save as rebuild_slurm.sh, and running exactly that script is how this installer keeps the
# documented procedure under test. Do not change a line of it here without changing the same line on the wiki
# page, and keep the copy diffable: no substitutions, no reindenting, and no installer-only additions. Everything
# this installer does beyond the page belongs in the functions around this one.
write_wiki_step_4_script() {
    log "Writing the wiki Step 4 script to ${REBUILD_SCRIPT}"
    cat >"${REBUILD_SCRIPT}" <<'REBUILD_SLURM_SH'
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
readonly ARCHIVE_PATH="${CACHE_DIR}/${SLURM_VERSION_NEW}.tar.gz"
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

# The head node runs slurmctld, an external Slurmdbd instance runs slurmdbd, and a head node with accounting
# disabled has no slurmdbd at all, so the version is read from whichever daemon binary this node has.
installed_version() {
    local binary
    local version=""

    for binary in "${PREFIX}/sbin/slurmctld" "${PREFIX}/sbin/slurmdbd"; do
        [[ -x "${binary}" ]] || continue
        version="$("${binary}" -V 2>/dev/null |
            awk 'match($0, /[0-9]+\.[0-9]+\.[0-9]+/) { print substr($0, RSTART, RLENGTH); exit }' || true)"
        if [[ -n "${version}" ]]; then
            break
        fi
    done
    printf '%s\n' "${version}"
}

[[ ${EUID} -eq 0 ]] || fail "Run this script as root"
[[ -d "${CACHE_DIR}" ]] || fail "The Chef cache directory ${CACHE_DIR} does not exist"
systemctl is-active --quiet slurmctld.service &&
    fail "slurmctld is still running. Stop the Slurm daemons before running this script."
systemctl is-active --quiet slurmdbd.service &&
    fail "slurmdbd is still running. Stop the Slurm daemons before running this script."

current_version="$(installed_version)"
[[ -n "${current_version}" ]] || fail "Unable to determine the Slurm version installed under ${PREFIX}"
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
# An archive that is already in place is used as it is, so a cluster that can reach neither GitHub nor S3 can be
# served by copying the source archive to ${ARCHIVE_PATH} beforehand.
if [[ -s "${ARCHIVE_PATH}" ]] && gzip --test "${ARCHIVE_PATH}" 2>/dev/null; then
    log "Using the Slurm source archive already present at ${ARCHIVE_PATH}"
else
    curl --fail --location --silent --show-error --retry 3 --output "${ARCHIVE_PATH}" "${SOURCE_URL}"
    gzip --test "${ARCHIVE_PATH}" || fail "The downloaded archive is not a valid gzip archive"
fi
tar -xf "${ARCHIVE_PATH}" -C "${CACHE_DIR}"
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

log "Installed Slurm version is now $(installed_version)"
log "Start the Slurm daemons as described in the wiki, slurmdbd first."
REBUILD_SLURM_SH
    chmod 755 "${REBUILD_SCRIPT}"
    bash -n "${REBUILD_SCRIPT}" || fail "The embedded copy of the wiki Step 4 script is not valid bash"
}

# Runs the wiki script through the interface the page documents: the Slurm tag in SLURM_VERSION_NEW and the
# archive location in SLURM_SOURCE_URL. The archive has already been staged at the path the script looks in, so
# the partitions where the artifact bucket needs credentials and a custom CA bundle are served without the script
# having to know anything about them.
run_wiki_step_4_script() {
    log "Running ${REBUILD_SCRIPT} to install ${TARGET_SOURCE_NAME} over Slurm ${CURRENT_VERSION}"
    SLURM_VERSION_NEW="${TARGET_SOURCE_NAME}" \
        SLURM_SOURCE_URL="$(artifact_https_url)" \
        "${REBUILD_SCRIPT}"
}

warn_about_slurm_config_complaints() {
    local since="$1"
    local slurmctld_log
    local -a complaints=()

    ((SLURMCTLD_WAS_ACTIVE)) || return 0
    slurmctld_log="$(slurmctld_log_file)"
    [[ -n "${slurmctld_log}" && -f "${slurmctld_log}" ]] || return 0

    # The new daemons re-validate the configuration written for the previous release, so a parameter that the
    # release removed or renamed is only visible here. These are warnings and not failures: the upgrade wiki
    # tells customers to update slurm.conf afterwards, and an integration test must not fail on the old file.
    mapfile -t complaints < <(tail -n "+$((since + 1))" "${slurmctld_log}" 2>/dev/null | \
        grep -iE 'defunct|obsolete|ignoring|no longer supported' || true)
    ((${#complaints[@]})) || return 0

    log "WARNING: the new slurmctld reported ${#complaints[@]} complaints about the existing configuration:"
    printf 'WARNING: %s\n' "${complaints[@]}" >&2
}

main() {
    local slurmctld_log_offset

    (($# == 0)) || fail "This installer accepts no arguments"
    [[ "${EUID}" -eq 0 ]] || fail "Run this installer as root"
    [[ -d "${CACHE_DIR}" ]] || fail "Chef cache directory does not exist: ${CACHE_DIR}"

    detect_role
    detect_region
    resolve_artifact_location
    capture_manager_state

    CURRENT_VERSION="$(runtime_version)"
    [[ -n "${CURRENT_VERSION}" ]] || fail "Unable to determine installed Slurm version"
    assert_upgrade_supported

    if [[ "${CURRENT_VERSION}" == "${TARGET_RUNTIME_VERSION}" ]]; then
        log "Slurm ${TARGET_RUNTIME_VERSION} is already installed"
        validate_services
        return 0
    fi

    # Everything that can fail on the state of this host or on the artifact bucket is settled while the cluster is
    # still up: the wiki script needs the source tree of the installed version to uninstall it, and staging the
    # archive here keeps a credentials or CA problem from surfacing once the daemons are already stopped.
    find_current_source_directory
    warn_about_external_plugins
    write_wiki_step_4_script
    download_source_archive

    # From here on the installer follows the wiki page in its order: Step 2 stops the daemons, Step 3 takes the
    # backups, Step 4 is the script itself. The script contains the build and refuses to run while a daemon is
    # active, so the build happens with the cluster down, exactly as it does for a customer following the page.
    stop_services
    slurmctld_log_offset="$(log_length "$(slurmctld_log_file)")"
    backup_installation_and_state
    run_wiki_step_4_script
    start_services
    validate_services
    warn_about_slurm_config_complaints "${slurmctld_log_offset}"
    log "Successfully installed and validated Slurm ${TARGET_RUNTIME_VERSION} (upgraded from ${CURRENT_VERSION})"
}

main "$@"
