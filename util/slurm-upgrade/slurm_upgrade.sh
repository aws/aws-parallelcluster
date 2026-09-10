#!/bin/bash
#
# Upgrade Slurm in place on an AWS ParallelCluster head node or on an external Slurmdbd instance, and roll the upgrade
# back. Companion to https://github.com/aws/aws-parallelcluster/wiki/Upgrade-Slurm-in-an-AWS-ParallelCluster-cluster,
# which this script follows step by step. Read that page first: it explains what each step does and why.
#
#   sudo SLURM_VERSION_NEW=slurm-25-11-8-1 [SLURM_SOURCE_URL=<url>] ./slurm_upgrade.sh upgrade
#   sudo ./slurm_upgrade.sh rollback [--install-backup <tar.gz>] [--state-backup <tar.gz>] [--accounting-backup <sql.gz>]
#
# `upgrade` runs Steps 2 to 5 and 7 of the page (Appendix A on an external Slurmdbd instance). `rollback` is Appendix D,
# from the newest backups of Step 3 under /opt unless given. Left to you: Steps 1 and 6 (the compute fleet), Step 3.2
# (see slurm_accounting_database.sh), Appendix B (plugins), Appendix E (login nodes) and the job checks of Step 7.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly PREFIX="/opt/slurm"
readonly SLURMCTLD_LOG_DEFAULT="/var/log/slurmctld.log"
readonly SLURMDBD_LOG_DEFAULT="/var/log/slurmdbd.log"
readonly SLURMDBD_PORT_DEFAULT="6819"
readonly CLUSTERMGTD_LOG="/var/log/parallelcluster/clustermgtd"
# Step 5: the accounting database conversion can take tens of minutes and must not be interrupted.
readonly SLURMDBD_STARTUP_TIMEOUT_SECONDS=$((60 * 60))
readonly SLURMDBD_STOP_TIMEOUT_SECONDS=120
readonly CONTROLLER_PING_TIMEOUT_SECONDS=300

SUPERVISORCTL=""
CLUSTERSTATUSMGTD=0
CLUSTERMGTD=0
SLURMRESTD=0
SLURMCTLD=0
SLURMDBD=0

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

usage() {
    cat >&2 <<EOF
Usage: sudo SLURM_VERSION_NEW=<slurm tag> [SLURM_SOURCE_URL=<url>] $0 upgrade
       sudo $0 rollback [--install-backup <tar.gz>] [--state-backup <tar.gz>] [--accounting-backup <sql.gz>]
EOF
    exit 2
}

on_exit() {
    local status=$? log_file
    ((status != 0)) || return 0
    log "Failed with status ${status}. Last lines of the Slurm logs:"
    for log_file in "$(slurmctld_log_file)" "$(slurmdbd_log_file)"; do
        [[ -f "${log_file}" ]] || continue
        log "--- ${log_file}"
        tail -n 50 "${log_file}" >&2 || true
    done
}
trap on_exit EXIT

# A Slurm configuration value from every file under /opt/slurm/etc, the last assignment winning as for Slurm.
conf_value() {
    { grep -rhiE "^[[:space:]]*$1[[:space:]]*=" "${PREFIX}/etc/" 2>/dev/null || true; } | tail -n 1 |
        sed -E 's/^[^=]*=[[:space:]]*//; s/[[:space:]]*(#.*)?$//'
}

slurmctld_log_file() { local value; value="$(conf_value SlurmctldLogFile)"; printf '%s\n' "${value:-${SLURMCTLD_LOG_DEFAULT}}"; }
slurmdbd_log_file() { local value; value="$(conf_value LogFile)"; printf '%s\n' "${value:-${SLURMDBD_LOG_DEFAULT}}"; }
log_length() { wc -l <"$1" 2>/dev/null || echo 0; }
unit_active() { systemctl is-active --quiet "$1"; }
unit_enabled() { systemctl is-enabled --quiet "$1" 2>/dev/null; }
is_head_node() { [[ -f "${PREFIX}/etc/slurm.conf" ]]; }

