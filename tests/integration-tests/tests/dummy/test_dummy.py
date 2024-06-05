# Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import logging

import pytest


@pytest.mark.usefixtures("os", "scheduler", "instance")
def test_dummy(
    region,
    scheduler,
    pcluster_config_reader,
    vpc_stack,
    s3_bucket_factory,
    test_datadir,
    clusters_factory,
):
    """Do nothing"""
    logging.info("Do nothing but test hooks")
