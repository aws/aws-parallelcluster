from assertpy import assert_that

from pcluster.api.errors import BadRequestException
from pcluster.constants import Operation


def mock_assert_supported_operation(mocker, path: str):
    return mocker.patch(path, side_effect=BadRequestException("ERROR MESSAGE"))


def verify_unsupported_operation(mocked_assertion, operation: Operation, region: str, response):
    mocked_assertion.assert_called_once()
    mocked_assertion.assert_called_with(operation=operation, region=region)
    assert_that(response.status_code).is_equal_to(400)
    assert_that(response.get_json()["message"]).matches("ERROR MESSAGE")