# The version installed under /opt/slurm, from slurmctld on a head node or slurmdbd on an external Slurmdbd instance.
installed_version() {
    local binary version=""
    for binary in "${PREFIX}/sbin/slurmctld" "${PREFIX}/sbin/slurmdbd"; do
        [[ -x "${binary}" ]] || continue
        version="$("${binary}" -V 2>/dev/null |
            awk 'match($0, /[0-9]+\.[0-9]+\.[0-9]+/) { print substr($0, RSTART, RLENGTH); exit }' || true)"
        [[ -z "${version}" ]] || break
    done
    printf '%s\n' "${version}"
}

# slurm-25-11-8-1 is Slurm 25.11.8.
version_of_tag() {
    local tag="${1#slurm-}" major minor patch
    IFS=- read -r major minor patch _ <<<"${tag}"
    [[ "${major}" =~ ^[0-9]+$ && "${minor}" =~ ^[0-9]+$ && "${patch}" =~ ^[0-9]+$ ]] ||
        fail "SLURM_VERSION_NEW must be a Slurm tag such as slurm-25-11-8-1, got '$1'"
    printf '%s.%s.%s\n' "${major}" "${minor}" "${patch}"
}

# The daemons Step 5 restarts: those active for `upgrade`, those configured for `rollback`, which usually follows a
# failed start.
record_daemons() {
    local mode="$1" status
    [[ -x "${PREFIX}/sbin/slurmctld" || -x "${PREFIX}/sbin/slurmdbd" ]] || fail "No Slurm installation under ${PREFIX}"

    # supervisord runs the ParallelCluster daemons on a head node; an external Slurmdbd instance has none.
    SUPERVISORCTL="$(ls /opt/parallelcluster/pyenv/versions/*/envs/cookbook_virtualenv/bin/supervisorctl 2>/dev/null | head -n 1 || true)"
    if [[ -n "${SUPERVISORCTL}" ]]; then
        status="$("${SUPERVISORCTL}" status 2>/dev/null || true)"
        if [[ "${mode}" == running ]]; then
            grep -qE '^clusterstatusmgtd[[:space:]]+RUNNING' <<<"${status}" && CLUSTERSTATUSMGTD=1
            grep -qE '^clustermgtd[[:space:]]+RUNNING' <<<"${status}" && CLUSTERMGTD=1
        else
            grep -qE '^clusterstatusmgtd[[:space:]]' <<<"${status}" && CLUSTERSTATUSMGTD=1
            grep -qE '^clustermgtd[[:space:]]' <<<"${status}" && CLUSTERMGTD=1
        fi
    fi
    if [[ "${mode}" == running ]]; then
        unit_active slurmrestd && SLURMRESTD=1
        unit_active slurmctld && SLURMCTLD=1
        unit_active slurmdbd && SLURMDBD=1
    else
        { unit_active slurmrestd || unit_enabled slurmrestd; } && SLURMRESTD=1
        { unit_active slurmctld || unit_enabled slurmctld; } && SLURMCTLD=1
        { unit_active slurmdbd || unit_enabled slurmdbd; } && SLURMDBD=1
    fi
    ((SLURMCTLD || SLURMDBD)) ||
        fail "Neither slurmctld nor slurmdbd is ${mode} on this node: it is not a head node or an external Slurmdbd instance"
    log "Daemons ${mode} on this node: clusterstatusmgtd=${CLUSTERSTATUSMGTD} clustermgtd=${CLUSTERMGTD}" \
        "slurmrestd=${SLURMRESTD} slurmctld=${SLURMCTLD} slurmdbd=${SLURMDBD}"
    return 0
}

# Before you begin, 5: anything linked against libslurm must be rebuilt across a major release.
warn_about_plugins() {
    local current="$1" new="$2" plugins
    [[ "${current%.*}" != "${new%.*}" ]] || return 0
    log "WARNING: ${current} to ${new} is a major release upgrade: slurmdbd converts the accounting database and" \
        "slurmctld converts the controller state on first start, and neither conversion can be undone."
    plugins="$(grep -hE '^[[:space:]]*(optional|required)' "${PREFIX}"/etc/plugstack.conf "${PREFIX}"/etc/plugstack.conf.d/* 2>/dev/null |
        grep -oE '/[^[:space:]]+\.so' | sort -u | tr '\n' ' ' || true)"
    [[ -z "${plugins}" ]] ||
        log "WARNING: these SPANK plugins were built against Slurm ${current} and must be rebuilt (Appendix B): ${plugins}"
}

