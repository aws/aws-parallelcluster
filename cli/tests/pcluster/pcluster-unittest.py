# Copyright 2013-2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# noqa: D101

import json
import logging
import os
import re
import stat
import unittest

import boto3
import configparser

from moto import mock_autoscaling, mock_cloudformation, mock_ec2, mock_s3
from pcluster import pcluster

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO


test_log_stream = StringIO()
config_file = "cli/tests/config"
with open("cloudformation/aws-parallelcluster.cfn.json") as f:
    cfncluster_json_data = json.load(f)
    version_on_file = cfncluster_json_data["Mappings"]["PackagesVersions"]["default"]["cfncluster"]
    version_on_file = re.match(r".*(\d+\.\d+\.\d+.*)", version_on_file).group(1)
    json_dump = json.dumps(cfncluster_json_data)


def config_logger_test():
    logging.basicConfig(stream=test_log_stream, level=logging.INFO)


def setup_configurations():
    s3 = boto3.client("s3")
    s3_conn = boto3.resource("s3")
    s3.create_bucket(Bucket="us-east-1-aws-parallelcluster")
    s3_conn.Object("us-east-1-aws-parallelcluster", "aws-parallelcluster").put(Body=json_dump)
    template_url = s3.generate_presigned_url(
        ClientMethod="get_object", Params={"Bucket": "us-east-1-aws-parallelcluster", "Key": "aws-parallelcluster"}
    )

    client = boto3.client("ec2", region_name="us-east-1")
    instance = client.run_instances(ImageId="ami-1234abcd", MinCount=1, MaxCount=1)["Instances"][0]

    vpc = client.create_vpc(CidrBlock="10.0.0.0/16", AmazonProvidedIpv6CidrBlock=True, DryRun=False)
    subnet = client.create_subnet(
        AvailabilityZone=instance["Placement"]["AvailabilityZone"],
        CidrBlock="10.0.0.0/16",
        Ipv6CidrBlock=vpc["Vpc"]["Ipv6CidrBlockAssociationSet"][0]["Ipv6CidrBlock"],
        VpcId=vpc["Vpc"]["VpcId"],
    )
    config = configparser.ConfigParser()
    config.read(config_file)
    config.set("vpc public", "vpc_id", subnet["Subnet"]["VpcId"])
    config.set("vpc public", "master_subnet_id", subnet["Subnet"]["SubnetId"])

    open(config_file, "a").close()
    os.chmod(config_file, stat.S_IRUSR | stat.S_IWUSR)
    with open(config_file, "w") as cf:
        config.write(cf)

    return template_url


class BaseArgs:
    def __init__(self):
        self.version = "0.0"
        self.func = lambda x: x
        self.config_file = "cli/tests/config"
        self.region = "us-east-1"


class CreateClusterArgs(BaseArgs):
    def __init__(self, template_url, nowait):
        BaseArgs.__init__(self)
        self.cluster_name = "test_cluster"
        self.template_url = template_url
        self.norollback = True
        self.nowait = nowait


class UpdateClusterArgs(CreateClusterArgs):
    def __init__(self, template_url, nowait, reset_desired):
        CreateClusterArgs.__init__(self, template_url=template_url, nowait=nowait)
        self.reset_desired = reset_desired


