#!/bin/bash
#
# Back up or restore the Slurm accounting database of an AWS ParallelCluster cluster.
#
# Run it as root on the host that runs slurmdbd: the head node of a cluster that keeps its accounting
# database locally, or the external slurmdbd instance.
#
# The first slurmdbd of a new Slurm major release converts the accounting database schema, and that
# conversion is one way: the previous slurmdbd cannot read the converted database. A dump taken before
# the upgrade is therefore the only thing that makes a cross major version rollback possible.
#
# Usage: slurm_accounting_database.sh backup [<path>]
#        slurm_accounting_database.sh restore <path>

set -euo pipefail

readonly ETC_DIR="/opt/slurm/etc"
readonly DEFAULT_BACKUP_PATH="/opt/slurm_accounting_backup_$(date -u +%Y%m%d-%H%M%S).sql.gz"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

usage() {
    printf 'Usage: %s backup [<path>]\n       %s restore <path>\n' "$0" "$0" >&2
    exit 2
}

[[ ${EUID} -eq 0 ]] || fail "Run this script as root"
command -v mysqldump >/dev/null || fail "mysqldump is not installed. Install the MySQL client package first."
command -v mysql >/dev/null || fail "mysql is not installed. Install the MySQL client package first."

# slurmdbd reads its connection settings from slurmdbd.conf and from the file that includes, and the last
# assignment of a setting is the one that takes effect. Both files are only readable by root and the Slurm
# user, and which of them holds the settings differs between a head node and an external slurmdbd instance,
# so all of them are read and the last assignment wins, exactly as slurmdbd does it.
setting() {
    grep -hE "^[[:space:]]*$1[[:space:]]*=" "${ETC_DIR}"/*.conf 2>/dev/null |
        tail -n 1 |
        sed -E "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//; s/[[:space:]]*$//"
}

readonly DB_HOST="$(setting StorageHost)"
readonly DB_PORT="$(setting StoragePort)"
readonly DB_USER="$(setting StorageUser)"
readonly DB_PASSWORD="$(setting StoragePass)"
readonly DB_NAME="$(setting StorageLoc)"

[[ -n "${DB_HOST}" ]] || fail "StorageHost is not configured under ${ETC_DIR}, so this host runs no slurmdbd"
[[ -n "${DB_USER}" ]] || fail "StorageUser is not configured under ${ETC_DIR}"
[[ -n "${DB_NAME}" ]] || fail "StorageLoc is not configured under ${ETC_DIR}"
# ParallelCluster writes the placeholder first and replaces it with the real password from Secrets Manager
# afterwards, so the placeholder means the credentials are not usable yet rather than that they are missing.
[[ -n "${DB_PASSWORD}" && "${DB_PASSWORD}" != "dummy" ]] ||
    fail "StoragePass under ${ETC_DIR} still holds the placeholder, so the database password is not available"

# The password goes into an option file rather than onto the command line, where every user on the host
# would see it in the output of ps. Backslashes and double quotes are escaped because a MySQL option file
# treats them as escape and quoting characters inside a quoted value.
escaped_password="${DB_PASSWORD//\\/\\\\}"
escaped_password="${escaped_password//\"/\\\"}"
DEFAULTS_FILE="$(mktemp /root/.slurm_accounting_database.cnf.XXXXXX)"
readonly DEFAULTS_FILE
chmod 600 "${DEFAULTS_FILE}"
trap 'rm -f "${DEFAULTS_FILE}"' EXIT
cat > "${DEFAULTS_FILE}" <<EOF
[client]
host=${DB_HOST}
port=${DB_PORT:-3306}
user=${DB_USER}
password="${escaped_password}"
# The database template ParallelCluster publishes sets require_secure_transport, so an unencrypted
# connection is refused by the server anyway. Requesting encryption here makes that a client side error
# with a clear message instead of a server side rejection.
ssl-mode=REQUIRED
EOF

backup() {
    local path="${1:-${DEFAULT_BACKUP_PATH}}"
    log "Dumping accounting database ${DB_NAME} from ${DB_HOST} to ${path}"
    # --single-transaction dumps a consistent snapshot without locking the tables slurmdbd is writing to,
    #   so the dump can be taken while the cluster is still in service.
    # --add-drop-database is what makes the dump able to undo a schema conversion: restoring it drops the
    #   converted database instead of merging into it, which would leave the new tables behind.
    # --set-gtid-purged=OFF keeps the dump free of the GTID statements that only a user with SUPER can
    #   replay, which the administrative user of an RDS or Aurora instance is not.
    mysqldump --defaults-file="${DEFAULTS_FILE}" \
        --single-transaction \
        --routines \
        --add-drop-database \
        --set-gtid-purged=OFF \
        --databases "${DB_NAME}" |
        gzip -c > "${path}.partial"
    mv "${path}.partial" "${path}"
    chmod 600 "${path}"
    # Reading the archive back proves it is a complete gzip stream, which "the file exists" does not: a
    # dump truncated by a full disk looks identical until someone actually needs to restore it.
    gzip --test "${path}" || fail "${path} is not a valid gzip archive"
    log "Accounting database backup written to ${path} ($(du -h "${path}" | cut -f1))"
}

restore() {
    local path="$1"
    [[ -f "${path}" ]] || fail "${path} does not exist"
    gzip --test "${path}" || fail "${path} is not a valid gzip archive"
    systemctl is-active --quiet slurmdbd.service &&
        fail "slurmdbd is still running. Stop it before restoring the accounting database."
    log "Restoring accounting database ${DB_NAME} on ${DB_HOST} from ${path}"
    gzip -dc "${path}" | mysql --defaults-file="${DEFAULTS_FILE}"
    log "Restored accounting database ${DB_NAME} from ${path}"
}

case "${1:-}" in
    backup) backup "${2:-}" ;;
    restore) [[ $# -eq 2 ]] || usage; restore "$2" ;;
    *) usage ;;
esac