# Step 2. Stop the daemons on the head node.
stop_daemons() {
    log "Step 2: stopping the ParallelCluster daemons and the Slurm daemons"
    if ((CLUSTERSTATUSMGTD)) && [[ "$("${SUPERVISORCTL}" status clusterstatusmgtd || true)" == *RUNNING* ]]; then
        "${SUPERVISORCTL}" stop clusterstatusmgtd
    fi
    if ((CLUSTERMGTD)) && [[ "$("${SUPERVISORCTL}" status clustermgtd || true)" == *RUNNING* ]]; then
        "${SUPERVISORCTL}" stop clustermgtd
    fi
    if unit_active slurmrestd; then systemctl stop slurmrestd; fi
    if unit_active slurmctld; then systemctl stop slurmctld; fi
    if unit_active slurmdbd; then systemctl stop slurmdbd; fi
}

# Step 3. Back up the Slurm controller state and the Slurm installation.
back_up() {
    local stamp state_dir state_backup_path installation_backup_path
    stamp="$(date -u +%Y%m%d-%H%M%S)"
    state_dir="$(conf_value StateSaveLocation)"
    if [[ -n "${state_dir}" && -d "${state_dir}" ]]; then
        state_backup_path="/opt/slurm_state_backup_${stamp}.tar.gz"
        log "Step 3: backing up ${state_dir} to ${state_backup_path}"
        tar -czf "${state_backup_path}" -C "$(dirname "${state_dir}")" "$(basename "${state_dir}")"
        tar -tzf "${state_backup_path}" >/dev/null || fail "The slurm state backup archive is not readable"
    else
        log "Step 3: no StateSaveLocation under ${PREFIX}/etc, so there is no controller state to back up here"
    fi
    installation_backup_path="/opt/slurm_backup_${stamp}.tar.gz"
    log "Step 3: backing up ${PREFIX} to ${installation_backup_path}"
    tar -czf "${installation_backup_path}" -C /opt slurm
    tar -tzf "${installation_backup_path}" >/dev/null || fail "The slurm installation backup archive is not readable"
}

# Step 4. Install the new Slurm version.
rebuild() {
    [[ -f "${SCRIPT_DIR}/rebuild_slurm.sh" ]] || fail "rebuild_slurm.sh is not next to this script in ${SCRIPT_DIR}"
    log "Step 4: running rebuild_slurm.sh with SLURM_VERSION_NEW=${SLURM_VERSION_NEW}${SLURM_SOURCE_URL:+ SLURM_SOURCE_URL=${SLURM_SOURCE_URL}}"
    bash "${SCRIPT_DIR}/rebuild_slurm.sh"
}

# Stop the slurmdbd start_slurmdbd_in_foreground runs: the Ctrl+C of the page, then SIGKILL if it does not stop.
stop_foreground_slurmdbd() {
    local pid="$1" waited=0
    kill -INT "${pid}" 2>/dev/null || true
    while kill -0 "${pid}" 2>/dev/null; do
        if ((waited >= SLURMDBD_STOP_TIMEOUT_SECONDS)); then
            log "slurmdbd did not stop within ${SLURMDBD_STOP_TIMEOUT_SECONDS} seconds of SIGINT, killing it"
            kill -KILL -- "-${pid}" 2>/dev/null || true
            pkill -KILL -f "^${PREFIX}/sbin/slurmdbd -D$" 2>/dev/null || true
            break
        fi
        sleep 1
        waited=$((waited + 1))
    done
    wait "${pid}" || true
}

