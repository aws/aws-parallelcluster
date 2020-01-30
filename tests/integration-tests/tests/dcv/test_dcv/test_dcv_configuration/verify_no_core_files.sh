#!/bin/bash
set -x

CRASHDIR=/var/crash

# There are no crash files if the directory doesn't exist
[ -d ${CRASHDIR} ] || exit 0

# Exit nonzero if there are any files
crash_files="$(ls -A ${CRASHDIR})"
if [ -n "${crash_files}" ]; then
  echo "Found crash files in ${CRASHDIR}: ${crash_files}"
  exit 1
fi
