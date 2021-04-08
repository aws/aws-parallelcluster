#!/bin/bash
. "/etc/parallelcluster/cfnconfig"

case "${node_type}" in
    HeadNode)
        exit 0
    ;;
    ComputeFleet)
        exit 1
    ;;
    *)
        ;;
esac
