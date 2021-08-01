"""This module provides unit tests for the functions in the pcluster.utils module."""
import os
import time

import pytest
from assertpy import assert_that

import pcluster.aws.common
import pcluster.utils as utils
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.aws_resources import InstanceTypeInfo
from pcluster.aws.common import Cache
from pcluster.models.cluster import Cluster, ClusterStack
from tests.pcluster.aws.dummy_aws_api import mock_aws_api

FAKE_NAME = "cluster-name"


@pytest.fixture()
def boto3_stubber_path():
    """Specify that boto3_mocker should stub calls to boto3 for the pcluster.utils module."""
    return "pcluster.utils.boto3"


def dummy_cluster_stack():
    """Return dummy cluster stack object."""
    return ClusterStack({"StackName": FAKE_NAME})


def dummy_cluster(name=FAKE_NAME, stack=None):
    """Return dummy cluster object."""
    if stack is None:
        stack = dummy_cluster_stack()
    return Cluster(name, stack=stack)


def _generate_stack_event():
    return {
        "LogicalResourceId": "id",
        "ResourceStatus": "status",
        "StackId": "id",
        "EventId": "id",
        "StackName": FAKE_NAME,
        "Timestamp": 0,
    }


@pytest.mark.parametrize(
    "bucket_prefix", ["test", "test-", "prefix-63-characters-long--------------------------------to-cut"]
)
def test_generate_random_name_with_prefix(bucket_prefix):
    bucket_name = utils.generate_random_name_with_prefix(bucket_prefix)
    max_bucket_name_length = 63
    random_suffix_length = 17  # 16 digits + 1 separator

    pruned_prefix = bucket_prefix[: max_bucket_name_length - len(bucket_prefix) - random_suffix_length]
    assert_that(bucket_name).starts_with(pruned_prefix)
    assert_that(len(bucket_name)).is_equal_to(len(pruned_prefix) + random_suffix_length)

    # Verify bucket name limits: bucket name must be at least 3 and no more than 63 characters long
    assert_that(len(bucket_name)).is_between(3, max_bucket_name_length)


def test_generate_random_prefix():
    prefix = utils.generate_random_prefix()
    assert_that(len(prefix)).is_equal_to(16)


@pytest.mark.parametrize(
    "architecture, supported_oses",
    [
        ("x86_64", ["alinux2", "centos7", "ubuntu1804", "ubuntu2004"]),
        ("arm64", ["alinux2", "centos7", "ubuntu1804", "ubuntu2004"]),
    ],
)
def test_get_supported_os_for_architecture(architecture, supported_oses):
    """Verify that the expected OSes are supported based on a given architecture."""
    assert_that(utils.get_supported_os_for_architecture(architecture)).contains_only(
        *supported_oses
    ).does_not_contain_duplicates()


@pytest.mark.parametrize(
    "scheduler, supported_oses",
    [
        ("slurm", ["alinux2", "centos7", "ubuntu1804", "ubuntu2004"]),
        ("awsbatch", ["alinux2"]),
    ],
)
def test_get_supported_os_for_scheduler(scheduler, supported_oses):
    """Verify that the expected OSes are supported based on a given architecture."""
    assert_that(utils.get_supported_os_for_scheduler(scheduler)).contains_only(
        *supported_oses
    ).does_not_contain_duplicates()


class TestCache:
    invocations = []

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        pcluster.aws.common.Cache.clear_all()

    @pytest.fixture(autouse=True)
    def clear_invocations(self):
        del self.invocations[:]

    @pytest.fixture
    def disabled_cache(self):
        os.environ["PCLUSTER_CACHE_DISABLED"] = "true"
        yield
        del os.environ["PCLUSTER_CACHE_DISABLED"]

    @staticmethod
    @Cache.cached
    def _cached_method_1(arg1, arg2):
        TestCache.invocations.append((arg1, arg2))
        return arg1, arg2

    @staticmethod
    @Cache.cached
    def _cached_method_2(arg1, arg2):
        TestCache.invocations.append((arg1, arg2))
        return arg1, arg2

    def test_cached_method(self):
        for _ in range(0, 2):
            assert_that(self._cached_method_1(1, 2)).is_equal_to((1, 2))
            assert_that(self._cached_method_2(1, 2)).is_equal_to((1, 2))
            assert_that(self._cached_method_1(2, 1)).is_equal_to((2, 1))
            assert_that(self._cached_method_1(1, arg2=2)).is_equal_to((1, 2))
            assert_that(self._cached_method_1(arg1=1, arg2=2)).is_equal_to((1, 2))

        assert_that(self.invocations).is_length(5)

    def test_disabled_cache(self, disabled_cache):
        assert_that(self._cached_method_1(1, 2)).is_equal_to((1, 2))
        assert_that(self._cached_method_1(1, 2)).is_equal_to((1, 2))

        assert_that(self.invocations).is_length(2)

    def test_clear_all(self):
        for _ in range(0, 2):
            assert_that(self._cached_method_1(1, 2)).is_equal_to((1, 2))
            assert_that(self._cached_method_2(1, 2)).is_equal_to((1, 2))

        Cache.clear_all()

        for _ in range(0, 2):
            assert_that(self._cached_method_1(1, 2)).is_equal_to((1, 2))
            assert_that(self._cached_method_2(1, 2)).is_equal_to((1, 2))

        assert_that(self.invocations).is_length(4)


