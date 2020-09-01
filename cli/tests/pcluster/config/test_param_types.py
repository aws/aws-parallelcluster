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
import pytest
from assertpy import assert_that

from pcluster.config.param_types import Param


class TestParam:
    @pytest.mark.parametrize(
        "section_label, should_trigger_error",
        [
            ("LongSectionNameJust1CharTooLong", True),
            ("Longest-Possible_Section-Name1", False),
            ("1BeginWithNumber", True),
            ("_BeginsWithUnderscore", True),
            ("Contains spaces", True),
        ],
    )
    def test_validate_section_label(self, section_label, should_trigger_error, mocker, caplog):
        error_msg = (
            "Failed validation for section queue {0}. Section names can be at most 30 chars long,"
            " must begin with a letter and only contain alphanumeric characters, hyphens and underscores."
        ).format(section_label)
        mocker.patch.object(Param, "__abstractmethods__", new_callable=set)
        param = Param("queue", section_label, None, {}, None, None)
        if should_trigger_error:
            with pytest.raises(SystemExit):
                param._validate_section_label()
            assert_that(caplog.text).contains(error_msg)
        else:
            param._validate_section_label()
            for record in caplog.records:
                assert record.levelname != "ERROR"
