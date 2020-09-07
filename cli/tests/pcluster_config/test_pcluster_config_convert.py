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
import os

from assertpy import assert_that

from pcluster_config import cli


def test_sge_sit(mocker, test_datadir, tmpdir):
    # template not specified, it takes the cluster_template value from global section
    _convert_and_assert_file_content(mocker, test_datadir, tmpdir)


def test_slurm_sit_simple(mocker, test_datadir, tmpdir):
    _convert_and_assert_file_content(mocker, test_datadir, tmpdir, cluster_template="slurm-sit-simple")


def test_slurm_sit_full(mocker, test_datadir, tmpdir):
    _convert_and_assert_file_content(mocker, test_datadir, tmpdir, cluster_template="slurm-sit-full")


def _convert_and_assert_file_content(mocker, test_datadir, tmpdir, cluster_template=None):
    config_file = test_datadir / "pcluster.config.ini"
    output_file = tmpdir / "pcluster.config.ini"

    argv = ["convert", "-c", str(config_file), "-o", str(output_file)]
    if cluster_template:
        argv += ["-t", cluster_template]

    mocker.patch("pcluster.config.cfn_param_types.get_availability_zone_of_subnet")
    mocker.patch("pcluster.config.cfn_param_types.get_supported_architectures_for_instance_type")
    mocker.patch("pcluster.config.json_param_types.utils.get_instance_type")

    original_default_region = os.environ.get("AWS_DEFAULT_REGION")
    if original_default_region:
        del os.environ["AWS_DEFAULT_REGION"]
    try:
        cli.main(argv)
    finally:
        if original_default_region:
            os.environ["AWS_DEFAULT_REGION"] = original_default_region

    _assert_files_are_equal(output_file, test_datadir / "expected_output.ini")


def _assert_files_are_equal(file, expected_file):
    with open(str(file)) as f, open(str(expected_file)) as exp_f:
        expected_file_content = exp_f.read()
        assert_that(f.read()).is_equal_to(expected_file_content)
