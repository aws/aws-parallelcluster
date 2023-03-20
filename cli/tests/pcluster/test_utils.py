# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
# This module provides unit tests for the functions in the pcluster.utils module."""
import os
import time
from collections import namedtuple

import pytest
from assertpy import assert_that
from yaml.constructor import ConstructorError

import pcluster.aws.common
import pcluster.utils as utils
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.aws_resources import InstanceTypeInfo
from pcluster.aws.common import Cache
from pcluster.models.cluster import Cluster, ClusterStack
from pcluster.utils import batch_by_property_callback, yaml_load
from tests.pcluster.aws.dummy_aws_api import mock_aws_api

FAKE_NAME = "cluster-name"
FAKE_VERSION = "0.0.0"


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
        ("x86_64", ["alinux2", "centos7", "ubuntu1804", "ubuntu2004", "rhel8"]),
        ("arm64", ["alinux2", "centos7", "ubuntu1804", "ubuntu2004", "rhel8"]),
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
        ("slurm", ["alinux2", "centos7", "ubuntu1804", "ubuntu2004", "rhel8"]),
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
                "VCpuInfo": {
                    "DefaultVCpus": 4,
                    "DefaultCores": 2,
                    "DefaultThreadsPerCore": 2,
                    "ValidCores": [1, 2],
                    "ValidThreadsPerCore": [1, 2],
                },
                "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 1},
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
            }
        ),
    )
    c4_instance_info = AWSApi.instance().ec2.get_instance_type_info("c4.xlarge")
    assert_that(c4_instance_info.gpu_count()).is_equal_to(0)
    assert_that(caplog.text).is_empty()
    assert_that(c4_instance_info.max_network_interface_count()).is_equal_to(1)
    assert_that(c4_instance_info.cores_count()).is_equal_to(2)
    assert_that(c4_instance_info.default_threads_per_core()).is_equal_to(2)
    assert_that(c4_instance_info.vcpus_count()).is_equal_to(4)
    assert_that(c4_instance_info.supported_architecture()).is_equal_to(["x86_64"])
    assert_that(c4_instance_info.is_efa_supported()).is_equal_to(False)

    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_instance_type_info",
        return_value=InstanceTypeInfo(
            {
                "InstanceType": "g4dn.metal",
                "VCpuInfo": {"DefaultVCpus": 96, "DefaultCores": 48, "DefaultThreadsPerCore": 2},
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
                "VCpuInfo": {
                    "DefaultVCpus": 64,
                    "DefaultCores": 32,
                    "DefaultThreadsPerCore": 2,
                    "ValidCores": [2, 4, 8, 16, 32],
                    "ValidThreadsPerCore": [1, 2],
                },
                "GpuInfo": {"Gpus": [{"Name": "*", "Manufacturer": "AMD", "Count": 4}]},
                "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 1},
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
            }
        ),
    )
    g4ad_instance_info = AWSApi.instance().ec2.get_instance_type_info("g4ad.16xlarge")
    assert_that(g4ad_instance_info.gpu_count()).is_equal_to(0)
    assert_that(g4ad_instance_info.gpu_manufacturer()).is_equal_to("AMD")
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
    "time_isoformat, time_zone, expect_output",
    [
        ("2021-06-04T03:34:52-07:00", "America/Los_Angeles", 1622802892000),
        ("2021-06-04T11:34:52+02:00", "Europe/Rome", 1622799292000),
        ("2021-06-04T11:34:52", "Europe/Rome", 1622806492000),
        ("2021-06-04T11:34", "Europe/Rome", 1622806440000),
        ("2021-06-04T11", "Europe/London", 1622804400000),
        ("2021-06-04", "Europe/London", 1622764800000),
    ],
)
def test_datetime_to_epoch(set_tz, time_isoformat, time_zone, expect_output):
    set_tz(time_zone)
    time.tzset()
    datetime_ = utils.to_utc_datetime(time_isoformat)
    assert_that(utils.datetime_to_epoch(datetime_)).is_equal_to(expect_output)


