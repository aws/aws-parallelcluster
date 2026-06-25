# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from pcluster.config.imagebuilder_config import ImagebuilderDevSettings


@pytest.mark.parametrize(
    "cli_attribute_overrides, expected_cinc_version, expected_cinc_installer_url",
    [
        pytest.param(None, "", "", id="unset blob -> empty overrides"),
        pytest.param("", "", "", id="empty blob -> empty overrides"),
        pytest.param(
            '{"cinc_version": "18.8.54", "cinc_installer_url": "https://omnitruck.cinc.sh/install.sh"}',
            "18.8.54",
            "https://omnitruck.cinc.sh/install.sh",
            id="both keys unfurled",
        ),
        pytest.param('{"cinc_version": "18.8.54"}', "18.8.54", "", id="only cinc_version present"),
        pytest.param(
            '{"cinc_installer_url": "https://omnitruck.cinc.sh/install.sh"}',
            "",
            "https://omnitruck.cinc.sh/install.sh",
            id="only cinc_installer_url present",
        ),
        pytest.param('{"unrelated": "value"}', "", "", id="unknown keys ignored"),
    ],
)
def test_dev_settings_cli_attribute_overrides_unfurl(
    cli_attribute_overrides, expected_cinc_version, expected_cinc_installer_url
):
    dev_settings = ImagebuilderDevSettings(cli_attribute_overrides=cli_attribute_overrides)
    assert_that(dev_settings.cinc_version).is_equal_to(expected_cinc_version)
    assert_that(dev_settings.cinc_installer_url).is_equal_to(expected_cinc_installer_url)
