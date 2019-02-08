import pytest


@pytest.mark.awsbatch
@pytest.mark.regions(["us-east-1", "eu-west-1", "cn-north-1", "us-gov-west-1"])
@pytest.mark.instances(["c5.xlarge", "t2.large"])
@pytest.mark.dimensions("*", "*", "alinux", "awsbatch")
def test_job_submission(region, os, instance, scheduler, pcluster_config_reader, clusters_factory):
    cluster_config = pcluster_config_reader(vpc_id="aaa", master_subnet_id="bbb", compute_subnet_id="ccc")
    clusters_factory(cluster_config)