class TestPCluster(unittest.TestCase):
    def setUp(self):
        config_logger_test()

    def test_cfn_cluster_version(self):
        args = BaseArgs()
        pcluster.version(args)
        log = test_log_stream.getvalue()
        version_returned = re.match(r"^INFO:\w+\.\w+:(\d+\.\d+\.\d+.*)$", log).group(1)
        self.assertEqual(version_returned, version_on_file)

    @mock_ec2
    @mock_cloudformation
    @mock_s3
    def test_cfn_cluster_create_nowait(self):
        template_url = setup_configurations()
        args = CreateClusterArgs(template_url, True)
        pcluster.create(args)
        log = test_log_stream.getvalue()
        success_message = "INFO:parallelcluster.parallelcluster:Status: CREATE_COMPLETE"
        error_prefix = "CRITICAL:"
        self.assertTrue(success_message in log)
        self.assertFalse(error_prefix in log)

    @mock_ec2
    @mock_cloudformation
    @mock_s3
    def test_cfn_cluster_create_wait(self):
        template_url = setup_configurations()
        args = CreateClusterArgs(template_url, False)
        pcluster.create(args)
        log = test_log_stream.getvalue()
        success_message = "INFO:parallelcluster.parallelcluster:MasterPublicIP:"
        error_prefix = "CRITICAL:"
        self.assertTrue(success_message in log)
        self.assertFalse(error_prefix in log)

    @mock_ec2
    @mock_cloudformation
    @mock_s3
    def test_cfn_cluster_create_fail(self):
        setup_configurations()
        args = CreateClusterArgs("", True)
        with self.assertRaises(SystemExit) as sys_ex:
            pcluster.create(args)

        self.assertEqual(sys_ex.exception.code, 1)
        log = test_log_stream.getvalue()
        error_prefix = "CRITICAL:"
        self.assertTrue(error_prefix in log)

    @mock_ec2
    @mock_cloudformation
    @mock_s3
    def test_cfn_cluster_list_empty(self):
        args = BaseArgs()
        pcluster.list(args)
        self.assertEqual(test_log_stream.tell(), 0)

    @mock_ec2
    @mock_cloudformation
    @mock_s3
    def test_cfn_cluster_list_nonempty(self):
        template_url = setup_configurations()
        args = CreateClusterArgs(template_url, False)
        pcluster.create(args)
        # reset the logger
        self.tearDown()
        pcluster.list(args)
        log = test_log_stream.getvalue()
        cluster_name = re.match(r"INFO:parallelcluster.parallelcluster:(\w+)", log).group(1)
        self.assertEqual(cluster_name, args.cluster_name)

    @mock_ec2
    @mock_cloudformation
    @mock_autoscaling
    @mock_s3
    def test_cfn_cluster_update_no_reset(self):
        template_url = setup_configurations()
        args = UpdateClusterArgs(template_url, True, False)
        pcluster.create(args)
        pcluster.update(args)
        success_message = "INFO:parallelcluster.parallelcluster:Status: UPDATE_COMPLETE"
        log = test_log_stream.getvalue()
        self.assertTrue(success_message in log)
        error_prefix = "CRITICAL:"
        self.assertFalse(error_prefix in log)

    @mock_ec2
    @mock_cloudformation
    @mock_autoscaling
    @mock_s3
    def test_cfn_cluster_update_with_reset(self):
        template_url = setup_configurations()
        args = UpdateClusterArgs(template_url, True, True)
        pcluster.create(args)
        pcluster.update(args)
        success_message = "INFO:parallelcluster.parallelcluster:Status: UPDATE_COMPLETE"
        log = test_log_stream.getvalue()
        self.assertTrue(success_message in log)
        error_prefix = "CRITICAL:"
        self.assertFalse(error_prefix in log)

    @mock_ec2
    @mock_cloudformation
    @mock_autoscaling
    @mock_s3
    def test_cfn_cluster_update_fail(self):
        template_url = setup_configurations()
        args = UpdateClusterArgs(template_url, True, False)
        with self.assertRaises(SystemExit) as sys_ex:
            pcluster.update(args)
        self.assertEqual(sys_ex.exception.code, 1)
        log = test_log_stream.getvalue()
        error_prefix = "CRITICAL:"
        self.assertTrue(error_prefix in log)

    @mock_ec2
    @mock_cloudformation
    @mock_s3
    @mock_autoscaling
    def test_cfn_cluster_delete(self):
        template_url = setup_configurations()
        args = CreateClusterArgs(template_url, True)
        pcluster.create(args)
        with self.assertRaises(SystemExit) as sys_ex:
            pcluster.delete(args)
            self.assertEqual(sys_ex.exception.code, 0)
        success_message = "Cluster deleted successfully"
        log = test_log_stream.getvalue()
        self.assertTrue(success_message in log)

    @mock_ec2
    @mock_cloudformation
    @mock_s3
    @mock_autoscaling
    def test_cfn_cluster_delete_fail(self):
        template_url = setup_configurations()
        args = CreateClusterArgs(template_url, True)
        with self.assertRaises(SystemExit) as sys_ex:
            pcluster.delete(args)
            self.assertEqual(sys_ex.exception.code, 1)
        log = test_log_stream.getvalue()
        error_prefix = "CRITICAL:"
        self.assertTrue(error_prefix in log)

    @mock_ec2
    @mock_cloudformation
    @mock_s3
    @mock_autoscaling
    def test_cfn_cluster_start(self):
        template_url = setup_configurations()
        args = CreateClusterArgs(template_url, True)
        pcluster.create(args)
        pcluster.start(args)
        log = test_log_stream.getvalue()
        error_prefix = "CRITICAL:"
        success_message = "Starting compute fleet"
        self.assertFalse(error_prefix in log)
        self.assertTrue(success_message in log)

    @mock_ec2
    @mock_cloudformation
    @mock_s3
    @mock_autoscaling
    def test_cfn_cluster_start_fail(self):
        template_url = setup_configurations()
        args = CreateClusterArgs(template_url, True)
        with self.assertRaises(SystemExit) as sys_ex:
            pcluster.start(args)
        self.assertEqual(sys_ex.exception.code, 1)
        log = test_log_stream.getvalue()
        error_prefix = "CRITICAL:"
        self.assertTrue(error_prefix in log)

    @mock_ec2
    @mock_cloudformation
    @mock_autoscaling
    @mock_s3
    def test_cfn_cluster_stop(self):
        template_url = setup_configurations()
        args = CreateClusterArgs(template_url, True)
        pcluster.create(args)
        pcluster.start(args)
        pcluster.stop(args)
        log = test_log_stream.getvalue()
        error_prefix = "CRITICAL:"
        success_message = "Stopping compute fleet"
        self.assertFalse(error_prefix in log)
        self.assertTrue(success_message in log)

    @mock_ec2
    @mock_cloudformation
    @mock_autoscaling
    @mock_s3
    def test_cfn_cluster_stop_fail(self):
        template_url = setup_configurations()
        args = CreateClusterArgs(template_url, True)
        with self.assertRaises(SystemExit):
            pcluster.stop(args)
        log = test_log_stream.getvalue()
        error_prefix = "CRITICAL:"
        self.assertTrue(error_prefix in log)

    def tearDown(self):
        test_log_stream.truncate(0)
        test_log_stream.seek(0)


if __name__ == "__main__":
    unittest.main()
