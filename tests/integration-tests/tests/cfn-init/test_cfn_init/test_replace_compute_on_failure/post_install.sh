#!/bin/bash
. "/etc/parallelcluster/cfnconfig"

case "${cfn_node_type}" in
    HeadNode)
        exit 0
    ;;
    ComputeFleet)
        exit 1
    ;;
    *)
        ;;
esac