# Step 5, first part: slurmdbd in the foreground as SlurmUser until it reports started, then Ctrl+C.
start_slurmdbd_in_foreground() {
    local slurm_user log_file offset pid elapsed=0
    slurm_user="$(conf_value SlurmUser)"
    slurm_user="${slurm_user:-slurm}"
    log_file="$(slurmdbd_log_file)"
    offset="$(log_length "${log_file}")"
    log "Step 5: starting slurmdbd in the foreground as ${slurm_user}. On the first start after a major upgrade it" \
        "converts the accounting database, which can take tens of minutes; watch ${log_file} and wait."
    # Job control gives sudo a process group of its own, as from a terminal: sudo does not relay a SIGINT sent from
    # the process group it was started in.
    set -m
    sudo -u "${slurm_user}" "${PREFIX}/sbin/slurmdbd" -D &
    pid=$!
    set +m
    # awk reads the file itself: under pipefail, a reader that stops early would make the writer fail with SIGPIPE.
    until awk -v offset="${offset}" 'NR > offset && /slurmdbd version .* started/ { found = 1; exit } END { exit !found }' \
        "${log_file}" 2>/dev/null; do
        if ! kill -0 "${pid}" 2>/dev/null; then
            wait "${pid}" || true
            fail "slurmdbd exited before it reported started. Read ${log_file}: this is almost always the database."
        fi
        if ((elapsed >= SLURMDBD_STARTUP_TIMEOUT_SECONDS)); then
            stop_foreground_slurmdbd "${pid}"
            fail "slurmdbd did not report started within ${SLURMDBD_STARTUP_TIMEOUT_SECONDS} seconds"
        fi
        sleep 10
        elapsed=$((elapsed + 10))
    done
    log "slurmdbd reported started after ${elapsed} seconds, stopping the foreground process"
    stop_foreground_slurmdbd "${pid}"
}

# Step 5. Start the daemons on the head node, exactly the ones recorded by record_daemons.
start_daemons() {
    if ((SLURMDBD)); then
        start_slurmdbd_in_foreground
        systemctl start slurmdbd
    fi
    log "Step 5: starting the Slurm daemons and the ParallelCluster daemons"
    if ((SLURMCTLD)); then systemctl start slurmctld; fi
    if ((SLURMRESTD)); then systemctl start slurmrestd; fi
    if ((CLUSTERSTATUSMGTD)); then "${SUPERVISORCTL}" start clusterstatusmgtd; fi
    if ((CLUSTERMGTD)); then "${SUPERVISORCTL}" start clustermgtd; fi
}

wait_for_controller() {
    local elapsed=0
    until "${PREFIX}/bin/scontrol" ping 2>/dev/null | grep -q 'is UP'; do
        ((elapsed < CONTROLLER_PING_TIMEOUT_SECONDS)) || fail "slurmctld did not answer scontrol ping within ${CONTROLLER_PING_TIMEOUT_SECONDS} seconds"
        sleep 10
        elapsed=$((elapsed + 10))
    done
}

