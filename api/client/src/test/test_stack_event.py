"""
    ParallelCluster

    ParallelCluster API  # noqa: E501

    The version of the OpenAPI document: 3.0.0
    Generated by: https://openapi-generator.tech
"""


import sys
import unittest

import pcluster_client
from pcluster_client.model.cloud_formation_resource_status import CloudFormationResourceStatus
globals()['CloudFormationResourceStatus'] = CloudFormationResourceStatus
from pcluster_client.model.stack_event import StackEvent


class TestStackEvent(unittest.TestCase):
    """StackEvent unit test stubs"""

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testStackEvent(self):
        """Test StackEvent"""
        # FIXME: construct object with mandatory attributes with example values
        # model = StackEvent()  # noqa: E501
        pass


if __name__ == '__main__':
    unittest.main()
