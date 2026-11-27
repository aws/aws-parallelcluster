#!/bin/bash
# Restricts GPU access to root and to the members of a group (default: pcluster-gpuusers).
#
# On GPU nodes it sets the NVIDIA driver parameters so that /dev/nvidia* are owned by root:<group> with mode 0660,
# and reloads the driver so that the parameters take effect. On a head node with DCV, the display stack (GDM, Xorg)
# and the DCV server are stopped during the reload and started again afterwards: active DCV sessions are closed.
# On nodes without NVIDIA GPUs it only makes sure the group exists.
#
# Slurm resolves the user's groups on the head node and sends them with each job: manage the members of the group
# on the head node (usermod -aG <group> <user>) or in your directory service.
#
# Usage:
#   gpu-group-gate.sh <gid> [<group-name>] [<user>[,<user>...]]
#     <gid>         mandatory: GID of the group, the same on every node of the cluster. If the group does not exist
#                   it is created as a local group with this GID; if it exists, its GID must match.
#     <group-name>  optional, default: pcluster-gpuusers
#     <users>       optional: comma-separated users to add to the group on this node. On a head node with DCV, pass
#                   the users that need the GPU for DCV: gdm (login screen) and the owners of the DCV sessions.
set -euo pipefail

# OnNodeUpdated runs with PATH=/usr/local/bin:/bin:/usr/bin:/opt/aws/bin: add the sbin directories
# (groupadd, lspci, rmmod, modprobe)
export PATH="/usr/local/sbin:/usr/sbin:/sbin:${PATH}"

GPU_GID_ARG="${1:-}"
GPU_GROUP="${2:-pcluster-gpuusers}"
GPU_USERS="${3:-}"
MODPROBE_CONF=/etc/modprobe.d/nvidia-gpu-group-gate.conf

function log() { echo "[gpu-group-gate] INFO: $*"; }
function fail() { echo "[gpu-group-gate] ERROR: $*" >&2; exit 1; }

if ! [[ "${GPU_GID_ARG}" =~ ^[0-9]+$ ]]; then
  fail "Missing or invalid GID '${GPU_GID_ARG}': usage: $0 <gid> [<group-name>] [<user>[,<user>...]]"
fi

# ---------------------------------------------------------------------------
# 1. Group: check the existing one or create an empty local one with the given GID
# ---------------------------------------------------------------------------
if getent group "${GPU_GROUP}" >/dev/null; then
  GPU_GID=$(getent group "${GPU_GROUP}" | cut -d: -f3)
  log "Group ${GPU_GROUP} resolves to GID ${GPU_GID}"
  if [ "${GPU_GID_ARG}" != "${GPU_GID}" ]; then
    fail "Group ${GPU_GROUP} has GID ${GPU_GID} on this node, expected ${GPU_GID_ARG}"
  fi
else
  if getent group "${GPU_GID_ARG}" >/dev/null; then
    fail "GID ${GPU_GID_ARG} is already used by group $(getent group "${GPU_GID_ARG}" | cut -d: -f1)"
  fi
  groupadd -g "${GPU_GID_ARG}" "${GPU_GROUP}"
  GPU_GID="${GPU_GID_ARG}"
  log "Created local group ${GPU_GROUP} with GID ${GPU_GID}"
fi

# ---------------------------------------------------------------------------
# 2. Members passed as argument
# ---------------------------------------------------------------------------
if [ -n "${GPU_USERS}" ]; then
  IFS=',' read -r -a users <<< "${GPU_USERS}"
  for user in "${users[@]}"; do
    id "${user}" >/dev/null 2>&1 || fail "User ${user} does not exist on $(hostname)"
    usermod -aG "${GPU_GROUP}" "${user}"
    log "Added ${user} to ${GPU_GROUP}"
  done
fi

# ---------------------------------------------------------------------------
# 3. Nodes without NVIDIA GPUs: nothing else to do
# ---------------------------------------------------------------------------
if ! command -v nvidia-smi >/dev/null || ! lspci 2>/dev/null | grep -i nvidia >/dev/null; then
  log "No NVIDIA GPU on $(hostname): group configured, driver unchanged"
  exit 0
fi

# ---------------------------------------------------------------------------
# 4. NVIDIA driver parameters
# ---------------------------------------------------------------------------
echo "options nvidia NVreg_DeviceFileUID=0 NVreg_DeviceFileGID=${GPU_GID} NVreg_DeviceFileMode=0660" > "${MODPROBE_CONF}"
log "Wrote ${MODPROBE_CONF}"

# The DCGM host engine (nvidia-dcgm service, used by the GPU Health Check) runs the diagnostics as the service
# account nvidia-dcgm with only its primary group (DCGM DropPrivs: setgroups(1, &pw_gid)), so supplementary
# membership is ignored: make the GPU group the primary group of nvidia-dcgm.
usermod -g "${GPU_GROUP}" nvidia-dcgm

