#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import itertools
import json
from collections import deque
from hashlib import sha256
from unittest.mock import PropertyMock

import pytest
from assertpy import assert_that

from pcluster.api.controllers.image_operations_controller import build_image
from pcluster.api.models import BuildImageResponseContent
from pcluster.aws.common import AWSClientError
from pcluster.cli.entrypoint import run
from pcluster.cli.exceptions import APIOperationException
from pcluster.imagebuilder_utils import (
    PCLUSTER_BUILD_IMAGE_CLEANUP_ROLE_BOOTSTRAP_TAG_KEY,
    PCLUSTER_BUILD_IMAGE_CLEANUP_ROLE_REVISION,
    _expected_inline_policy,
    ensure_default_build_image_stack_cleanup_role,
    get_cleanup_role_name,
)


class TestBuildImageCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = ["pcluster", "build-image", "--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize(
        "args, error_message",
        [
            ({}, "error: the following arguments are required: -c/--image-configuration, -i/--image-id"),
            ({"--image-configuration": None}, "error: argument -c/--image-configuration: expected one argument"),
            ({"--image-id": None}, "error: argument -i/--image-id: expected one argument"),
            ({"-c": "file", "-i": "id", "--invalid": None}, "Invalid arguments ['--invalid']"),
            (
                {"-c": "file", "--image-id": "id", "--region": "eu-west-"},
                "Bad Request: invalid or unsupported region 'eu-west-'",
            ),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys, test_datadir):
        if args.get("-c"):
            args["-c"] = str(test_datadir / "file")
        args = self._build_args(args)
        command = ["pcluster", "build-image"] + args
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    @pytest.mark.parametrize("image_id_arg, region_arg", [("--image-id", "--region"), ("-i", "-r")])
    def test_execute(self, image_id_arg, region_arg, mocker, test_datadir):
        response_dict = {
            "image": {
                "imageId": "image-id",
                "imageBuildStatus": "BUILD_IN_PROGRESS",
                "cloudformationStackStatus": "CREATE_IN_PROGRESS",
                "cloudformationStackArn": "arn:aws:cloudformation:eu-west-1:000000000000:stack/image-id/aaa",
                "region": "eu-west-1",
                "version": "3.0.0",
            }
        }

        response = BuildImageResponseContent().from_dict(response_dict)
        describe_clusters_mock = mocker.patch(
            "pcluster.api.controllers.image_operations_controller.build_image", return_value=response, autospec=True
        )

        path = str(test_datadir / "config.yaml")
        out = run(["build-image", "--image-configuration", path, image_id_arg, "image-id", region_arg, "eu-west-1"])
        assert_that(out).is_equal_to(response_dict)
        assert_that(describe_clusters_mock.call_args).is_length(2)  # this is due to the decorator on list_clusters
        expected_args = {
            "suppress_validators": None,
            "validation_failure_level": None,
            "dryrun": None,
            "rollback_on_failure": None,
            "region": "eu-west-1",
            "build_image_request_content": {"imageId": "image-id", "imageConfiguration": ""},
        }
        describe_clusters_mock.assert_called_with(**expected_args)

    def test_error(self, mocker, test_datadir):
        api_response = {"message": "error"}, 400
        mocker.patch(
            "pcluster.api.controllers.image_operations_controller.build_image", return_value=api_response, autospec=True
        )

        path = str(test_datadir / "config.yaml")
        with pytest.raises(APIOperationException) as exc_info:
            command = ["build-image", "--region", "eu-west-1", "--image-configuration", path, "--image-id", "image-id"]
            run(command)
        assert_that(exc_info.value.data).is_equal_to(api_response[0])

    @staticmethod
    def run_build_image_command(test_datadir):
        run(
            [
                "build-image",
                "--region",
                "eu-west-1",
                "--image-configuration",
                str(test_datadir / "config.yaml"),
                "--image-id",
                "image-id",
            ]
        )

    def test_no_nodejs_error(self, mocker, test_datadir):
        """Test expected message is printed out if nodejs is not installed."""
        mocker.patch("pcluster.api.util.shutil.which", return_value=None)
        with pytest.raises(APIOperationException) as exc_info:
            self.run_build_image_command(test_datadir)
        assert_that(exc_info.value.data.get("message")).matches("Node.js is required")

    def test_nodejs_wrong_version_error(self, mocker, test_datadir):
        """Test expected message is printed out if nodejs is wrong version."""
        mocker.patch("pcluster.api.util.subprocess.check_output", return_value="0.0.0")
        with pytest.raises(APIOperationException) as exc_info:
            self.run_build_image_command(test_datadir)
        assert_that(exc_info.value.data.get("message")).matches("requires Node.js version >=")

    def test_get_cleanup_role_name(self):
        fake_account = "123456789012"
        role_name = get_cleanup_role_name(fake_account)
        name_hash = sha256(fake_account.encode()).hexdigest()[:12]
        assert_that(role_name).is_equal_to(
            f"PClusterBuildImageCleanupRole-{name_hash}-v{PCLUSTER_BUILD_IMAGE_CLEANUP_ROLE_REVISION}"
        )

    @pytest.mark.parametrize(
        "cleanup_role_in_cfg, vpc_cfg_present, expect_call, expect_vpc_flag",
        [
            (None, False, True, False),
            (None, True, True, True),
            ("arn:aws:iam::123456789012:role/AlreadyProvided", False, False, False),
            ("arn:aws:iam::123456789012:role/AlreadyProvided", True, False, False),
        ],
    )
    def test_enable_cleanup_role_call_and_vpc_flag(
        self,
        mocker,
        aws_api_mock,
        cleanup_role_in_cfg,
        vpc_cfg_present,
        expect_call,
        expect_vpc_flag,
    ):
        """Validate following things.

        1. when (and only when) no custom CleanupLambdaRole is given call ensure_default_build_image_stack_cleanup_role.
        2. attach_vpc_access_policy flag reflects presence of DeploymentSettings/LambdaFunctionsVpcConfig.
        """
        ensure_mock = mocker.patch(
            "pcluster.api.controllers.image_operations_controller.ensure_default_build_image_stack_cleanup_role",
            return_value="arn:aws:iam::123456789012:role/cleanup",
        )

        cfg_lines = [
            "Build:",
            "  InstanceType: fake-instance",
            "  ParentImage: ami-0123456789abcdef0",
        ]
        if cleanup_role_in_cfg:
            cfg_lines += [
                "  Iam:",
                f"    CleanupLambdaRole: {cleanup_role_in_cfg}",
            ]

        if vpc_cfg_present:
            cfg_lines += [
                "DeploymentSettings:",
                "  LambdaFunctionsVpcConfig:",
                "    SubnetIds: subnet-12345678",
                "    SecurityGroupIds: sg-xxxxxx",
            ]

        cfg = "\n".join(cfg_lines) + "\n"

        aws_api_mock.sts.get_account_id.return_value = "fake-account"

        mocker.patch("pcluster.models.imagebuilder.ImageBuilder.create", return_value=[], autospec=True)
        mocker.patch(
            "pcluster.models.imagebuilder.ImageBuilder.stack",
            new_callable=PropertyMock,
            return_value=mocker.MagicMock(
                pcluster_image_id="fake-image-id",
                status="CREATE_IN_PROGRESS",
                id="arn:stack/fake",
                version="fake-pcluster-version",
            ),
        )

        build_image(
            build_image_request_content={"imageConfiguration": cfg, "imageId": "fake-image-id"},
            region="us-east-1",
        )

        if expect_call:
            ensure_mock.assert_called_once()
            _, kwargs = ensure_mock.call_args
            assert kwargs["attach_vpc_access_policy"] is expect_vpc_flag
        else:
            ensure_mock.assert_not_called()

    @pytest.mark.parametrize(
        "vpc_cfg_present",
        [False, True],
    )
    def test_ensure_default_build_image_stack_cleanup_role_bootstrap_flow(self, aws_api_mock, vpc_cfg_present):
        """
        If the cleanup IAM role exist and have an old revision.

        The IAM API call execution order must be:
        1. If vpc_cfg_present, attach the AWS-managed LambdaVPCAccess policy
        2. Attach the AWS-managed Lambda basic policy.
        3. Update/write the inline policy.
        4. Only after the inline policy succeeds, set or bump the revision tag.
        """
        call_seq = deque()

        def record(name):
            return lambda *a, **k: call_seq.append(name)

        resp_outdated = {"Role": {"RoleName": "dummy", "Tags": []}}
        aws_api_mock.iam.get_role.return_value = resp_outdated
        aws_api_mock.iam.attach_role_policy.side_effect = record("attach")
        aws_api_mock.iam.put_role_policy.side_effect = record("put")
        aws_api_mock.iam.tag_role.side_effect = record("tag")

        ensure_default_build_image_stack_cleanup_role("fake-account", "aws", vpc_cfg_present)
        assert list(call_seq) == ["attach", "attach", "put", "tag"] if vpc_cfg_present else ["attach", "put", "tag"]

    def test_ensure_default_build_image_stack_cleanup_role_skip_when_already_bootstrapped(
        self,
        mocker,
        aws_api_mock,
    ):
        current_resp = {
            "Role": {
                "RoleName": "dummy",
                "Tags": [
                    {
                        "Key": PCLUSTER_BUILD_IMAGE_CLEANUP_ROLE_BOOTSTRAP_TAG_KEY,
                        "Value": "true",
                    }
                ],
            }
        }

        aws_api_mock.iam.get_role.return_value = current_resp

        ensure_default_build_image_stack_cleanup_role("fake-account-id", "fake-partition")
        aws_api_mock.iam.get_role.assert_called()
        aws_api_mock.iam.put_role_policy.assert_not_called()
        aws_api_mock.iam.tag_role.assert_not_called()

    def test_ensure_default_build_image_stack_cleanup_role_permission_denied(self, aws_api_mock):
        """put_role_policy AccessDenied → It should throw an error and the cleanup IAM role should not be tagged."""
        resp_outdated = {"Role": {"RoleName": "dummy", "Tags": []}}
        aws_api_mock.iam.get_role.return_value = resp_outdated

        aws_api_mock.iam.put_role_policy.side_effect = AWSClientError(
            function_name="put_role_policy",
            message="Access denied",
            error_code="AccessDenied",
        )

        with pytest.raises(AWSClientError) as exc:
            ensure_default_build_image_stack_cleanup_role("fake-account", "aws")
        assert_that(exc.value.error_code).is_equal_to("AccessDenied")
        # tag_role should not be called
        aws_api_mock.iam.tag_role.assert_not_called()

    @pytest.mark.parametrize(
        "account_id, partition",
        [
            ("123456789012", "aws"),
            ("000000000000", "aws-us-gov"),
        ],
    )
    def test_expected_inline_policy_dynamic_fields(self, account_id, partition):
        raw = _expected_inline_policy(account_id, partition)
        policy = json.loads(raw)
        assert policy["Version"] == "2012-10-17"
        assert len(policy["Statement"]) == 13
        for statement in policy["Statement"]:
            resources = statement["Resource"]
            resources = resources if isinstance(resources, list) else [resources]
            for res in resources:
                if res == "*":
                    continue
                assert f"arn:{partition}" in res
                if not res == f"arn:{partition}:ec2:*::image/*":
                    assert f":{account_id}:" in res

    def _build_args(self, args):
        args = [[k, v] if v is not None else [k] for k, v in args.items()]
        return list(itertools.chain(*args))
