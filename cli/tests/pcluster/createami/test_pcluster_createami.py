"""This module provides unit tests for (portions of) the `pcluster createami` code."""

import os

import pytest
from assertpy import assert_that
from recordclass import recordclass

import pcluster.createami as createami
from pcluster.constants import SUPPORTED_ARCHITECTURES

MockedCreateAmiArgs = recordclass(
    "MockedCreateAmiArgs", ["base_ami_id", "instance_type", "base_ami_os"], rename=False, defaults=None, module=None
)


@pytest.mark.parametrize(
    "ami_architecture, expected_default_instance_type, instance_info_err",
    [
        ("x86_64", "t2.xlarge", None),
        ("arm64", "m6g.xlarge", None),
        ("arm64", "m6g.xlarge", None),
        ("arm64", "m6g.xlarge", "instance types do not exist"),
        ("arm64", "m6g.xlarge", "failure unrelated to instance types"),
        ("notARealArch", None, None),
    ],
)
def test_get_default_createami_instance_type(
    mocker, ami_architecture, expected_default_instance_type, instance_info_err
):
    """Verify that the function to select default instance types for the createami command behaves as expected."""
    instance_type_info_patch = mocker.patch(
        "pcluster.createami.utils.InstanceTypeInfo.init_from_instance_type",
        side_effect=SystemExit(instance_info_err) if instance_info_err else None,
    )
    logger_error_patch = mocker.patch("pcluster.createami.LOGGER.error")
    mocked_region = "MockedRegion"
    mocker.patch.dict(os.environ, {"AWS_DEFAULT_REGION": "MockedRegion"})
    if ami_architecture not in SUPPORTED_ARCHITECTURES:
        error_message = "unsupported architecture: {0}".format(ami_architecture)
        with pytest.raises(SystemExit) as sysexit:
            createami._get_default_createami_instance_type(ami_architecture)
        assert_that(sysexit.value.code).is_not_equal_to(0)
        instance_type_info_patch.assert_not_called()
        assert_that(logger_error_patch.call_count).is_equal_to(1)
        assert_that(logger_error_patch.call_args[0][0]).matches(error_message)
    elif instance_info_err:
        instance_unavailable_in_region = "instance types do not exit" in instance_info_err
        if instance_unavailable_in_region:
            error_message = "architecture {0} is {1}.*not available in {2}".format(
                ami_architecture, expected_default_instance_type, mocked_region
            )
        else:
            error_message = instance_info_err

        with pytest.raises(SystemExit) as sysexit:
            createami._get_default_createami_instance_type(ami_architecture)
        assert_that(sysexit.value.code).is_not_equal_to(0)
        instance_type_info_patch.assert_called_with(expected_default_instance_type)

        if instance_unavailable_in_region:
            assert_that(logger_error_patch.call_count).is_equal_to(1)
            assert_that(logger_error_patch.call_args[0][0]).matches(error_message)
    else:
        assert_that(createami._get_default_createami_instance_type(ami_architecture)).is_equal_to(
            expected_default_instance_type
        )
        instance_type_info_patch.assert_called_with(expected_default_instance_type)


@pytest.mark.parametrize(
    "base_ami_id, instance_type, base_ami_os, base_ami_architecture, supported_instance_archs, supported_os",
    [
        # Everything is compatible
        ("ami-id-one", None, "alinux2", "x86_64", ["x86_64"], ["alinux2"]),
        ("ami-id-two", "t2.xlarge", "alinux2", "x86_64", ["x86_64"], ["alinux2"]),
        # instance type arch is not compatible with base AMI arch
        ("ami-id-three", "t2.xlarge", "alinux2", "arm64", ["x86_64"], ["alinux2"]),
        # instance type arch compatible with base AMI arch, but OS isn't
        ("ami-id-four", "m6g.xlarge", "alinux", "arm64", ["arm64"], ["alinux2"]),
    ],
)
def test_validate_createami_args_architecture_compatibility(
    mocker, base_ami_id, instance_type, base_ami_os, base_ami_architecture, supported_instance_archs, supported_os
):
    """Verify that parameter validation works as expected in the function that implements the createami command."""
    base_ami_name = "ami-x"
    mocker.patch("pcluster.createami.utils.get_info_for_amis").return_value = [
        {"Architecture": base_ami_architecture, "Name": base_ami_name}
    ]
    mocker.patch("pcluster.createami._get_default_createami_instance_type")
    mocker.patch("pcluster.createami.utils.validate_pcluster_version_based_on_ami_name")
    mocker.patch(
        "pcluster.createami.utils.get_supported_architectures_for_instance_type"
    ).return_value = supported_instance_archs
    mocker.patch("pcluster.createami.utils.get_supported_os_for_architecture").return_value = supported_os

    args = MockedCreateAmiArgs(base_ami_id, instance_type, base_ami_os)
    error_expected = any(
        [
            instance_type is not None and base_ami_architecture not in supported_instance_archs,
            base_ami_os not in supported_os,
        ]
    )
    if error_expected:
        with pytest.raises(SystemExit) as sysexit:
            createami._validate_createami_args_ami_compatibility(args)
        assert_that(sysexit.value.code).is_not_equal_to(0)
    else:
        assert_that(createami._validate_createami_args_ami_compatibility(args)).is_equal_to(
            {"Architecture": base_ami_architecture, "Name": base_ami_name}
        )
        createami.utils.validate_pcluster_version_based_on_ami_name.assert_called_with(base_ami_name)

    createami.utils.get_info_for_amis.assert_called_with([base_ami_id])

    if instance_type is None:
        createami._get_default_createami_instance_type.assert_called_with(base_ami_architecture)
    else:
        createami.utils.get_supported_architectures_for_instance_type.assert_called_with(instance_type)

    if instance_type is None or base_ami_architecture in supported_instance_archs:
        createami.utils.get_supported_os_for_architecture.assert_called_with(base_ami_architecture)


@pytest.mark.parametrize(
    "post_install_script_url, expected_url",
    [
        ("https://bucket.s3.us-east-1.amazonaws.com/script.sh", True),
        ("https://bucket.s3.us-east-1.amazonaws.com/cookbooks/script.sh", True),
        ("file://script.sh", True),
        # Invalid url
        ("script", False),
        # Script not specified
        (None, False),
    ],
)
def test_get_post_install_script_dir(mocker, post_install_script_url, expected_url):
    mocker.patch("pcluster.createami.os.mkdir")
    mocker.patch("pcluster.createami.urlretrieve")
    mocker.patch("pcluster.createami.copyfile")
    mocker.patch("pcluster.createami._get_current_timestamp").return_value = "now"

    if not post_install_script_url or expected_url:
        assert_that(createami._get_post_install_script_dir(post_install_script_url, "/tmp")).is_equal_to(
            os.path.join("/tmp", "script", "now-script.sh") if post_install_script_url else None
        )
    else:
        with pytest.raises(SystemExit) as sysexit:
            createami._get_post_install_script_dir(post_install_script_url, "/tmp")
        assert_that(sysexit.value.code).is_not_equal_to(0)