# ---------------------------------------------------------------------------
# 5. Reload the driver, unless the parameters are already in effect
# ---------------------------------------------------------------------------
function current_params() {
  grep -E '^(DeviceFileUID|DeviceFileGID|DeviceFileMode):' /proc/driver/nvidia/params 2>/dev/null | tr -d ' ' | sort
}
expected_params=$(printf 'DeviceFileGID:%s\nDeviceFileMode:432\nDeviceFileUID:0\n' "${GPU_GID}" | sort)  # 432 = 0660

RELOAD_STARTED=""
STOPPED_SERVICES=""
REMOVED_MODULES=""
STOPPED_DISPLAY=""

# If the reload fails: start again what was stopped, and remove the driver parameters so that a reboot does not
# apply a configuration that was not validated.
function restore() {
  local rc=$?
  if [ "${rc}" -ne 0 ] && [ -n "${RELOAD_STARTED}" ]; then
    echo "[gpu-group-gate] ERROR: reload failed, restoring the NVIDIA stack" >&2
    rm -f "${MODPROBE_CONF}"
    for m in ${REMOVED_MODULES}; do modprobe "$m" || true; done
    for s in ${STOPPED_SERVICES}; do systemctl start "$s" || true; done
    if [ -n "${STOPPED_DISPLAY}" ]; then
      systemctl isolate graphical.target || true
      systemctl start dcvserver || true
    fi
  fi
}
trap restore EXIT

if [ "$(current_params)" != "${expected_params}" ]; then
  log "Reloading the NVIDIA driver"
  RELOAD_STARTED=yes

  # DCV (head node): the DCV sessions and the display stack (GDM, Xorg, GNOME) keep the GPUs open
  if systemctl is-active -q gdm; then
    log "Stopping DCV and the display stack: active DCV sessions are closed"
    STOPPED_DISPLAY=yes
    systemctl stop dcvserver || true
    systemctl isolate multi-user.target
    for _ in $(seq 1 30); do pgrep -x Xorg >/dev/null || break; sleep 1; done
  fi

  # Services that keep the GPUs open. parallelcluster_nvidia is the ParallelCluster service that runs
  # nvidia-persistenced.
  for s in parallelcluster_nvidia nvidia-persistenced nvidia-fabricmanager nvidia-dcgm; do
    if systemctl is-active -q "$s"; then
      systemctl stop "$s"
      STOPPED_SERVICES="${STOPPED_SERVICES} $s"
    fi
  done
  # nvidia-persistenced started outside systemd
  if pgrep -x nvidia-persistenced >/dev/null; then
    pkill -x nvidia-persistenced
    for _ in $(seq 1 10); do pgrep -x nvidia-persistenced >/dev/null || break; sleep 1; done
  fi

  for m in gdrdrv nvidia_peermem nvidia_uvm nvidia_drm nvidia_modeset nvidia; do
    if lsmod | grep -q "^${m} "; then
      if ! rmmod "$m"; then
        log "Processes using the GPUs:"
        fuser -v /dev/nvidia* 2>&1 || true
        fail "Unable to unload kernel module $m"
      fi
      REMOVED_MODULES="$m ${REMOVED_MODULES}"   # reversed: reload in dependency order
    fi
  done

  rm -f /dev/nvidiactl /dev/nvidia[0-9]*
  modprobe nvidia
  for m in ${REMOVED_MODULES}; do
    [ "$m" = nvidia ] || modprobe "$m"
  done
  nvidia-smi >/dev/null   # recreates the device files with the new ownership and mode

  for s in ${STOPPED_SERVICES}; do systemctl start "$s"; done

  if [ -n "${STOPPED_DISPLAY}" ]; then
    systemctl isolate graphical.target
    for _ in $(seq 1 60); do pgrep -x Xorg >/dev/null && break; sleep 1; done
    pgrep -x Xorg >/dev/null || fail "Xorg did not start after the driver reload: check that gdm is in ${GPU_GROUP}"
    systemctl start dcvserver
    log "Display stack and DCV started again"
  fi
else
  log "Driver parameters already in effect"
fi

# ---------------------------------------------------------------------------
# 6. Check
# ---------------------------------------------------------------------------
for dev in /dev/nvidiactl /dev/nvidia[0-9]*; do
  actual=$(stat -c '%u:%g %a' "${dev}")
  [ "${actual}" = "0:${GPU_GID} 660" ] || fail "${dev} is ${actual}, expected 0:${GPU_GID} 660"
done
RELOAD_STARTED=""
log "GPU access restricted to root and members of ${GPU_GROUP} (GID ${GPU_GID}) on $(hostname)"
