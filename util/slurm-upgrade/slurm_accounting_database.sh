#!/bin/bash
#
# Back up or restore the Slurm accounting database of an AWS ParallelCluster cluster.
#
# Run it as root on the host that runs slurmdbd. The first slurmdbd of a new major release converts the schema one way,
# so a dump taken before the upgrade is what makes a cross major release rollback possible.
#
# Usage: slurm_accounting_database.sh backup [<path>]
#        slurm_accounting_database.sh restore <path>

set -euo pipefail

readonly ETC_DIR="/opt/slurm/etc"
DEFAULT_BACKUP_PATH="/opt/slurm_accounting_backup_$(date -u +%Y%m%d-%H%M%S).sql.gz"
readonly DEFAULT_BACKUP_PATH

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

usage() {
    printf 'Usage: %s backup [<path>]\n       %s restore <path>\n' "$0" "$0" >&2
    exit 2
}

[[ ${EUID} -eq 0 ]] || fail "Run this script as root"
command -v mysqldump >/dev/null || fail "mysqldump is not installed. Install the MySQL client package first."
command -v mysql >/dev/null || fail "mysql is not installed. Install the MySQL client package first."

# A setting from the .conf files under /opt/slurm/etc, the last assignment winning as for slurmdbd.
setting() {
    # An unset setting prints nothing and succeeds; the callers check for empty values.
    { grep -hE "^[[:space:]]*$1[[:space:]]*=" "${ETC_DIR}"/*.conf 2>/dev/null || true; } |
        tail -n 1 |
        sed -E "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//; s/[[:space:]]*$//"
}

DB_HOST="$(setting StorageHost)"
DB_PORT="$(setting StoragePort)"
DB_USER="$(setting StorageUser)"
DB_PASSWORD="$(setting StoragePass)"
DB_NAME="$(setting StorageLoc)"
readonly DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME

[[ -n "${DB_HOST}" ]] || fail "StorageHost is not configured under ${ETC_DIR}, so this host runs no slurmdbd"
[[ -n "${DB_USER}" ]] || fail "StorageUser is not configured under ${ETC_DIR}"
[[ -n "${DB_NAME}" ]] || fail "StorageLoc is not configured under ${ETC_DIR}"
# ParallelCluster replaces the placeholder with the password from Secrets Manager after writing the file.
[[ -n "${DB_PASSWORD}" && "${DB_PASSWORD}" != "dummy" ]] ||
    fail "StoragePass under ${ETC_DIR} still holds the placeholder, so the database password is not available"

# An option file keeps the password out of ps. Backslashes and double quotes are special in its quoted values.
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
# The database template of ParallelCluster sets require_secure_transport: fail clearly on the client side.
ssl-mode=REQUIRED
EOF

backup() {
    local path="${1:-${DEFAULT_BACKUP_PATH}}"
    log "Dumping accounting database ${DB_NAME} from ${DB_HOST} to ${path}"
    # --single-transaction: a consistent snapshot without locking the tables slurmdbd writes to.
    # --add-drop-database: restoring drops the converted database instead of merging into it.
    # --set-gtid-purged=OFF: no GTID statements, which need SUPER, unavailable on RDS and Aurora.
    mysqldump --defaults-file="${DEFAULTS_FILE}" \
        --single-transaction \
        --routines \
        --add-drop-database \
        --set-gtid-purged=OFF \
        --databases "${DB_NAME}" |
        gzip -c > "${path}.partial"
    mv "${path}.partial" "${path}"
    chmod 600 "${path}"
    # A dump truncated by a full disk would otherwise go unnoticed until it is needed.
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
