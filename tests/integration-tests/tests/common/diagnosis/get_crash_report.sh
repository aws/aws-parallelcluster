#!/bin/bash
# Scans for crash files based on the detected OS and outputs a JSON
# dictionary: { "crash_file_path": "content", ... }
# Exits 0 on supported OSes (even when crashes are found) — the caller decides whether to fail.
# Exits 1 on unsupported OSes or when /etc/os-release is missing/incomplete.
# Log lines are emitted to stderr so they don't pollute the JSON on stdout.

SCRIPT_NAME=$(basename "$0")

# This variable will be populated with a JSON object containing crash details.
crash_results=""

function log_info() {
  echo "[${SCRIPT_NAME}] INFO: $*" >&2
}

function log_error() {
  echo "[${SCRIPT_NAME}] ERROR: $*" >&2
}

function add_entry() {
  # Append a crash entry to the JSON output.
  # Uses python3 for safe JSON escaping of both the path and content.
  # Args:
  #   $1 - crash file path or identifier (e.g. "coredumpctl")
  #   $2 - human-readable crash content
  local path="$1"
  local content="$2"
  log_info "Adding crash entry: ${path}"
  if [ -n "${crash_results}" ]; then
    crash_results="${crash_results},"
  fi
  crash_results="${crash_results}$(python3 -c "
import json, sys
print(json.dumps(sys.argv[1]) + ': ' + json.dumps(sys.argv[2]))
" "${path}" "${content}")"
}

