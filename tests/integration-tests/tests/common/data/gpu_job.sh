#!/bin/bash
#SBATCH --job-name=cuda-gpu-validate
#SBATCH --output=cuda-gpu-validate-%j.out

# Build and run a single CUDA sample (passed as a script argument) from the
# pre-installed /usr/local/cuda-samples-13.0 tree. CUDA samples 13.x are
# CMake-only and /usr/local/... isn't writable, so the script copies the
# sample into a temp dir before building.

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: sbatch $0 <category>/<sample>" >&2
    echo "  e.g. sbatch $0 1_Utilities/deviceQuery"  >&2
    exit 2
fi
SAMPLE_REL=$1
SAMPLE_NAME=${SAMPLE_REL##*/}

export PATH=/usr/local/cuda/bin:${PATH}

echo "Node: $(hostname)"
echo "Sample: $SAMPLE_REL"
echo "SLURM_JOB_GPUS=${SLURM_JOB_GPUS:-unset}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"
nvidia-smi -L
nvidia-smi
nvcc --version

SAMPLES_SRC=/usr/local/cuda-samples-13.0
if [[ ! -d "$SAMPLES_SRC/Samples/$SAMPLE_REL" ]]; then
    echo "ERROR: sample not found: $SAMPLES_SRC/Samples/$SAMPLE_REL" >&2
    exit 2
fi

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

# Shared scaffolding required by every sample (Common/, top-level cmake/)
cp -r "$SAMPLES_SRC"/{Common,cmake,CMakeLists.txt} "$WORKDIR"/

DST="$WORKDIR/Samples/$SAMPLE_REL"
mkdir -p "$(dirname "$DST")"
cp -r "$SAMPLES_SRC/Samples/$SAMPLE_REL" "$DST"

echo "===== Building $SAMPLE_REL ====="
cmake -S "$DST" -B "$DST/build"
cmake --build "$DST/build" -j"${SLURM_CPUS_PER_TASK:-2}"

echo "===== Running $SAMPLE_NAME ====="
"$DST/build/$SAMPLE_NAME"
