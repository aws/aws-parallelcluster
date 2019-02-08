import logging

import pytest


@pytest.mark.dimensions("us-east-1", "c5.xlarge", "alinux", "sge")
@pytest.mark.dimensions("us-west-1", "c4.xlarge", "centos6", "slurm")
def test_dimensions(region, instance, os, scheduler):
    assert region in ["us-east-1", "us-west-1"]
    assert instance in ["c5.xlarge", "c4.xlarge"]
    assert os in ["alinux", "centos6"]
    assert scheduler in ["sge", "slurm"]


@pytest.mark.skip_dimensions("us-east-1", "c5.xlarge", "alinux", "sge")
@pytest.mark.skip_dimensions("us-west-1", "c4.xlarge", "*", "*")
def test_skip_dimensions(region, instance, os, scheduler):
    assert (region, instance, os, scheduler) != ("us-east-1", "c5.xlarge", "alinux", "sge")
    assert (region, instance, os, scheduler) != ("us-west-1", "c4.xlarge", "centos6", "slurm")


@pytest.mark.instances(["c4.xlarge", "c5.xlarge"])
def test_instances(instance):
    assert instance in ["c4.xlarge", "c5.xlarge"]


@pytest.mark.skip_instances(["c4.xlarge"])
def test_skip_instances(instance):
    assert instance != "c4.xlarge"


@pytest.mark.regions(["us-east-1", "us-west-1"])
def test_regions(region):
    assert region in ["us-east-1", "us-west-1"]


@pytest.mark.skip_regions(["us-east-1"])
def test_skip_regions(region):
    assert region != "us-east-1"


@pytest.mark.oss(["alinux", "centos7"])
def test_oss(os):
    assert os in ["alinux", "centos7"]


@pytest.mark.skip_oss(["alinux"])
def test_skip_oss(os):
    assert os != "alinux"


@pytest.mark.schedulers(["sge", "slurm"])
def test_schedulers(scheduler):
    assert scheduler in ["sge", "slurm"]


@pytest.mark.skip_schedulers(["sge"])
def test_skip_schedulers(scheduler):
    assert scheduler != "sge"


@pytest.mark.factory
def test_factory(clusters_factory):
    clusters_factory("/Users/fdm/.parallelcluster/aws_batch.config")


@pytest.mark.instances(["c4.xlarge", "c5.xlarge"])
@pytest.mark.regions(["us-east-1"])
def test_markers(instance, region):
    logging.info(instance)
    logging.info(region)


@pytest.mark.feature1
def test_feature1():
    logging.warning("test_feature")


def test_failure():
    assert True is False


@pytest.fixture
def fix():
    raise Exception("oops")


def test_error(fix):
    assert fix == 2
