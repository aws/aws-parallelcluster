#!/bin/bash
pcluster -h > tests/pcluster/cli/test_entrypoint/TestParallelClusterCli/test_helper/pcluster-help.txt
pcluster  2> tests/pcluster/cli/test_entrypoint/TestParallelClusterCli/test_no_command/pcluster-command-error.txt
