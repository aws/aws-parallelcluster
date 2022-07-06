#!/bin/bash
#
# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# Requirements: sudo, user be able to become root without password, ethtool, netstat

# Script to generate a system information archive.
# This script needs to be run by a user in sudoers and it takes an existing directory as argument

function log() {
  local LEVEL="INFO"
  if [ "${2}" != "" ]; then
    LEVEL="${2}"
  fi
  echo "$(date) - system-analyzer - ${LEVEL} - ${1}"
}

function body() {
  # Function to print the header passed in pipe and execute the argument
  # example: cat file_with_header.csv | body sort > file_with_header_but_sorted_body.csv
  IFS= read -r HEADER
  printf '%s\n' "${HEADER}"
  "${@}"
}

function _copy_if_exists() {
  if [ -e "${1}" ]; then
    cp -r "${1}" "${2}"
  else
    log "${1} do not exists" "WARNING"
  fi
}

function signal_handler() {
  # arg 1: return code
  # arg 2: line number of the error
  # arg 3: temporary directory to remove

  if [ "${1}" != "0" ]; then
    log "Catching a signal" "ERROR"
    rm -fr "${BASE_TEMP_DIR}"
    log "Return code:${1} occurred on line ${2} - Deleted ${3}" "ERROR"
    exit "${1}"
  fi
}

function _save_installed_services_timers() {
  log "Save installed services and timer"
  local OUT_DIR=${1}

  # Save installed services
  systemctl --all --type=service --state running,active | head -n -7 | body sort -du > "${OUT_DIR}"/services_active
  systemctl list-unit-files --state enabled,generated | head -n -2 | body sort -du > "${OUT_DIR}"/services_enabled

  # Save timers
  systemctl list-timers | head -n -3 | body sort -du > "${OUT_DIR}"/timers
}

function _save_scheduled_commands() {
  log "Save scheduled commands"
  local OUT_DIR=${1}
  local OS=${2}
  local OS_VERSION=${3}

  # Save scheduled commands and scripts
  mkdir "${OUT_DIR}"/etc_cron
  mkdir "${OUT_DIR}"/spool_cron


  _copy_if_exists /etc/cron* "${OUT_DIR}"/etc_cron
  _copy_if_exists /var/spool/cron "${OUT_DIR}"/spool_cron

  _copy_if_exists /etc/anacrontab "${OUT_DIR}"/etc_cron
  _copy_if_exists /var/spool/anacron "${OUT_DIR}"/spool_cron

  _copy_if_exists /var/spool/at "${OUT_DIR}"/spool_cron

}

function _network_info() {
  log "Save network information"
  local OUT_DIR="${1}/network/"

  # Save meaningful network statistic
  mkdir "${OUT_DIR}"
  for network in $(ip link | egrep "^[0-9]+" | awk -F\: '{print $2}' | tr -d " " | grep -v "lo"); do
    ethtool -S "${network}" > "${OUT_DIR}"/eth0_stats
  done
  netstat -s > "${OUT_DIR}"/netstat_stats
  ip address > "${OUT_DIR}"/address
}

function _save_avail_mpi() {
  log "Save mpi versions"
  local OUT_DIR="${1}/mpi/"

  # Save available mpi
  mkdir "${OUT_DIR}"
  MODULES="$(echo "${MODULEPATH}" | tr : '\n')"
  set +e +o pipefail
  MPI_MODULES=$(for MODULE in $MODULES; do
    ls -1 "${MODULE}" 2>/dev/null | grep -i mpi;
    done)
  set -e -o pipefail
  for MPI_MODULE in $MPI_MODULES
  do
    module load "${MPI_MODULE}" 2>&1 1>/dev/null
    mpirun --version > "${OUT_DIR}"/"${MPI_MODULE}"
    module unload "${MPI_MODULE}" 2>&1 1>/dev/null
  done
}

function _save_imds_info() {
  log "Save IMDSv2 information"
  # Misc IMDS info
  TOKEN="$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")"
  curl -s -H "X-aws-ec2-metadata-token: ${TOKEN}" http://169.254.169.254/latest/meta-data/ami-id > "${TEMP_DIR}"/ami-id
  curl -s -H "X-aws-ec2-metadata-token: ${TOKEN}" http://169.254.169.254/latest/meta-data/instance-type > "${TEMP_DIR}"/instance-type
  curl -s -H "X-aws-ec2-metadata-token: ${TOKEN}" http://169.254.169.254/latest/user-data > "${TEMP_DIR}"/user-data
}

function _is_user_root() {
  [ "${EUID:-$(id -u)}" -eq 0 ]
}

function main() {

  # Set switch to catch errors
  set -e -o pipefail

  # Check number of arguments
  if [ $# -ne 1 ]; then
    echo "usage: ${0} [directory]"
    echo "es. ${0} /tmp/"
    exit 1
  fi

  # Become root if not and re-execute the script itself
  if ! _is_user_root; then
    log "Running the script as root"
    sudo bash --login ${0} ${1}
    exit $?
  fi

  # Check if path exist
  if [ -d "${1}" ]; then
    log "Directory ${1} exists."
  else
    log "Directory ${1} does not exist - exiting"
    exit 1
  fi

  local RESULT_ARCHIVE="${1}/system-information.tar.gz"

  # temporary directory
  local BASE_TEMP_DIR="$(mktemp -d)"
  local TEMP_DIR="${BASE_TEMP_DIR}/system-information/"

  # Register signal handling to clean the temporary directory in case of kill, kill -9, ctrl+c, error in the script
  trap 'signal_handler ${?} ${LINENO} ${BASE_TEMP_DIR}' SIGINT SIGTERM SIGHUP INT ERR EXIT

  log "Create temporary directory"
  mkdir "${TEMP_DIR}"

  # Find os type and select package command
  local PACKAGE_REPORT_CMD=""
  local OS="$(grep "^ID=" /etc/os-release | cut -d"=" -f 2 | xargs)"

  case ${OS} in
    ubuntu)
      PACKAGE_REPORT_CMD="dpkg-query -l"
      ;;
    amzn | centos)
      PACKAGE_REPORT_CMD="rpm -qa"
      ;;
    *)
      echo "Unrecognized system. Found /etc/os-release ID content: ${OS}"
      exit 1
      ;;
  esac

  local OS_VERSION="$(grep "^VERSION_ID=" /etc/os-release | cut -d"=" -f 2 | xargs)"

  log "Save OS type and version"
  echo "${OS}" > "${TEMP_DIR}/os"
  echo "${OS_VERSION}" > "${TEMP_DIR}/os_version"

  # Save uname
  log "Save uname"
  uname -a > "${TEMP_DIR}/uname"

  # Save installed packages on system
  log "Save installed packages on system"
  ${PACKAGE_REPORT_CMD} | sort -du > "${TEMP_DIR}"/packages

  _save_installed_services_timers "${TEMP_DIR}"

  _save_scheduled_commands "${TEMP_DIR}" "${OS}" "${OS_VERSION}"

  _save_avail_mpi "${TEMP_DIR}"

  _network_info "${TEMP_DIR}"

  _save_imds_info "${TEMP_DIR}"

  # Save users info
  log "Save /etc/passwd content"
  cp /etc/passwd "${TEMP_DIR}/passwd"

  # Create the archive
  log "Create the archive"
  rm -fr "${RESULT_ARCHIVE}"
  cd "${TEMP_DIR}/.."
  tar -czf "${RESULT_ARCHIVE}" "system-information/" 1>/dev/null
  cd "/"
  rm -fr "${BASE_TEMP_DIR}"
  log "DONE"
}

log "START"
main "${@}"