def test_init_from_instance_type(mocker, caplog):
    mock_aws_api(mocker, mock_instance_type_info=False)

    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_instance_type_info",
        return_value=InstanceTypeInfo(
            {
                "InstanceType": "c4.xlarge",
                "VCpuInfo": {"DefaultVCpus": 4, "DefaultCores": 2, "DefaultThreadsPerCore": 2},
                "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 1},
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
            }
        ),
    )
    c4_instance_info = AWSApi.instance().ec2.get_instance_type_info("c4.xlarge")
    assert_that(c4_instance_info.gpu_count()).is_equal_to(0)
    assert_that(caplog.text).is_empty()
    assert_that(c4_instance_info.max_network_interface_count()).is_equal_to(1)
    assert_that(c4_instance_info.default_threads_per_core()).is_equal_to(2)
    assert_that(c4_instance_info.vcpus_count()).is_equal_to(4)
    assert_that(c4_instance_info.supported_architecture()).is_equal_to(["x86_64"])
    assert_that(c4_instance_info.is_efa_supported()).is_equal_to(False)

    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_instance_type_info",
        return_value=InstanceTypeInfo(
            {
                "InstanceType": "g4dn.metal",
                "VCpuInfo": {"DefaultVCpus": 96},
                "GpuInfo": {"Gpus": [{"Name": "T4", "Manufacturer": "NVIDIA", "Count": 8}]},
                "NetworkInfo": {"EfaSupported": True, "MaximumNetworkCards": 4},
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
            }
        ),
    )
    g4dn_instance_info = AWSApi.instance().ec2.get_instance_type_info("g4dn.metal")
    assert_that(g4dn_instance_info.gpu_count()).is_equal_to(8)
    assert_that(caplog.text).is_empty()
    assert_that(g4dn_instance_info.max_network_interface_count()).is_equal_to(4)
    assert_that(g4dn_instance_info.default_threads_per_core()).is_equal_to(2)
    assert_that(g4dn_instance_info.vcpus_count()).is_equal_to(96)
    assert_that(g4dn_instance_info.supported_architecture()).is_equal_to(["x86_64"])
    assert_that(g4dn_instance_info.is_efa_supported()).is_equal_to(True)

    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_instance_type_info",
        return_value=InstanceTypeInfo(
            {
                "InstanceType": "g4ad.16xlarge",
                "VCpuInfo": {"DefaultVCpus": 64},
                "GpuInfo": {"Gpus": [{"Name": "*", "Manufacturer": "AMD", "Count": 4}]},
                "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 1},
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
            }
        ),
    )
    g4ad_instance_info = AWSApi.instance().ec2.get_instance_type_info("g4ad.16xlarge")
    assert_that(g4ad_instance_info.gpu_count()).is_equal_to(0)
    assert_that(caplog.text).matches("not offer native support for 'AMD' GPUs.")
    assert_that(g4ad_instance_info.max_network_interface_count()).is_equal_to(1)
    assert_that(g4ad_instance_info.default_threads_per_core()).is_equal_to(2)
    assert_that(g4ad_instance_info.vcpus_count()).is_equal_to(64)
    assert_that(g4ad_instance_info.supported_architecture()).is_equal_to(["x86_64"])
    assert_that(g4ad_instance_info.is_efa_supported()).is_equal_to(False)


@pytest.mark.parametrize(
    "url, expect_output",
    [
        ("https://test.s3.cn-north-1.amazonaws.com.cn/post_install.sh", "https"),
        (
            "s3://test/post_install.sh",
            "s3",
        ),
    ],
)
def test_get_url_scheme(url, expect_output):
    assert_that(utils.get_url_scheme(url)).is_equal_to(expect_output)


@pytest.mark.parametrize(
    "timestamp, time_zone, expect_output",
    [
        (1622802892000, "Europe/London", "2021-06-04T11:34:52+01:00"),
        (1622802892000, "America/Los_Angeles", "2021-06-04T03:34:52-07:00"),
        (1622757600000, "Europe/London", "2021-06-03T23:00:00+01:00"),
    ],
)
def test_timestamp_to_isoformat(set_tz, timestamp, time_zone, expect_output):
    set_tz(time_zone)
    time.tzset()
    assert_that(utils.timestamp_to_isoformat(timestamp)).is_equal_to(expect_output)


@pytest.mark.parametrize(
    "time_isoformat, time_zone, expect_output",
    [
        ("2021-06-04T03:34:52-07:00", "America/Los_Angeles", 1622802892000),
        ("2021-06-04T11:34:52+02:00", "Europe/Rome", 1622799292000),
        ("2021-06-04T11:34:52", "Europe/Rome", 1622799292000),
        ("2021-06-04T11:34", "Europe/Rome", 1622799240000),
        ("2021-06-04T11", "Europe/London", 1622800800000),
        ("2021-06-04", "Europe/London", 1622761200000),
    ],
)
def test_isoformat_to_epoch(set_tz, time_isoformat, time_zone, expect_output):
    set_tz(time_zone)
    time.tzset()
    assert_that(utils.isoformat_to_epoch(time_isoformat)).is_equal_to(expect_output)
