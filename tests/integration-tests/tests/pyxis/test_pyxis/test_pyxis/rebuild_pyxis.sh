#!/bin/bash
# Appendix B.2 of https://github.com/aws/aws-parallelcluster/wiki/Upgrade-Slurm-in-an-AWS-ParallelCluster-cluster:
# rebuild the Pyxis SPANK plugin against the Slurm installed in /opt/slurm, from the Pyxis sources the AMI keeps.
#
# The plugin lives on each node's root volume, so this runs on the head node right after Step 4, and on every compute
# node at boot as its OnNodeConfigured script. The commands are the ones the page lists, in the page's order.
set -euo pipefail

echo "Executing $0"
ls /opt/parallelcluster/sources/pyxis-*.tar.gz
mkdir -p ~/pyxis-rebuild
tar -xf "$(ls /opt/parallelcluster/sources/pyxis-*.tar.gz | sort -V | tail -n 1)" -C ~/pyxis-rebuild --strip-components=1
CPPFLAGS="-I/opt/slurm/include" make -C ~/pyxis-rebuild
sudo install -m 755 ~/pyxis-rebuild/spank_pyxis.so /usr/local/lib/slurm/spank_pyxis.so
echo "Rebuilt /usr/local/lib/slurm/spank_pyxis.so against $(/opt/slurm/sbin/slurmd -V 2>/dev/null || /opt/slurm/bin/sinfo -V)"