@pytest.mark.parametrize(
    "region, partition",
    [
        ("cn-north-1", "aws-cn"),
        ("cn-northwest-1", "aws-cn"),
        ("us-gov-east-1", "aws-us-gov"),
        ("us-gov-west-1", "aws-us-gov"),
        ("us-iso-east-1", "aws-iso"),
        ("us-iso-west-1", "aws-iso"),
        ("us-isob-east-1", "aws-iso-b"),
        ("WHATEVER-ELSE", "aws"),
    ],
)
def test_get_partition(mocker, region, partition):
    mocker.patch("pcluster.utils.get_region", return_value=region)
    assert_that(pcluster.utils.get_partition()).is_equal_to(partition)


@pytest.mark.parametrize(
    "partition, domain_suffix",
    [
        ("aws-cn", "amazonaws.com.cn"),
        ("aws", "amazonaws.com"),
        ("aws-us-gov", "amazonaws.com"),
        ("aws-iso", "c2s.ic.gov"),
        ("aws-iso-b", "sc2s.sgov.gov"),
        ("WHATEVER-ELSE", "amazonaws.com"),
    ],
)
def test_get_url_domain_suffix(mocker, partition, domain_suffix):
    mocker.patch("pcluster.utils.get_partition", return_value=partition)
    assert_that(pcluster.utils.get_url_domain_suffix()).is_equal_to(domain_suffix)


@pytest.mark.parametrize(
    "partition, docs_base_url",
    [
        ("aws-cn", "docs.amazonaws.cn"),
        ("aws-iso", "docs.c2shome.ic.gov"),
        ("aws-iso-b", "docs.sc2shome.sgov.gov"),
        ("WHATEVER-ELSE", "docs.aws.amazon.com"),
    ],
)
def test_docs_base_url(mocker, partition, docs_base_url):
    mocker.patch("pcluster.utils.get_partition", return_value=partition)
    assert_that(pcluster.utils.get_docs_base_url()).is_equal_to(docs_base_url)


@pytest.mark.parametrize(
    "region, s3_bucket_domain",
    [
        ("cn-north-1", "cn-north-1-aws-parallelcluster.s3.cn-north-1.amazonaws.com.cn"),
        ("cn-northwest-1", "cn-northwest-1-aws-parallelcluster.s3.cn-northwest-1.amazonaws.com.cn"),
        ("us-iso-east-1", "us-iso-east-1-aws-parallelcluster.s3.us-iso-east-1.c2s.ic.gov"),
        ("us-iso-west-1", "us-iso-west-1-aws-parallelcluster.s3.us-iso-west-1.c2s.ic.gov"),
        ("us-isob-east-1", "us-isob-east-1-aws-parallelcluster.s3.us-isob-east-1.sc2s.sgov.gov"),
        ("WHATEVER-REGION", "WHATEVER-REGION-aws-parallelcluster.s3.WHATEVER-REGION.amazonaws.com"),
    ],
)
def test_get_templates_bucket_path(mocker, region, s3_bucket_domain):
    mocker.patch("pcluster.utils.get_region", return_value=region)
    mocker.patch("pcluster.utils.get_installed_version", return_value="INSTALLED_VERSION")
    expected_template_path = f"https://{s3_bucket_domain}/parallelcluster/INSTALLED_VERSION/templates/"
    assert_that(pcluster.utils.get_templates_bucket_path()).is_equal_to(expected_template_path)


@pytest.mark.parametrize(
    "url, expected_url",
    (
        [
            "https://bucket.s3.${Region}.${URLSuffix}/parallelcluster/script.sh",
            "https://bucket.s3.us-east-1.amazonaws.com/parallelcluster/script.sh",
        ],
        ["s3://bucket/parallelcluster/script.sh", "s3://bucket/parallelcluster/script.sh"],
        [
            "https://bucket.s3.us-east-1.amazonaws.com/parallelcluster/script.sh",
            "https://bucket.s3.us-east-1.amazonaws.com/parallelcluster/script.sh",
        ],
    ),
)
def test_replace_url_parameters(mocker, url, expected_url):
    mocker.patch("pcluster.utils.get_region", return_value="us-east-1")
    mocker.patch("pcluster.utils.get_url_domain_suffix", return_value="amazonaws.com")
    assert_that(pcluster.utils.replace_url_parameters(url)).is_equal_to(expected_url)