# Step 7 checks 1, 2, 3 and 5, which need no compute node, or Appendix A.7 on an external Slurmdbd instance.
verify() {
    local expected_version="$1" slurmctld_log_offset="$2" version log_file lines status port elapsed=0
    version="$(installed_version)"
    log "Step 7.1: installed Slurm version is ${version}"
    [[ -z "${expected_version}" || "${version}" == "${expected_version}" ]] ||
        fail "Installed Slurm version ${version} does not match ${expected_version}"

    if ((SLURMCTLD)); then
        wait_for_controller
        log_file="$(slurmctld_log_file)"
        log "Step 7.1: $("${PREFIX}/bin/sinfo" -V); $("${PREFIX}/bin/scontrol" ping)"
        log "Step 7.1: $(grep 'slurmctld version' "${log_file}" 2>/dev/null | tail -n 1)"
        lines="$(tail -n "+$((slurmctld_log_offset + 1))" "${log_file}" 2>/dev/null |
            grep -iE 'defunct|obsolete|ignoring|no longer supported|fatal' | tail -n 20 || true)"
        if [[ -n "${lines}" ]]; then
            log "Step 7.2: slurmctld reported these lines about the existing configuration, correct them in your cluster configuration:"
            printf '%s\n' "${lines}"
            grep -qi 'fatal' <<<"${lines}" && fail "slurmctld logged a fatal error"
        fi
    fi

    if [[ -n "${SUPERVISORCTL}" ]]; then
        status="$("${SUPERVISORCTL}" status || true)"
        log "Step 7.3: supervisorctl status:"
        printf '%s\n' "${status}"
        if ((CLUSTERSTATUSMGTD)); then grep -qE '^clusterstatusmgtd[[:space:]]+RUNNING' <<<"${status}" || fail "clusterstatusmgtd is not running"; fi
        if ((CLUSTERMGTD)); then grep -qE '^clustermgtd[[:space:]]+RUNNING' <<<"${status}" || fail "clustermgtd is not running"; fi
        log "Step 7.3: last lines of ${CLUSTERMGTD_LOG}:"
        tail -n 50 "${CLUSTERMGTD_LOG}" 2>/dev/null || true
    fi

    if ((SLURMDBD)); then
        unit_active slurmdbd || fail "slurmdbd is not active"
        log_file="$(slurmdbd_log_file)"
        log "Step 7.5: $(grep 'slurmdbd version' "${log_file}" 2>/dev/null | tail -n 1)"
        if is_head_node; then
            # The conversion completed, not merely the daemon started.
            until "${PREFIX}/bin/sacctmgr" -n show clusters >/dev/null 2>&1; do
                ((elapsed < 120)) || fail "sacctmgr cannot read the accounting database"
                sleep 5
                elapsed=$((elapsed + 5))
            done
            log "Step 7.5: sacctmgr -n show clusters: $("${PREFIX}/bin/sacctmgr" -n show clusters | tr -s ' ' | tr '\n' ';')"
            log "Step 7.5: sacct -X --starttime now-7days | head:"
            "${PREFIX}/bin/sacct" -X --starttime now-7days | head || true
        else
            port="$(conf_value DbdPort)"
            port="${port:-${SLURMDBD_PORT_DEFAULT}}"
            until ss -ltn "sport = :${port}" | grep -q ":${port}"; do
                ((elapsed < 120)) || fail "slurmdbd is not listening on port ${port}"
                sleep 5
                elapsed=$((elapsed + 5))
            done
            log "Appendix A.7: slurmdbd is active and listens on port ${port}"
        fi
    fi
}

