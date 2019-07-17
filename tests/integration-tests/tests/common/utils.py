# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import json
import logging

import boto3
from retrying import retry


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def _fetch_instance_slots(region, instance_type):
    bucket_name = "{0}-aws-parallelcluster".format(region)
    try:
        s3 = boto3.resource("s3", region_name=region)
        instances_file_content = s3.Object(bucket_name, "instances/instances.json").get()["Body"].read()
        instances = json.loads(instances_file_content)
        return int(instances[instance_type]["vcpus"])
    except Exception as e:
        logging.critical(
            "Could not load instance mapping file from S3 bucket {0}. Failed with exception: {1}".format(bucket_name, e)
        )
        raise
