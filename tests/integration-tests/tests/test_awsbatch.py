import logging

import pytest

from remote_command_executor import RemoteCommandExecutor


@pytest.mark.awsbatch
@pytest.mark.regions(["us-east-1", "eu-west-1", "cn-north-1", "us-gov-west-1"])
@pytest.mark.instances(["c5.xlarge", "t2.large"])
@pytest.mark.dimensions("*", "*", "alinux", "awsbatch")
def test_job_submission(region, os, instance, scheduler, pcluster_config_reader, clusters_factory, test_datadir):
    cluster_config = pcluster_config_reader(vpc_id="aaa", master_subnet_id="bbb", compute_subnet_id="ccc")
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    result = remote_command_executor.run_remote_command("env")
    logging.info(result.stdout)
    result = remote_command_executor.run_remote_command(["echo", "test"])
    logging.info(result.stdout)
    result = remote_command_executor.run_remote_script(
        str(test_datadir / "test_script.sh"), args=["1", "2"], additional_files=[str(test_datadir / "data_file")]
    )
    logging.info(result.stdout)
