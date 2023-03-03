import logging
import time
from threading import Thread

LOGGER = logging.getLogger(__name__)


def import_cdk():
    """Import cdk libraries."""
    LOGGER.info("Start importing")
    begin = time.time()
    from aws_cdk.core import App  # noqa: F401 pylint: disable=import-outside-toplevel

    from pcluster.templates.cluster_stack import ClusterCdkStack  # noqa: F401 pylint: disable=import-outside-toplevel

    LOGGER.info("Import complete in %i seconds", time.time() - begin)


def start():
    """
    Import cdk libraries in a separate thread.

    :return: thread importing cdk libraries
    """
    thread = Thread(target=import_cdk)
    thread.start()
    return thread
