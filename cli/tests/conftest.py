"""
This module loads pytest fixtures and plugins needed by all tests.

It's very useful for fixtures that need to be shared among all tests.
"""
from __future__ import print_function

import os

import boto3
import pytest
from botocore.stub import Stubber
from jinja2 import Environment, FileSystemLoader


@pytest.fixture(autouse=True)
def clear_env():
    if "AWS_DEFAULT_REGION" in os.environ:
        del os.environ["AWS_DEFAULT_REGION"]


@pytest.fixture(autouse=True)
def mock_default_instance(mocker, request):
    """
    Mock get_default_instance_type for all tests.

    To disable the mock for certain tests, add annotation `@pytest.mark.nomockdefaultinstance` to the tests.
    To disable the mock for an entire file, declare global var `pytestmark = pytest.mark.noassertnopendingresponses`
    """
    if "nomockdefaultinstance" in request.keywords:
        # skip mocking
        return
    mocker.patch("pcluster.config.cfn_param_types.get_default_instance_type", return_value="t2.micro")


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
def convert_to_date_mock(request, mocker):
    """Mock convert_to_date function by enforcing the timezone to UTC."""
    module_under_test = request.node.fspath.purebasename.replace("test_", "")

    def _convert_to_date_utc(*args, **kwargs):
        from dateutil import tz

        from awsbatch.utils import convert_to_date

        # executes convert_to_date but overrides arguments so that timezone is enforced to utc
        if "timezone" in kwargs:
            del kwargs["timezone"]
        return convert_to_date(timezone=tz.tzutc(), *args, **kwargs)

    return mocker.patch("awsbatch." + module_under_test + ".convert_to_date", wraps=_convert_to_date_utc)


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


DEFAULT_AWSBATCHCLICONFIG_MOCK_CONFIG = {
    "region": "region",
    "proxy": None,
    "aws_access_key_id": "aws_access_key_id",
    "aws_secret_access_key": "aws_secret_access_key",
    "job_queue": "job_queue",
}


@pytest.fixture()
def awsbatchcliconfig_mock(request, mocker):
    """Mock AWSBatchCliConfig object with a default mock."""
    module_under_test = request.node.fspath.purebasename.replace("test_", "")
    mock = mocker.patch("awsbatch." + module_under_test + ".AWSBatchCliConfig", autospec=True)
    for key, value in DEFAULT_AWSBATCHCLICONFIG_MOCK_CONFIG.items():
        setattr(mock.return_value, key, value)
    return mock


@pytest.fixture()
def pcluster_config_reader(test_datadir):
    """
    Define a fixture to render pcluster config templates associated to the running test.

    The config for a given test is a pcluster.config.ini file stored in the configs_datadir folder.
    The config can be written by using Jinja2 template engine.
    The current renderer already replaces placeholders for current keys:
        {{ region }}, {{ os }}, {{ instance }}, {{ scheduler}}, {{ key_name }},
        {{ vpc_id }}, {{ public_subnet_id }}, {{ private_subnet_id }}
    The current renderer injects options for custom templates and packages in case these
    are passed to the cli and not present already in the cluster config.
    Also sanity_check is set to true by default unless explicitly set in config.
    :return: a _config_renderer(**kwargs) function which gets as input a dictionary of values to replace in the template
    """

    def _config_renderer(config_file="pcluster.config.ini", **kwargs):
        config_file_path = os.path.join(str(test_datadir), config_file)
        # default_values = _get_default_template_values(vpc_stacks, region, request)
        file_loader = FileSystemLoader(str(test_datadir))
        env = Environment(loader=file_loader)
        rendered_template = env.get_template(config_file).render(**kwargs)
        with open(config_file_path, "w") as f:
            f.write(rendered_template)
        return config_file_path

    return _config_renderer