upgrade() {
    local current_version new_version slurmctld_log_offset
    (($# == 0)) || usage
    [[ -n "${SLURM_VERSION_NEW:-}" ]] || fail "Set SLURM_VERSION_NEW to the Slurm tag to install, for example slurm-25-11-8-1"
    new_version="$(version_of_tag "${SLURM_VERSION_NEW}")"
    current_version="$(installed_version)"
    [[ -n "${current_version}" ]] || fail "Unable to determine the Slurm version installed under ${PREFIX}"
    # Before Step 2 stops anything.
    [[ "${new_version}" != "${current_version}" &&
        "$(printf '%s\n' "${current_version}" "${new_version}" | sort -V | tail -n 1)" == "${new_version}" ]] ||
        fail "Slurm ${new_version} is not newer than the installed ${current_version}, there is nothing to upgrade"
    log "Upgrading Slurm ${current_version} to ${new_version} (${SLURM_VERSION_NEW})"
    record_daemons running
    warn_about_plugins "${current_version}" "${new_version}"

    slurmctld_log_offset="$(log_length "$(slurmctld_log_file)")"
    stop_daemons
    back_up
    rebuild
    start_daemons
    verify "${new_version}" "${slurmctld_log_offset}"
    log "Slurm ${new_version} is installed and the daemons are running. Continue with Step 6 of the page."
}

newest() { ls -1t "$@" 2>/dev/null | head -n 1 || true; }

# The major.minor release of the Slurm installation an archive of /opt/slurm holds, from its SLURM_VERSION_NUMBER.
archived_major_release() {
    local number
    number="$(tar -xzOf "$1" slurm/include/slurm/slurm_version.h 2>/dev/null |
        awk '$1 == "#define" && $2 == "SLURM_VERSION_NUMBER" { print $3; exit }' || true)"
    [[ -n "${number}" ]] || fail "Unable to read the Slurm version of $1"
    printf '%d.%02d\n' "$((number >> 16 & 0xff))" "$((number >> 8 & 0xff))"
}

# Replace the contents of a directory with those of an archive, keeping the directory: /opt/slurm is an EFS mount point
# (SharedStorageType: Efs) or an NFS export the login nodes keep mounted. The current contents are archived first.
restore_in_place() {
    local dir="$1" archive="$2" aside
    [[ "${dir}" == /?*/?* && -d "${dir}" ]] || fail "Refusing to restore '${dir}' in place: not a directory below /"
    aside="${dir}_rollback_aside_$(date -u +%Y%m%d-%H%M%S).tar.gz"
    log "Archiving the current contents of ${dir} to ${aside}"
    tar -czf "${aside}" -C "$(dirname "${dir}")" "$(basename "${dir}")"
    find "${dir}" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    tar -xzf "${archive}" -C "$(dirname "${dir}")"
}

rollback() {
    local install_backup="" state_backup="" accounting_backup="" state_dir slurmctld_log_offset current_version restored_major
    while (($# > 0)); do
        case "$1" in
            --install-backup) install_backup="${2:-}"; shift 2 ;;
            --state-backup) state_backup="${2:-}"; shift 2 ;;
            --accounting-backup) accounting_backup="${2:-}"; shift 2 ;;
            *) usage ;;
        esac
    done
    install_backup="${install_backup:-$(newest /opt/slurm_backup_*.tar.gz)}"
    [[ -f "${install_backup}" ]] || fail "No Slurm installation backup found, expected /opt/slurm_backup_<timestamp>.tar.gz"
    state_dir="$(conf_value StateSaveLocation)"
    if [[ -n "${state_dir}" ]]; then
        state_backup="${state_backup:-$(newest /opt/slurm_state_backup_*.tar.gz)}"
        [[ -f "${state_backup}" ]] || fail "No Slurm state backup found, expected /opt/slurm_state_backup_<timestamp>.tar.gz"
    fi
    [[ -z "${accounting_backup}" || -f "${accounting_backup}" ]] || fail "${accounting_backup} does not exist"
    current_version="$(installed_version)"
    log "Rolling Slurm ${current_version} back with ${install_backup}${state_backup:+ and ${state_backup}}${accounting_backup:+ and ${accounting_backup}}"
    record_daemons configured
    # Before anything stops: an older slurmdbd cannot read the database a newer major release converted.
    restored_major="$(archived_major_release "${install_backup}")"
    if ((SLURMDBD)) && [[ -z "${accounting_backup}" && "${restored_major}" != "${current_version%.*}" ]]; then
        fail "Rolling Slurm ${current_version} back to ${restored_major} crosses a major release on a node that runs" \
            "slurmdbd: pass the --accounting-backup taken before the upgrade (Step 3.2)"
    fi

    # Appendix D.1: the daemons are stopped, and the ones this node is configured to run come back in D.6.
    slurmctld_log_offset="$(log_length "$(slurmctld_log_file)")"
    stop_daemons

    # Appendix D.2: restore /opt/slurm.
    log "Appendix D.2: restoring ${PREFIX} from ${install_backup}"
    restore_in_place "${PREFIX}" "${install_backup}"
    ldconfig
    log "Appendix D.2: restored Slurm version is $(installed_version)"

    # Appendix D.3: restore the controller state.
    if [[ -n "${state_backup}" ]]; then
        log "Appendix D.3: restoring ${state_dir} from ${state_backup}"
        restore_in_place "${state_dir}" "${state_backup}"
    fi

    # Appendix D.4: restore the accounting database, only needed after a major release upgrade.
    if [[ -n "${accounting_backup}" ]]; then
        [[ -f "${SCRIPT_DIR}/slurm_accounting_database.sh" ]] || fail "slurm_accounting_database.sh is not next to this script in ${SCRIPT_DIR}"
        log "Appendix D.4: restoring the accounting database from ${accounting_backup}"
        bash "${SCRIPT_DIR}/slurm_accounting_database.sh" restore "${accounting_backup}"
    fi

    log "Appendix D.5: revert the plugins you rebuilt for the new version, if any"
    # Appendix D.6: start the daemons as in Step 5 and verify as in Step 7.
    start_daemons
    verify "" "${slurmctld_log_offset}"
    log "Slurm $(installed_version) is restored and the daemons are running. Start the compute fleet as in Step 6."
}

main() {
    [[ ${EUID} -eq 0 ]] || fail "Run this script as root"
    case "${1:-}" in
        upgrade) shift; upgrade "$@" ;;
        rollback) shift; rollback "$@" ;;
        *) usage ;;
    esac
}

main "$@"
