#!/bin/bash
#SBATCH --job-name=cuda-gpu-validate
#SBATCH --output=cuda-gpu-validate-%j.out

# Build and run a single CUDA sample (passed as a script argument) from the
# pre-installed /usr/local/cuda-samples-* tree. CUDA samples 13.x are
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

# Pick whichever cuda-samples-<ver> tree is installed (version not hardcoded).
SAMPLES_SRC=$(ls -d /usr/local/cuda-samples-* 2>/dev/null | sort -V | tail -1)
if [[ -z "$SAMPLES_SRC" ]]; then
    echo "ERROR: no /usr/local/cuda-samples-* tree found" >&2
    exit 2
fi

# 13.3+ moved C++ samples under cpp/; older trees keep them under Samples/.
if [[ -d "$SAMPLES_SRC/cpp/$SAMPLE_REL" ]]; then
    SAMPLE_ROOT="$SAMPLES_SRC/cpp"
elif [[ -d "$SAMPLES_SRC/Samples/$SAMPLE_REL" ]]; then
    SAMPLE_ROOT="$SAMPLES_SRC/Samples"
else
    echo "ERROR: sample not found under $SAMPLES_SRC (cpp/ or Samples/): $SAMPLE_REL" >&2
    exit 2
fi

# /opt/parallelcluster/tmp is the node-local scratch area with room for a CUDA sample build, but it is not
# guaranteed to exist on every OS/architecture combination, so create it rather than assume it.
BUILD_BASE=/opt/parallelcluster/tmp
sudo -n mkdir -p "$BUILD_BASE"
WORKDIR=$(sudo -n mktemp -d "${BUILD_BASE}/pcluster-cuda-samples.XXXXXX")
sudo -n chown "$(id -u):$(id -g)" "$WORKDIR"
export TMPDIR="$WORKDIR"
trap 'sudo rm -rf "$WORKDIR"' EXIT

# Shared scaffolding required by every sample (Common/, top-level cmake/)
cp -r "$SAMPLES_SRC"/{Common,cmake,CMakeLists.txt} "$WORKDIR"/

DST="$WORKDIR/samples/$SAMPLE_REL"
mkdir -p "$(dirname "$DST")"
cp -r "$SAMPLE_ROOT/$SAMPLE_REL" "$DST"

# Some AMIs ship the samples tree already configured, and a CMake cache records the absolute path it was generated
# for, so cmake refuses to reuse the copy ("The current CMakeCache.txt directory ... is different than the directory
# ..."). Drop every trace of the inherited configuration so the copy is configured from scratch.
find "$DST" -name CMakeCache.txt -delete
find "$DST" -name CMakeFiles -type d -prune -exec rm -rf {} +
rm -rf "$DST/build"

echo "===== Building $SAMPLE_REL ====="
cmake -S "$DST" -B "$DST/build"
cmake --build "$DST/build" -j"${SLURM_CPUS_PER_TASK:-2}"

echo "===== Running $SAMPLE_NAME ====="
"$DST/build/$SAMPLE_NAME"
