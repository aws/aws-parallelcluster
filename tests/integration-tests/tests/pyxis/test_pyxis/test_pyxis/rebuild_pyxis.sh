#!/bin/bash
# Appendix B.2 of https://github.com/aws/aws-parallelcluster/wiki/Upgrade-Slurm-in-an-AWS-ParallelCluster-cluster:
# rebuild the Pyxis SPANK plugin against /opt/slurm from the Pyxis sources of the AMI. Runs on the head node after
# Step 4, and on every compute node at boot as its OnNodeConfigured script.
set -euo pipefail

echo "Executing $0"
ls /opt/parallelcluster/sources/pyxis-*.tar.gz
# A fresh directory: in one a previous rebuild used, the sources look older than its objects (and the Slurm headers are
# not a make dependency), so make would install the plugin built against the previous Slurm.
build_dir="$(mktemp -d)"
trap 'rm -rf "${build_dir}"' EXIT
tar -xf "$(ls /opt/parallelcluster/sources/pyxis-*.tar.gz | sort -V | tail -n 1)" -C "${build_dir}" --strip-components=1
CPPFLAGS="-I/opt/slurm/include" make -C "${build_dir}"
sudo install -m 755 "${build_dir}/spank_pyxis.so" /usr/local/lib/slurm/spank_pyxis.so
echo "Rebuilt /usr/local/lib/slurm/spank_pyxis.so against $(/opt/slurm/sbin/slurmd -V 2>/dev/null || /opt/slurm/bin/sinfo -V)"
