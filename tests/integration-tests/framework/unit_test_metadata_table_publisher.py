#  Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import logging

import jsonpickle
from framework_constants import METADATA_TABLE
from metadata_table_manager import MetadataTableManager, PhaseMetadata, TestMetadata

logger = logging.getLogger()
logger.setLevel(logging.INFO)

pub = MetadataTableManager("us-west-2", METADATA_TABLE)
sample_setup = PhaseMetadata("setup")
sample_call = PhaseMetadata("call")
sample_teardown = PhaseMetadata("teardown")
print(sample_setup)
print(sample_call)
print(sample_teardown)
sample_test = TestMetadata("test_name")
print(f"sample {sample_test}")
pub.publish_metadata([sample_test])
pub.get_metadata([sample_test.id])
frozen = jsonpickle.encode(sample_test)
print(f"frozen {frozen}")
thawed = jsonpickle.decode(frozen)
print(f"thawed {thawed}")
assert sample_test == thawed
# pub.publish_phase_metadata(PhaseMetadata("test_phase", "test_phase_description"))
