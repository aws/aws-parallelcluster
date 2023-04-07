"""
This module loads pytest fixtures and plugins needed by all tests.

It's very useful for fixtures that need to be shared among all tests.
"""
import logging
import os
import sys
import time
from datetime import datetime

import boto3
import pytest
from assertpy import assert_that, soft_assertions
from botocore.stub import Stubber
from dateutil import tz
from flask.testing import FlaskClient
from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

from pcluster.api.flask_app import ParallelClusterFlaskApp
from pcluster.aws.common import StackNotFoundError
from pcluster.cli.entrypoint import main
from pcluster.constants import CW_LOGS_CFN_PARAM_NAME


@pytest.fixture(autouse=True)
def clear_env(mocker):
    if "AWS_DEFAULT_REGION" in os.environ:
        del os.environ["AWS_DEFAULT_REGION"]
    mocker.patch("botocore.session.Session.get_scoped_config", return_value={})


@pytest.fixture(autouse=True)
def reset_aws_api():
    """Reset AWSApi singleton to remove dependencies between tests."""
    from pcluster.aws.aws_api import AWSApi

    AWSApi._instance = None


@pytest.fixture
def failed_with_message(capsys):
    """Assert that the command exited with a specific error message."""
    __tracebackhide__ = True

    def _failed_with_message(func, message, *args, **kwargs):
        __tracebackhide__ = True
        with pytest.raises(SystemExit) as error:
            func(*args, **kwargs)
        assert error.type == SystemExit
        assert error.value.code == 1
        if message:
            assert capsys.readouterr().err == message

    return _failed_with_message


@pytest.fixture()
def test_datadir(request, datadir):
    """
    Inject the datadir with resources for the specific test function.

    If the test function is declared in a class then datadir is ClassName/FunctionName
    otherwise it is only FunctionName.
    """
    function_name = request.function.__name__
    if not request.cls:
        return datadir / function_name

    class_name = request.cls.__name__
    return datadir / "{0}/{1}".format(class_name, function_name)


@pytest.fixture()
def boto3_stubber(mocker, boto3_stubber_path):
    """
    Create a function to easily mock boto3 clients.

    To mock a boto3 service simply pass the name of the service to mock and
    the mocked requests, where mocked_requests is an object containing the method to mock,
    the response to return and the expected params for the boto3 method that gets called.

    The function makes use of botocore.Stubber to mock the boto3 API calls.
    Multiple boto3 services can be mocked as part of the same test.

    :param boto3_stubber_path is the path of the boto3 import to mock. (e.g. pcluster.config.validators.boto3)
    """
    __tracebackhide__ = True
    created_stubbers = []
    mocked_clients = {}

    mocked_client_factory = mocker.patch(boto3_stubber_path, autospec=True)
    # use **kwargs to skip parameters passed to the boto3.client other than the "service"
    # e.g. boto3.client("ec2", region_name=region, ...) --> x = ec2
    mocked_client_factory.client.side_effect = lambda x, **kwargs: mocked_clients[x]

    def _boto3_stubber(service, mocked_requests):
        if "AWS_DEFAULT_REGION" not in os.environ:
            # We need to provide a region to boto3 to avoid no region exception.
            # Which region to provide is arbitrary.
            os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
        client = boto3.client(service)
        stubber = Stubber(client)
        # Save a ref to the stubber so that we can deactivate it at the end of the test.
        created_stubbers.append(stubber)

        # Attach mocked requests to the Stubber and activate it.
        if not isinstance(mocked_requests, list):
            mocked_requests = [mocked_requests]
        for mocked_request in mocked_requests:
            if mocked_request.generate_error:
                stubber.add_client_error(
                    mocked_request.method,
                    service_message=mocked_request.response,
                    expected_params=mocked_request.expected_params,
                    service_error_code=mocked_request.error_code,
                )
            else:
                stubber.add_response(
                    mocked_request.method, mocked_request.response, expected_params=mocked_request.expected_params
                )
        stubber.activate()

        # Add stubber to the collection of mocked clients. This allows to mock multiple clients.
        # Mocking twice the same client will replace the previous one.
        mocked_clients[service] = client
        return client

    # yield allows to return the value and then continue the execution when the test is over.
    # Used for resources cleanup.
    yield _boto3_stubber

    # Assert that all mocked requests were consumed and deactivate all stubbers.
    for stubber in created_stubbers:
        stubber.assert_no_pending_responses()
        stubber.deactivate()


