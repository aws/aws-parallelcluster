# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import logging
import sys
import time

from api.pcluster_api import ClusterInfo, PclusterApi
from pcluster import utils

LOGGER = logging.getLogger(__name__)


def delete(args):
    """Delete cluster described by cluster_name."""
    LOGGER.info("Deleting: %s", args.cluster_name)
    LOGGER.debug("CLI args: %s", str(args))
    try:
        # delete cluster raises an exception if stack does not exist
        result = PclusterApi().delete_cluster(args.cluster_name, utils.get_region(), args.keep_logs)
        if isinstance(result, ClusterInfo):
            print(f"Cluster deletion started correctly. {result}")
        else:
            utils.error(f"Cluster deletion failed. {result.message}")

        sys.stdout.write("\rStatus: %s" % result.stack_status)
        sys.stdout.flush()
        LOGGER.debug("Status: %s", result.stack_status)
        if not args.nowait:
            while result.stack_status == "DELETE_IN_PROGRESS":
                time.sleep(5)
                result = PclusterApi().describe_cluster(cluster_name=args.cluster_name, region=utils.get_region())
                if isinstance(result, ClusterInfo):
                    events = utils.get_stack_events(result.stack_name, raise_on_error=True)[0]
                    resource_status = (
                        "Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))
                    ).ljust(80)
                    sys.stdout.write("\r%s" % resource_status)
                    sys.stdout.flush()
                else:
                    utils.error(f"Unable to retrieve the status of the cluster.\n{result.message}")

            sys.stdout.write("\rStatus: %s\n" % result.stack_status)
            sys.stdout.flush()
            LOGGER.debug("Status: %s", result.stack_status)
        else:
            sys.stdout.write("\n")
            sys.stdout.flush()
        if result.stack_status == "DELETE_FAILED":
            LOGGER.info("Cluster did not delete successfully. Run 'pcluster delete %s' again", args.cluster_name)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)
