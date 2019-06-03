import pytest

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
    module_under_test = request.module.__name__.replace("test_", "")
    mock = mocker.patch("awsbatch." + module_under_test + ".AWSBatchCliConfig", autospec=True)
    for key, value in DEFAULT_AWSBATCHCLICONFIG_MOCK_CONFIG.items():
        setattr(mock.return_value, key, value)
    return mock