@pytest.fixture()
def pcluster_config_reader(test_datadir):
    """
    Define a fixture to render pcluster config templates associated to the running test.

    The config for a given test is a pcluster.config.ini file stored in the configs_datadir folder.
    The config can be written by using Jinja2 template engine.
    The current renderer already replaces placeholders for current keys:
        {{ os }}, {{ instance }}, {{ scheduler}}, {{ key_name }},
        {{ vpc_id }}, {{ public_subnet_id }}, {{ private_subnet_id }}
    The current renderer injects options for custom templates and packages in case these
    are passed to the cli and not present already in the cluster config.
    Also sanity_check is set to true by default unless explicitly set in config.
    :return: a _config_renderer(**kwargs) function which gets as input a dictionary of values to replace in the template
    """

    def _config_renderer(
        config_file="pcluster.config.yaml",
        output_file=None,
        **kwargs,
    ):
        config_file_path = os.path.join(str(test_datadir), config_file)
        output_file_path = os.path.join(str(test_datadir), output_file) if output_file else config_file_path
        file_loader = FileSystemLoader(str(test_datadir))
        env = SandboxedEnvironment(loader=file_loader)
        rendered_template = env.get_template(config_file).render(**kwargs)
        with open(output_file_path, "w", encoding="utf-8") as f:
            f.write(rendered_template)
        return output_file_path

    return _config_renderer


@pytest.fixture
def aws_api_mock(mocker):
    mocked_aws_api = mocker.MagicMock(autospec=True)
    mocker.patch("pcluster.aws.aws_api.AWSApi.instance", return_value=mocked_aws_api)
    return mocked_aws_api


@pytest.fixture
def client() -> FlaskClient:
    flask_app = ParallelClusterFlaskApp(swagger_ui=False, validate_responses=True).flask_app
    with flask_app.test_client() as client:
        yield client


@pytest.fixture
def set_env():
    old_environ = dict(os.environ)

    def _set_env_var(key, value):
        os.environ[key] = value

    yield _set_env_var
    os.environ.clear()
    os.environ.update(old_environ)


@pytest.fixture
def unset_env():
    old_environ = dict(os.environ)

    def _unset_env_var(key):
        os.environ.pop(key, default=None)

    yield _unset_env_var
    os.environ.clear()
    os.environ.update(old_environ)


@pytest.fixture
def set_tz(set_env):
    def _set_tz(value):
        set_env("TZ", value)
        time.tzset()

    yield _set_tz
    os.environ.pop("TZ", default=None)
    time.tzset()


@pytest.fixture()
def run_cli(mocker, capsys):
    def _run_cli(command, expect_failure=False, expect_message=None):
        mocker.patch.object(sys, "argv", command)
        with pytest.raises(SystemExit) as sysexit:
            main()
        if expect_failure:
            if expect_message:
                assert_that(sysexit.value.code).contains(expect_message)
            else:
                assert_that(sysexit.value.code).is_greater_than(0)
        else:
            assert_that(sysexit.value.code).is_equal_to(0)

    return _run_cli


@pytest.fixture()
def assert_out_err(capsys):
    def _assert_out_err(expected_out, expected_err):
        out_err = capsys.readouterr()
        # In Python 3.10 ArgParse renamed the 'optional arguments' section in the helper to 'option'
        expected_out_alternative = expected_out.replace("options", "optional arguments")
        with soft_assertions():
            assert_that(out_err.out.strip()).is_in(expected_out, expected_out_alternative)
            assert_that(out_err.err.strip()).contains(expected_err)

    return _assert_out_err


@pytest.fixture(autouse=True)
def enable_logging_propagation():
    # pytest caplog fixture captures logs propagated to the root logger.
    # Since we disabled propagation by default we have to enable it in order to enable
    # unit tests to verify logging output.
    logging.getLogger("pcluster").propagate = True


