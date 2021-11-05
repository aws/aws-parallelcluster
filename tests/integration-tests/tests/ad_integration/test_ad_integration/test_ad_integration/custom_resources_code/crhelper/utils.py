# Imported from https://github.com/aws-cloudformation/custom-resource-helper
# The file has been modified to drop dependency on requests package
# flake8: noqa

import json
import logging
import time
from http.client import HTTPSConnection
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)


def _send_response(response_url, response_body):
    try:
        json_response_body = json.dumps(response_body)
    except Exception as e:
        msg = "Failed to convert response to json: {}".format(str(e))
        logger.error(msg, exc_info=True)
        response_body = {"Status": "FAILED", "Data": {}, "Reason": msg}
        json_response_body = json.dumps(response_body)
    logger.debug("CFN response URL: %s", response_url)
    logger.debug(json_response_body)
    headers = {"content-type": "", "content-length": str(len(json_response_body))}
    split_url = urlsplit(response_url)
    host = split_url.netloc
    url = urlunsplit(("", "", *split_url[2:]))
    while True:
        try:
            connection = HTTPSConnection(host)  # nosec nosemgrep
            connection.request(method="PUT", url=url, body=json_response_body, headers=headers)
            response = connection.getresponse()
            logger.info("CloudFormation returned status code: %s", response.reason)
            break
        except Exception as e:
            logger.error("Unexpected failure sending response to CloudFormation %s", e, exc_info=True)
            time.sleep(5)
