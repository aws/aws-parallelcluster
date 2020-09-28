import pytest


@pytest.mark.regions(["us-east-2"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.schedulers(["slurm", "awsbatch"])
@pytest.mark.oss(["alinux2"])
@pytest.mark.usefixtures("os", "instance", "scheduler", "region")
def test_multi_cidr(pcluster_config_reader, clusters_factory):
    """
    Test cluster creation when there is multiple CIDR in a VPC.

    Specifically test that cluster is created when compute subnet is in the second CIDR block of the VPC.
    """
    cluster_config = pcluster_config_reader()
    clusters_factory(cluster_config)