@pytest.fixture()
def cfn_describe_stack_mock_response():
    def _cfn_describe_stack_mock_response(edits=None):
        stack_data = {
            "StackId": "arn:aws:cloudformation:us-east-1:123:stack/cluster/123",
            "StackName": "cluster",
            "CreationTime": datetime(2021, 4, 30),
            "StackStatus": "CREATE_COMPLETE",
            "Outputs": [],
            "Parameters": [{"ParameterKey": CW_LOGS_CFN_PARAM_NAME, "ParameterValue": "log_group"}],
            "Tags": [
                {"Key": "parallelcluster:version", "Value": "3.0.0"},
                {"Key": "parallelcluster:s3_bucket", "Value": "bucket_name"},
                {
                    "Key": "parallelcluster:cluster_dir",
                    "Value": "parallelcluster/3.0.0/clusters/cluster-smkloc964uzpm12m",
                },
            ],
        }
        if edits:
            stack_data.update(edits)
        return stack_data

    return _cfn_describe_stack_mock_response


@pytest.fixture()
def mock_cluster_stack(mocker, cfn_describe_stack_mock_response):
    def _mock_cluster_stack(cluster_found=True, cluster_valid=True, logging_enabled=True):
        if not cluster_found:
            mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", side_effect=StackNotFoundError("func", "stack"))
        else:
            edits = {}
            if not cluster_valid:
                edits.update({"Tags": [{"Key": "parallelcluster:version", "Value": "2.0.0"}]})
            if not logging_enabled:
                edits.update({"Parameters": []})
            mocker.patch(
                "pcluster.aws.cfn.CfnClient.describe_stack", return_value=cfn_describe_stack_mock_response(edits=edits)
            )

    return _mock_cluster_stack


@pytest.fixture()
def mock_image_stack(mocker):
    def _mock_image_stack(image_id: str = "image", stack_exists: bool = True):
        uid = "00000000-ffff-1111-9999-000000000000"
        stack_data = {
            "Capabilities": ["CAPABILITY_NAMED_IAM"],
            "CreationTime": datetime(2021, 1, 1, 0, 0, 0, 0, tzinfo=tz.tzutc()),
            "NotificationARNs": [],
            "Parameters": [],
            "RollbackConfiguration": {},
            "StackId": f"arn:aws:cloudformation:us-east-1:000000000000:stack/{image_id}/{uid}",
            "StackName": image_id,
            "StackStatus": "CREATE_COMPLETE",
            "Tags": [
                {"Key": "parallelcluster:version", "Value": "3.0.0"},
                {"Key": "parallelcluster:image_name", "Value": image_id},
                {"Key": "parallelcluster:image_id", "Value": image_id},
                {"Key": "parallelcluster:s3_bucket", "Value": "parallelcluster-0000000000000000-v1-do-not-delete"},
                {
                    "Key": "parallelcluster:s3_image_dir",
                    "Value": f"parallelcluster/3.0.0/images/{image_id}-aaaaaaaaaaaaaaaa",
                },
                {
                    "Key": "parallelcluster:build_log",
                    "Value": (
                        "arn:aws:logs:us-east-1:000000000000:log-group:"
                        "/aws/imagebuilder/ParallelClusterImage-{image_id}"
                    ),
                },
                {
                    "Key": "parallelcluster:build_config",
                    "Value": (
                        "s3://parallelcluster-0cd54f8004a2e0af-v1-do-not-delete/parallelcluster/"
                        "3.0.0/images/custom-image-0-pgdlow92odu5dbvv/configs/image-config.yaml"
                    ),
                },
            ],
        }
        if not stack_exists:
            mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", side_effect=StackNotFoundError("func", "stack"))
        else:
            mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack", return_value=stack_data)

    return _mock_image_stack


@pytest.fixture
def mock_cloud_assembly(mocker):
    def _mock_cloud_assembly(assets, directory="test_dir", template_content="test_template_content"):
        cloud_assembly = mocker.patch("aws_cdk.cx_api.CloudAssembly")
        cloud_assembly.directory = directory
        cluster_cloud_artifact = mocker.patch("aws_cdk.cx_api.CloudFormationStackArtifact")
        mocker.patch(
            "pcluster.templates.cdk_artifacts_manager.CDKV1ClusterCloudAssembly._get_artifacts_class",
            return_value=type(cluster_cloud_artifact),
        )
        cluster_cloud_artifact.template = template_content
        cluster_cloud_artifact.assets = assets
        cloud_assembly.artifacts = [cluster_cloud_artifact]

        return cloud_assembly

    return _mock_cloud_assembly