@pytest.mark.parametrize(
    "yaml_string, expected_yaml_dict, expected_error",
    (
        ["PropA:\n  PropB: ValueB", {"PropA": {"PropB": "ValueB"}}, None],
        ["PropA:\n  PropB: ValueB1\n  PropB: ValueB2", None, ConstructorError("Duplicate key found: PropB *")],
    ),
)
def test_yaml_load(yaml_string, expected_yaml_dict, expected_error):
    if expected_error is not None:
        with pytest.raises(Exception) as exc:
            yaml_load(yaml_string)
        assert_that(str(exc.value)).matches(str(expected_error))
    else:
        yaml_dict = yaml_load(yaml_string)
        assert_that(yaml_dict).is_equal_to(expected_yaml_dict)


@pytest.mark.parametrize("imds_support, http_tokens", [("v1.0", "optional"), ("v2.0", "required")])
def test_get_http_token_settings(imds_support, http_tokens):
    assert_that(utils.get_http_tokens_setting(imds_support)).is_equal_to(http_tokens)


@pytest.mark.parametrize(
    "original, response",
    [({"test1": None, "test2": 2}, {"test2": 2}), ({"test1": 1, "test2": 2}, {"test1": 1, "test2": 2})],
)
def test_remove_none_values(original, response):
    assert_that(utils.remove_none_values(original)).is_equal_to(response)


@pytest.mark.parametrize(
    "resource_prefix, expected_output",
    [
        ("/path-prefix/", ["/path-prefix/", None]),
        ("/path-prefix/name-prefix", ["/path-prefix/", "name-prefix"]),
        ("name-prefix", [None, "name-prefix"]),
        ("/longerpath/path-prefix/name-prefix", ["/longerpath/path-prefix/", "name-prefix"]),
        (None, [None, None]),
    ],
)
def test_split_resource_prefix(resource_prefix, expected_output):
    iam_path_prefix, iam_role_prefix = utils.split_resource_prefix(resource_prefix=resource_prefix)
    assert_that(iam_path_prefix).is_equal_to(expected_output[0])
    assert_that(iam_role_prefix).is_equal_to(expected_output[1])


Item = namedtuple("Item", "property")


@pytest.mark.parametrize(
    "items, expected_batches, batch_size, raises",
    [
        (
            [
                Item(property=["test-1", "test-2", "test-3"]),
                Item(property=["test-4", "test-5", "test-6"]),
                Item(property=["test-7", "test-8", "test-9"]),
                Item(property=["test-10", "test-11", "test-12"]),
                Item(property=["test-13", "test-14", "test-15"]),
            ],
            [
                [
                    Item(property=["test-1", "test-2", "test-3"]),
                    Item(property=["test-4", "test-5", "test-6"]),
                    Item(property=["test-7", "test-8", "test-9"]),
                ],
                [
                    Item(property=["test-10", "test-11", "test-12"]),
                    Item(property=["test-13", "test-14", "test-15"]),
                ],
            ],
            9,
            False,
        ),
        (
            [
                Item(property=["test-1", "test-2"]),
                Item(property=["test-3"]),
                Item(property=["test-4"]),
                Item(property=["test-5", "test-6"]),
                Item(property=["test-7", "test-8", "test-9"]),
            ],
            [
                [Item(property=["test-1", "test-2"]), Item(property=["test-3"])],
                [Item(property=["test-4"]), Item(property=["test-5", "test-6"])],
                [Item(property=["test-7", "test-8", "test-9"])],
            ],
            3,
            False,
        ),
        (
            [
                Item(property=["test-1", "test-2", "test-3", "test-4"]),
                Item(property=["test-5"]),
            ],
            None,
            3,
            True,
        ),
        (
            [
                Item(property=["test-1", "test-2"]),
            ],
            [[Item(property=["test-1", "test-2"])]],
            3,
            False,
        ),
    ],
    ids=[
        "last-batch-with-size-smaller-than-batch-size",
        "all-item-property-sizes-within-range-of-batch-size",
        "property-count-greater-than-batch-size",
        "total-property-counts-less-than-batch-size",
    ],
)
def test_batch_by_property_size(items, expected_batches, batch_size, raises):
    if raises:
        with pytest.raises(ValueError):
            for _ in batch_by_property_callback(items, lambda item: len(item.property), batch_size):
                pass
    else:
        batches = [batch for batch in batch_by_property_callback(items, lambda item: len(item.property), batch_size)]
        assert_that(batches).is_equal_to(expected_batches)
