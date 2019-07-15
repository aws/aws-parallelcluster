# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import json

import boto3


def get_instance_vcpus(region, instance):
    bucket_name = "{0}-aws-parallelcluster".format(region)
    s3 = boto3.resource("s3", region_name=region)
    instances_file_content = s3.Object(bucket_name, "instances/instances.json").get()["Body"].read()
    instances = json.loads(instances_file_content)
    return int(instances[instance]["vcpus"])
