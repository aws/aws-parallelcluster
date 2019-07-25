#!/bin/bash
set -e

_openmpi_module=$1
_remote_host=$2

if [ "${_openmpi_module}" != "no_module_available" ]; then
  module load ${_openmpi_module}
fi
$(which mpirun) --host ${_remote_host} hostname