function read_crash_content() {
  # Read and return the human-readable content of a crash file or ABRT directory.
  # For Apport .crash files (Ubuntu): extracts key text fields using python3.
  # For ABRT directories: concatenates all text fields (skipping the coredump binary).
  # For text files: returns the last 100 lines.
  # For binary files: extracts printable strings (first 100 lines).
  # Args:
  #   $1 - path to a crash file or ABRT crash directory
  local filepath="$1"
  if [ -d "${filepath}" ]; then
    local content=""
    for field in "${filepath}"/*; do
      [ -f "${field}" ] || continue
      fname=$(basename "${field}")
      [ "${fname}" = "coredump" ] && continue
      if sudo file "${field}" 2>/dev/null | grep -q "text"; then
        content="${content}${fname}:\n$(sudo tail -100 "${field}")\n\n"
      fi
    done
    echo -e "${content}"
  elif echo "${filepath}" | grep -q '\.crash$'; then
    # Ubuntu Apport .crash files: extract human-readable fields.
    # Uses sudo because Apport crash files in /var/crash are owned by root.
    # Try the apport module first (always available on Ubuntu), fall back to manual parsing.
    # If no Stacktrace is found in the report, attempt to extract one from the CoreDump using gdb.
    sudo python3 -c "
import sys, subprocess, tempfile, os

APPORT_KEYS = ['ProblemType','Package','ExecutablePath','Signal','Traceback',
               'Stacktrace','StacktraceTop','ProcCmdline','Title','ErrorMessage']

def parse_with_apport(path):
    import apport
    r = apport.Report()
    with open(path, 'rb') as f:
        r.load(f)

    lines = []
    for k in APPORT_KEYS:
        if k in r:
            val = r[k] if isinstance(r[k], str) else r[k].decode('utf-8', errors='replace')
            lines.append(f'{k}: {val}')

    # If no Stacktrace in the report, try to extract one from the CoreDump via gdb
    if 'Stacktrace' not in r and 'CoreDump' in r and 'ExecutablePath' in r:
        try:
            with tempfile.NamedTemporaryFile(suffix='.core', delete=False) as tmp:
                tmp.write(r['CoreDump'])
                core_path = tmp.name
            exe = r['ExecutablePath']
            result = subprocess.run(
                ['gdb', '-batch', '-ex', 'thread apply all bt', exe, core_path],
                capture_output=True, text=True, timeout=30
            )
            os.unlink(core_path)
            bt = result.stdout.strip()
            if bt:
                lines.append(f'Stacktrace (from gdb): {bt}')
        except Exception as e:
            lines.append(f'Stacktrace extraction failed: {e}')

    return '\n'.join(lines) if lines else repr(dict((k, r[k]) for k in list(r.keys())[:20]))

def parse_manually(path):
    fields = {}
    current_key = None
    for raw in open(path, 'rb'):
        line = raw.decode('utf-8', errors='replace')
        if not line.startswith(' ') and ':' in line:
            key, _, val = line.partition(':')
            current_key = key.strip()
            fields[current_key] = val.strip()
        elif current_key and line.startswith(' '):
            fields[current_key] += '\n' + line.rstrip()
    return '\n'.join(f'{k}: {fields[k]}' for k in APPORT_KEYS if k in fields)

try:
    result = parse_with_apport(sys.argv[1])
except Exception:
    result = parse_manually(sys.argv[1])
print(result or 'Unable to parse Apport crash file')
" "${filepath}" 2>&1
  elif sudo file "${filepath}" 2>/dev/null | grep -q "text"; then
    sudo tail -100 "${filepath}"
  else
    sudo strings "${filepath}" 2>/dev/null | head -100
  fi
}

function scan_directory() {
  # Scan a directory for crash files and add each one to the report.
  # Used for Apport (/var/crash) and ABRT (/var/spool/abrt) crash stores.
  # Args:
  #   $1 - path to the crash directory to scan
  local crashdir="$1"
  log_info "Scanning directory ${crashdir}..."
  if [ ! -d "${crashdir}" ]; then
    log_info "Directory ${crashdir} does not exist, skipping."
    return
  fi
  local found=0
  while IFS= read -r -d '' filepath; do
    found=1
    log_info "Reading crash file: ${filepath}"
    content=$(read_crash_content "${filepath}")
    add_entry "${filepath}" "${content}"
  done < <(sudo find "${crashdir}" -mindepth 1 -maxdepth 1 -print0 2>/dev/null)
  if [ "${found}" -eq 0 ]; then
    log_info "No crash files found in ${crashdir}."
  fi
}

function scan_coredumpctl() {
  # Query systemd-coredump via coredumpctl for crash entries.
  # Used on OSes that use systemd-coredump (AL2023, RHEL9, Rocky9).
  # Adds a single "coredumpctl" entry with the first 500 lines of `coredumpctl info`.
  # Retries once if systemd-coredump is still processing a core dump.
  log_info "Checking coredumpctl for systemd-coredump entries..."
  if ! command -v coredumpctl > /dev/null 2>&1; then
    log_info "coredumpctl not found, skipping."
    return
  fi
  dump_list=$(coredumpctl list --no-pager --no-legend 2>/dev/null)
  if [ -z "${dump_list}" ]; then
    log_info "No coredump entries found via coredumpctl."
    return
  fi
  log_info "Found coredump entries via coredumpctl."

  local attempts=2
  local content=""
  for i in $(seq 1 ${attempts}); do
    # Merge stderr into stdout so we can filter notice lines from either stream.
    # Filter out "-- Notice:" lines that appear when systemd-coredump is still processing.
    content=$(coredumpctl info --no-pager 2>&1 | grep -vF -- '-- Notice:' | grep -vF 'No coredumps found.' | head -500)
    if [ -n "${content}" ]; then
      break
    fi
    log_info "coredumpctl info returned no crash content (attempt ${i}/${attempts}), waiting 5s..."
    sleep 5
  done

  if [ -n "${content}" ]; then
    add_entry "coredumpctl" "${content}"
  else
    log_info "coredumpctl info returned no crash content after ${attempts} attempts."
  fi
}

log_info "Detecting OS from /etc/os-release..."
if [ -f /etc/os-release ]; then
  . /etc/os-release
else
  log_error "/etc/os-release not found. Cannot determine OS."
  exit 1
fi

if [ -z "${ID}" ]; then
  log_error "Could not determine OS from /etc/os-release (ID is empty)."
  exit 1
fi

log_info "Detected OS: ID=${ID}, VERSION_ID=${VERSION_ID}"

log_info "Selecting crash scan strategy for OS '${ID}' version '${VERSION_ID}'..."
case "${ID}" in
  ubuntu)
    log_info "Using Apport strategy (Ubuntu)."
    scan_directory /var/crash
    ;;
  amzn)
    case "${VERSION_ID}" in
      2)
        log_info "Using ABRT + coredumpctl strategy (Amazon Linux 2)."
        scan_directory /var/spool/abrt
        scan_coredumpctl
        ;;
      2023)
        log_info "Using systemd-coredump strategy (Amazon Linux 2023)."
        scan_coredumpctl
        ;;
    esac
    ;;
  rhel)
    case "${VERSION_ID%%.*}" in
      8)
        log_info "Using ABRT + coredumpctl strategy (RHEL 8)."
        scan_directory /var/spool/abrt
        scan_coredumpctl
        ;;
      9)
        log_info "Using systemd-coredump strategy (RHEL 9)."
        scan_coredumpctl
        ;;
    esac
    ;;
  rocky)
    case "${VERSION_ID%%.*}" in
      8)
        log_info "Using ABRT + coredumpctl strategy (Rocky 8)."
        scan_directory /var/spool/abrt
        scan_coredumpctl
        ;;
      9)
        log_info "Using systemd-coredump strategy (Rocky 9)."
        scan_coredumpctl
        ;;
    esac
    ;;
  *)
    log_error "Unsupported OS '${ID}' (VERSION_ID='${VERSION_ID}'). Cannot determine crash file locations."
    exit 1
    ;;
esac

log_info "Crash scan complete."
echo "{${crash_results}}"
exit 0
