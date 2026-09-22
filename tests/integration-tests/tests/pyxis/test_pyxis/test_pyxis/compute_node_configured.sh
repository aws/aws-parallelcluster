#!/bin/bash
# OnNodeConfigured script of the compute nodes. Nothing to do while the cluster runs the Slurm of its AMI: the test
# replaces this object in S3 with rebuild_pyxis.sh once Slurm has been upgraded across a major release, so that every
# compute node launched afterwards rebuilds the Pyxis plugin at boot, as Appendix B of the upgrade wiki page describes.
set -e

echo "Executing $0: nothing to do"
