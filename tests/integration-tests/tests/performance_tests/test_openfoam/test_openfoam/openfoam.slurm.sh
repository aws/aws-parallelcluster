# Absolute path to the SubspaceBenchmarks repository
# E.g.: /shared/ec2-user/SubspaceBenchmarks
SUBSPACE_BENCHMARKS_PATH=${1}

# NumProcesses / (vCPUS / 2); valid NumProcesses are 288, 576, 1152 as per https://t.corp.amazon.com/D39020520
# E.g.: with 1152 processes using compute nodes c5n.18xlarge with multithreading disabled, the value should be 1152 / (72/2) = 32
# E.g.: with 576 processes using compute nodes c5n.18xlarge with multithreading disabled, the value should be 576 / (72/2) = 16
# E.g.: with 288 processes using compute nodes c5n.18xlarge with multithreading disabled, the value should be 288 / (72/2) = 8
NODES=${2}

[[ -z ${SUBSPACE_BENCHMARKS_PATH} ]] && echo "[ERROR] SUBSPACE_BENCHMARKS_PATH missing" && exit 1
[[ -z ${NODES} ]] && echo "[ERROR] NODES missing" && exit 1

export TARGET_ENVIRONMENT='slurm' # may bve also mpi, but the you must specify MPI_HOST_FILE
# export MPI_HOST_FILE=${HOST_FILE}
export MPI_LIBRARY=ompi
export MPI_INSTALL_PATH=/opt/amazon/openmpi
export MIN_NODES=${NODES}
export NUM_NODES=${NODES}
export PACKAGE_TYPE=rpm

cd ${SUBSPACE_BENCHMARKS_PATH}

./apps/openfoam/run.sh
