"""This module provides unit tests for (portions of) the `pcluster createami` code."""

import pytest

import pcluster.commands as commands
from assertpy import assert_that
from recordclass import recordclass

MockedCreateAmiArgs = recordclass(
    "MockedCreateAmiArgs", ["base_ami_id", "instance_type", "base_ami_os"], rename=False, defaults=None, module=None
)


@pytest.mark.parametrize(
    "ami_architecture, expected_default_instance_type, exception_expected",
    [("x86_64", "t2.xlarge", False), ("arm64", "m6g.xlarge", False), ("notARealArch", None, True)],
)
def test_get_default_createami_instance_type(ami_architecture, expected_default_instance_type, exception_expected):
    """Verify that the function to select default instance types for the createami command behaves as expected."""
    if exception_expected:
        with pytest.raises(SystemExit) as sysexit:
            commands._get_default_createami_instance_type(ami_architecture)
        assert_that(sysexit.value.code).is_not_equal_to(0)
    else:
        assert_that(commands._get_default_createami_instance_type(ami_architecture)).is_equal_to(
            expected_default_instance_type
        )


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
    mocker.patch("pcluster.commands.utils.get_info_for_amis").return_value = [{"Architecture": base_ami_architecture}]
    mocker.patch("pcluster.commands._get_default_createami_instance_type")
    mocker.patch(
        "pcluster.commands.utils.get_supported_architectures_for_instance_type"
    ).return_value = supported_instance_archs
    mocker.patch("pcluster.commands.utils.get_supported_os_for_architecture").return_value = supported_os

    args = MockedCreateAmiArgs(base_ami_id, instance_type, base_ami_os)
    error_expected = any(
        [
            instance_type is not None and base_ami_architecture not in supported_instance_archs,
            base_ami_os not in supported_os,
        ]
    )
    if error_expected:
        with pytest.raises(SystemExit) as sysexit:
            commands._validate_createami_args_architecture_compatibility(args)
        assert_that(sysexit.value.code).is_not_equal_to(0)
    else:
        assert_that(commands._validate_createami_args_architecture_compatibility(args)).is_equal_to(
            base_ami_architecture
        )

    commands.utils.get_info_for_amis.assert_called_with([base_ami_id])

    if instance_type is None:
        commands._get_default_createami_instance_type.assert_called_with(base_ami_architecture)
    else:
        commands.utils.get_supported_architectures_for_instance_type.assert_called_with(instance_type)

    if instance_type is None or base_ami_architecture in supported_instance_archs:
        commands.utils.get_supported_os_for_architecture.assert_called_with(base_ami_architecture)
