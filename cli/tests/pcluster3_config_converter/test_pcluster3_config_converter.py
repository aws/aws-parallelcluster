#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import os
import subprocess

import pytest
import yaml
from assertpy import assert_that

from pcluster3_config_converter.pcluster3_config_converter import Pcluster3ConfigConverter
from tests.pcluster3_config_converter import test_data


@pytest.mark.parametrize(
    "expected_input, expected_output, warn",
    [
        (
            "pcluster.config.ini",
            "pcluster.config.yaml",
            [
                "Note: Volume encrypted defaults to True in AWS ParallelCluster version 3 while it defaults to "
                "False in AWS ParallelCluster version 2.",
                "Note: In AWS ParallelCluster version 3, access to the Instance Metadata Service(IMDS) on the head "
                "node is restricted to the cluster administrator. If additional users required access to IMDS, you "
                "can set HeadNode/Imds/Secured to False.",
                "Warning: Parameter vpc_id = vpc-12345678 is no longer supported. Ignoring it during conversion.",
                "Warning: Parameter update_check = true is no longer supported. Ignoring it during conversion.",
                "Warning: Parameter ssh = ssh {CFN_USER}@{MASTER_IP} {ARGS} is no longer supported. Ignoring it "
                "during conversion.",
                "Warning: Parameter encrypted_ephemeral = true is no longer supported. Ignoring it during conversion.",
                "Warning: additional_iam_policies = arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess is added to "
                "both headnode and scheduling sections. Please review the configuration file after conversion "
                "and decide whether to further trim down the permissions and specialize.",
                "Warning: pre_install = s3://testbucket/scripts/pre_install.sh is added to both headnode and "
                "scheduling sections. Please review the configuration file after conversion and decide whether to "
                "further trim down the permissions and specialize.",
                "Warning: post_install = s3://testbucekt/scripts/post_install.sh is added to both headnode and "
                "scheduling sections. Please review the configuration file after conversion and decide whether "
                "to further trim down the permissions and specialize.",
            ],
        ),
    ],
)
def test_pcluster3_config_converter_command(test_datadir, tmpdir, expected_input, expected_output, warn):
    config_file_path = os.path.join(str(test_datadir), expected_input)
    args = [
        "pcluster3-config-converter",
        "--config-file",
        config_file_path,
        "--output-file",
        tmpdir / "pcluster.config.yaml",
    ]
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
    _assert_files_are_equal(
        tmpdir / "pcluster.config.yaml",
        test_datadir / expected_output,
    )
    for message in warn:
        assert_that(result.stdout).contains(message)


@pytest.mark.parametrize(
    "expected_input, expected_output, warn, error, force_convert, cluster_label",
    [
        (
            "slurm_full.ini",
            "slurm_full.yaml",
            [
                "Note: Volume encrypted defaults to True in AWS ParallelCluster version 3 while it defaults to False "
                "in AWS ParallelCluster version 2.",
                "Note: In AWS ParallelCluster version 3, access to the Instance Metadata Service(IMDS) on the head "
                "node is restricted to the cluster administrator. If additional users required access to IMDS, you "
                "can set HeadNode/Imds/Secured to False.",
                "Warning: Parameter vpc_id = vpc-0e0f223cc35256b9a is no longer supported. Ignoring it "
                "during conversion.",
                "Warning: Parameter update_check = true is no longer supported. Ignoring it during conversion.",
                "Warning: Parameter ssh = ssh {CFN_USER}@{MASTER_IP} {ARGS} is no longer supported. Ignoring it "
                "during conversion.",
                "Warning: Parameter encrypted_ephemeral = true is no longer supported. Ignoring it during conversion.",
                "Warning: additional_iam_policies = arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess is added to both "
                "headnode and scheduling sections. Please review the configuration file after conversion and decide "
                "whether to further trim down the permissions and specialize.",
                "Warning: s3_read_write_resource = arn:aws:s3:::test/hello/* is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: s3_read_resource = arn:aws:s3:::testbucket/* is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: pre_install = s3://testbucket/pre_install.sh is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: post_install = s3://testbucket/post_install.sh is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: proxy_server = https://x.x.x.x:8080 is added to both headnode and scheduling sections. "
                "Please review the configuration file after conversion and decide whether to further trim down the "
                "permissions and specialize.",
                "Warning: additional_sg = sg-xxxxxx is added to both headnode and scheduling sections. Please review "
                "the configuration file after conversion and decide whether to further trim down the permissions and "
                "specialize.",
                "Warning: vpc_security_group_id = sg-xxxxxx is added to both headnode and scheduling sections. Please "
                "review the configuration file after conversion and decide whether to further trim down the "
                "permissions and specialize.",
                "Warning: Parameters ['extra_json', 'custom_chef_cookbook', 'template_url', 'instance_types_data'] "
                "are not officially supported and not recommended.",
                "Warning: Duplicate names 'custom1' are not allowed in the SharedStorage section. Please change them "
                "before cluster creation.",
                "Warning: '_' is not allowed in the name of 'compute_resource ondemand_i1'. Please rename it before "
                "cluster creation.",
                "Warning: '_' is not allowed in the name of 'compute_resource ondemand_i3'. Please rename it before "
                "cluster creation.",
                "Warning: Parameter initial_count = 2 is no longer supported. Ignoring it during conversion.",
                "Warning: '_' is not allowed in the name of 'compute_resource ondemand_i2'. Please rename it before "
                "cluster creation.",
            ],
            None,
            True,
            "default",
        ),
        (
            "slurm_required.ini",
            "slurm_required.yaml",
            [
                "Note: Volume encrypted defaults to True in AWS ParallelCluster version 3 while it defaults to False "
                "in AWS ParallelCluster version 2.",
                "Note: In AWS ParallelCluster version 3, access to the Instance Metadata Service(IMDS) on the head "
                "node is restricted to the cluster administrator. If additional users required access to IMDS, you "
                "can set HeadNode/Imds/Secured to False.",
                "Warning: Parameter vpc_id = vpc-123 is no longer supported. Ignoring it during conversion.",
                "Warning: Parameter update_check = true is no longer supported. Ignoring it during conversion.",
                "Warning: Parameter ssh = ssh {CFN_USER}@{MASTER_IP} {ARGS} is no longer supported. Ignoring it "
                "during conversion.",
            ],
            None,
            False,
            "cluster_label1",
        ),
        (
            "awsbatch_required.ini",
            "awsbatch_required.yaml",
            [
                "Note: Volume encrypted defaults to True in AWS ParallelCluster version 3 while it defaults to False "
                "in AWS ParallelCluster version 2.",
                "Warning: Parameter vpc_id = vpc-0e0f223cc35256b9a is no longer supported. Ignoring it "
                "during conversion.",
                "Warning: Parameter update_check = true is no longer supported. Ignoring it during conversion.",
                "Warning: Parameter ssh = ssh {CFN_USER}@{MASTER_IP} {ARGS} is no longer supported. Ignoring it "
                "during conversion.",
                "Warning: Parameter sanity_check = false is no longer supported, please specify "
                "`--suppress-validators ALL` during cluster creation.",
            ],
            None,
            False,
            None,
        ),
        (
            "awsbatch_full.ini",
            "awsbatch_full.yaml",
            [
                "Note: Volume encrypted defaults to True in AWS ParallelCluster version 3 while it defaults to False "
                "in AWS ParallelCluster version 2.",
                "Warning: Parameter vpc_id = vpc-0e0f223cc35256b9a is no longer supported. Ignoring it "
                "during conversion.",
                "Warning: Parameter update_check = true is no longer supported. Ignoring it during conversion.",
                "Warning: Parameter ssh = ssh {CFN_USER}@{MASTER_IP} {ARGS} is no longer supported. Ignoring it "
                "during conversion.",
                "Warning: Parameter encrypted_ephemeral = true is no longer supported. Ignoring it during conversion.",
                "Warning: Parameter sanity_check = false is no longer supported, please specify "
                "`--suppress-validators ALL` during cluster creation.",
                "Warning: s3_read_resource = arn:aws:s3:::testbucket/* is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: disable_hyperthreading = true is added to both headnode and scheduling sections. Please "
                "review the configuration file after conversion and decide whether to further trim down the "
                "permissions and specialize.",
                "Warning: pre_install = s3://testbucket/pre_install.sh is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: post_install = s3://testbucket/post_install.sh is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: proxy_server = https://x.x.x.x:8080 is added to both headnode and scheduling sections. "
                "Please review the configuration file after conversion and decide whether to further trim down the "
                "permissions and specialize.",
                "Warning: additional_sg = sg-xxxxxx is added to both headnode and scheduling sections. Please review "
                "the configuration file after conversion and decide whether to further trim down the permissions and "
                "specialize.",
                "Warning: vpc_security_group_id = sg-xxxxxx is added to both headnode and scheduling sections. Please "
                "review the configuration file after conversion and decide whether to further trim down the "
                "permissions and specialize.",
                "Warning: Parameters ['extra_json'] are not officially supported and not recommended.",
                "Warning: Duplicate names 'custom1' are not allowed in the SharedStorage section. Please change them "
                "before cluster creation.",
            ],
            None,
            True,
            "default",
        ),
        (
            "slurm_full.ini",
            None,
            [
                "Note: Volume encrypted defaults to True in AWS ParallelCluster version 3 while it defaults to False "
                "in AWS ParallelCluster version 2.",
                "Note: In AWS ParallelCluster version 3, access to the Instance Metadata Service(IMDS) on the head "
                "node is restricted to the cluster administrator. If additional users required access to IMDS, you "
                "can set HeadNode/Imds/Secured to False.",
                "Warning: Parameter vpc_id = vpc-0e0f223cc35256b9a is no longer supported. Ignoring it "
                "during conversion.",
                "Warning: Parameter update_check = true is no longer supported. Ignoring it during conversion.",
                "Warning: Parameter ssh = ssh {CFN_USER}@{MASTER_IP} {ARGS} is no longer supported. Ignoring it during "
                "conversion.",
                "Warning: Parameter encrypted_ephemeral = true is no longer supported. Ignoring it during conversion.",
                "Warning: additional_iam_policies = arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess is added to both "
                "headnode and scheduling sections. Please review the configuration file after conversion and decide "
                "whether to further trim down the permissions and specialize.",
                "Warning: s3_read_write_resource = arn:aws:s3:::test/hello/* is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: s3_read_resource = arn:aws:s3:::testbucket/* is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: pre_install = s3://testbucket/pre_install.sh is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: post_install = s3://testbucket/post_install.sh is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: proxy_server = https://x.x.x.x:8080 is added to both headnode and scheduling sections. "
                "Please review the configuration file after conversion and decide whether to further trim down the "
                "permissions and specialize.",
                "Warning: additional_sg = sg-xxxxxx is added to both headnode and scheduling sections. Please review "
                "the configuration file after conversion and decide whether to further trim down the permissions and "
                "specialize.",
                "Warning: vpc_security_group_id = sg-xxxxxx is added to both headnode and scheduling sections. Please "
                "review the configuration file after conversion and decide whether to further trim down the "
                "permissions and specialize.",
            ],
            "ERROR: ['extra_json', 'custom_chef_cookbook', 'template_url', 'instance_types_data'] are not officially "
            "supported and not recommended. If you want to proceed with conversion, please specify `--force-convert` "
            "and rerun the command.",
            False,
            None,
        ),
        (
            "compute_subnet_cidr.ini",
            None,
            None,
            "ERROR: Parameter compute_subnet_cidr = 0.0.0.0/16 is no longer supported. Please remove it and run the "
            "converter again.",
            False,
            None,
        ),
        (
            "missing_vpc.ini",
            None,
            None,
            "Missing vpc_settings in the configuration file",
            False,
            None,
        ),
        (
            "slurm_full.ini",
            None,
            None,
            "The specified cluster section is not in the configuration.",
            False,
            "invalid_cluster_label",
        ),
        (
            "slurm_requred.ini",
            None,
            None,
            "Can not find a valid cluster section.",
            False,
            None,
        ),
        (
            "sit_base.ini",
            "sit_base.yaml",
            [
                "Note: Volume encrypted defaults to True in AWS ParallelCluster version 3 while it defaults to False "
                "in AWS ParallelCluster version 2.",
                "Note: In AWS ParallelCluster version 3, access to the Instance Metadata Service(IMDS) on the head "
                "node is restricted to the cluster administrator. If additional users required access to IMDS, you "
                "can set HeadNode/Imds/Secured to False.",
                "Warning: Parameter vpc_id = vpc-12345678 is no longer supported. Ignoring it during conversion.",
                "Warning: Parameter update_check = false is no longer supported. Ignoring it during conversion.",
                "Warning: Parameter ssh = ssh {CFN_USER}@{MASTER_IP} {ARGS} is no longer supported. Ignoring it during "
                "conversion.",
            ],
            None,
            False,
            None,
        ),
        (
            "sit_full.ini",
            "sit_full.yaml",
            [
                "Note: Volume encrypted defaults to True in AWS ParallelCluster version 3 while it defaults to False "
                "in AWS ParallelCluster version 2.",
                "Note: In AWS ParallelCluster version 3, access to the Instance Metadata Service(IMDS) on the head "
                "node is restricted to the cluster administrator. If additional users required access to IMDS, you "
                "can set HeadNode/Imds/Secured to False.",
                "Warning: Parameter vpc_id = vpc-12345678 is no longer supported. Ignoring it during conversion.",
                "Warning: Parameter update_check = false is no longer supported. Ignoring it during conversion.",
                "Warning: Parameter ssh = ssh {CFN_USER}@{MASTER_IP} {ARGS} is no longer supported. Ignoring it during "
                "conversion.",
                "Warning: s3_read_write_resource = arn:aws:s3:::test/hello/* is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: s3_read_resource = arn:aws:s3:::testbucket/* is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: disable_hyperthreading = false is added to both headnode and scheduling sections. Please "
                "review the configuration file after conversion and decide whether to further trim down the "
                "permissions and specialize.",
                "Warning: pre_install = s3://testbucket/pre_install.sh is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: post_install = s3://testbucket/post_install.sh is added to both headnode and scheduling "
                "sections. Please review the configuration file after conversion and decide whether to further trim "
                "down the permissions and specialize.",
                "Warning: Parameter initial_queue_size = 2 is no longer supported. Ignoring it during conversion.",
            ],
            None,
            False,
            None,
        ),
    ],
)
def test_pcluster3_config_converter(
    test_datadir, tmpdir, expected_input, expected_output, mocker, warn, error, force_convert, capsys, cluster_label
):
    mocker.patch(
        "pcluster3_config_converter.pcluster3_config_converter.Pcluster3ConfigConverter.get_region",
        return_value="us-west-1",
    )
    mocker.patch(
        "pcluster3_config_converter.pcluster3_config_converter._get_account_id",
        return_value="1234567",
    )
    converter = Pcluster3ConfigConverter(
        test_datadir / expected_input, cluster_label, tmpdir / "output_yaml", False, force_convert
    )
    try:
        converter.validate()
        converter.convert_to_pcluster3_config()
        converter.write_configuration_file()
        _assert_files_are_equal(
            tmpdir / "output_yaml",
            test_datadir / expected_output,
        )

    except SystemExit as e:
        print(e)
        assert_that(e.args[0]).contains(error)
    if warn:
        readouterr = capsys.readouterr()
        for message in warn:
            assert_that(readouterr.out).contains(message)


@pytest.mark.parametrize(
    "test_case",
    test_data.region_test,
)
def test_convert_region(test_case):
    user_input, expected_output = test_case[0], test_case[1]
    expected_output_data = yaml.safe_load(expected_output)
    converter = Pcluster3ConfigConverter(
        config_file=user_input, cluster_template="default", output_file="dummy_output", input_as_string=True
    )
    converter.convert_region("Region")
    assert_that(converter.pcluster3_configuration).is_equal_to(expected_output_data)


@pytest.mark.parametrize(
    "test_case",
    test_data.image_test,
)
def test_convert_image(test_case):
    user_input, expected_output = test_case[0], test_case[1]
    expected_output_data = yaml.safe_load(expected_output)
    converter = Pcluster3ConfigConverter(
        config_file=user_input, cluster_template="default", output_file="dummy_output", input_as_string=True
    )
    converter.validate_cluster_section_name()
    converter.convert_image("Image")
    assert_that(converter.pcluster3_configuration).is_equal_to(expected_output_data)


@pytest.mark.parametrize(
    "test_case",
    test_data.iam_test,
)
def test_convert_iam(test_case, mocker):
    region, user_input, expected_output = test_case[0], test_case[1], test_case[2]
    mocker.patch(
        "pcluster3_config_converter.pcluster3_config_converter.Pcluster3ConfigConverter.get_region",
        return_value=region,
    )
    mocker.patch(
        "pcluster3_config_converter.pcluster3_config_converter._get_account_id",
        return_value="1234567",
    )
    expected_output_data = yaml.safe_load(expected_output)
    converter = Pcluster3ConfigConverter(
        config_file=user_input, cluster_template="default", output_file="dummy_output", input_as_string=True
    )
    converter.validate_cluster_section_name()
    converter.convert_iam("Iam")
    assert_that(converter.pcluster3_configuration).is_equal_to(expected_output_data)


@pytest.mark.parametrize(
    "test_case",
    test_data.additional_packages_test,
)
def test_convert_additional_packages(test_case):
    user_input, expected_output = test_case[0], test_case[1]
    expected_output_data = yaml.safe_load(expected_output)
    converter = Pcluster3ConfigConverter(
        config_file=user_input, cluster_template="default", output_file="dummy_output", input_as_string=True
    )
    converter.validate_cluster_section_name()
    converter.convert_additional_packages("AdditionalPackages")
    assert_that(converter.pcluster3_configuration).is_equal_to(expected_output_data)


@pytest.mark.parametrize(
    "test_case",
    test_data.tags_test,
)
def test_convert_tags(test_case):
    user_input, expected_output, error_message = test_case[0], test_case[1], test_case[2]
    expected_output_data = yaml.safe_load(expected_output)
    converter = Pcluster3ConfigConverter(
        config_file=user_input, cluster_template="default", output_file="dummy_output", input_as_string=True
    )
    converter.validate_cluster_section_name()
    try:
        converter.convert_tags("Tags")
        assert_that(converter.pcluster3_configuration).is_equal_to(expected_output_data)
    except SystemExit as e:
        assert_that(e.args[0]).contains(error_message)


@pytest.mark.parametrize(
    "test_case",
    test_data.monitoring_test,
)
def test_convert_monitoring(test_case):
    user_input, expected_output = test_case[0], test_case[1]
    expected_output_data = yaml.safe_load(expected_output)
    converter = Pcluster3ConfigConverter(
        config_file=user_input, cluster_template="default", output_file="dummy_output", input_as_string=True
    )
    converter.validate_cluster_section_name()
    converter.convert_monitoring("Monitoring")
    assert_that(converter.pcluster3_configuration).is_equal_to(expected_output_data)


@pytest.mark.parametrize(
    "test_case",
    test_data.convert_custom_s3_bucket_test,
)
def test_convert_custom_s3_bucket(test_case):
    user_input, expected_output = test_case[0], test_case[1]
    expected_output_data = yaml.safe_load(expected_output)
    converter = Pcluster3ConfigConverter(
        config_file=user_input, cluster_template="default", output_file="dummy_output", input_as_string=True
    )
    converter.validate_cluster_section_name()
    converter.convert_custom_s3_bucket("CustomS3Bucket")
    assert_that(converter.pcluster3_configuration).is_equal_to(expected_output_data)


@pytest.mark.parametrize(
    "test_case",
    test_data.convert_dev_settings_test,
)
def test_convert_dev_settings(test_case):
    user_input, expected_output = test_case[0], test_case[1]
    expected_output_data = yaml.safe_load(expected_output)
    converter = Pcluster3ConfigConverter(
        config_file=user_input, cluster_template="default", output_file="dummy_output", input_as_string=True
    )
    converter.validate_cluster_section_name()
    converter.convert_dev_settings("DevSettings")
    assert_that(converter.pcluster3_configuration).is_equal_to(expected_output_data)


@pytest.mark.parametrize(
    "test_case",
    test_data.convert_additional_resources_test,
)
def test_convert_additional_resources(test_case):
    user_input, expected_output = test_case[0], test_case[1]
    expected_output_data = yaml.safe_load(expected_output)
    converter = Pcluster3ConfigConverter(
        config_file=user_input, cluster_template="default", output_file="dummy_output", input_as_string=True
    )
    converter.validate_cluster_section_name()
    converter.convert_additional_resources("AdditionalResources")
    assert_that(converter.pcluster3_configuration).is_equal_to(expected_output_data)


@pytest.mark.parametrize(
    "test_case",
    test_data.shared_storage_test,
)
def test_convert_shared_storage(test_case):
    user_input, expected_output = test_case[0], test_case[1]
    expected_output_data = yaml.safe_load(expected_output)
    converter = Pcluster3ConfigConverter(
        config_file=user_input, cluster_template="default", output_file="dummy_output", input_as_string=True
    )
    converter.validate_cluster_section_name()
    converter.convert_shared_storage("SharedStorage")
    assert_that(converter.pcluster3_configuration).is_equal_to(expected_output_data)


@pytest.mark.parametrize(
    "test_case",
    test_data.headnode_test,
)
def test_convert_headnode(test_case, mocker):
    mocker.patch(
        "pcluster3_config_converter.pcluster3_config_converter.Pcluster3ConfigConverter.get_region",
        return_value="us-west-1",
    )
    mocker.patch(
        "pcluster3_config_converter.pcluster3_config_converter._get_account_id",
        return_value="1234567",
    )
    user_input, expected_output = test_case[0], test_case[1]
    expected_output_data = yaml.safe_load(expected_output)
    converter = Pcluster3ConfigConverter(
        config_file=user_input, cluster_template="default", output_file="dummy_output", input_as_string=True
    )
    converter.validate_cluster_section_name()
    converter.validate_vpc_settings()
    converter.convert_headnode("HeadNode")
    assert_that(converter.pcluster3_configuration).is_equal_to(expected_output_data)


@pytest.mark.parametrize(
    "test_case",
    test_data.scheduling_test,
)
def test_convert_scheduling(test_case, mocker):
    mocker.patch(
        "pcluster3_config_converter.pcluster3_config_converter.Pcluster3ConfigConverter.get_region",
        return_value="us-west-1",
    )
    mocker.patch(
        "pcluster3_config_converter.pcluster3_config_converter._get_account_id",
        return_value="1234567",
    )
    user_input, expected_output, warn = test_case[0], test_case[1], test_case[2]
    expected_output_data = yaml.safe_load(expected_output)
    converter = Pcluster3ConfigConverter(
        config_file=user_input, cluster_template="default", output_file="dummy_output", input_as_string=True
    )
    converter.validate_cluster_section_name()
    converter.validate_vpc_settings()
    converter.convert_scheduling("Scheduling")
    assert_that(converter.pcluster3_configuration).is_equal_to(expected_output_data)
    if warn:
        assert_that(converter.comments).contains(warn)


@pytest.mark.parametrize(
    "pcluster2_field, value, pcluster3_field, method, error_message",
    [
        ("proxy_server", "https://x.x.x.x:8080", "HttpProxyAddress", None, None),
        ("disable_hyperthreading", True, "DisableSimultaneousMultithreading", "getboolean", None),
        ("master_root_volume_size", 30, "Size", "getint", None),
        (
            "master_root_volume_size",
            True,
            "Size",
            "getint",
            "Wrong type for master_root_volume_size in dummy-section section: invalid literal for int() with base 10: "
            "'True'",
        ),
        ("spot_price", 20.99, "SpotPrice", "getfloat", None),
    ],
)
def test_convert_single_field(
    test_datadir, tmpdir, pcluster2_field, value, pcluster3_field, method, error_message, caplog, capsys
):
    converter = Pcluster3ConfigConverter(
        config_file="dummy_input", cluster_template="default", output_file="dummy_output"
    )
    converter.config_parser.read_dict({"dummy-section": {pcluster2_field: value}})
    pcluster3_model = {}
    try:
        converter.convert_single_field("dummy-section", pcluster2_field, pcluster3_model, pcluster3_field, method)
        assert_that(pcluster3_model).is_equal_to({pcluster3_field: value})
    except SystemExit as e:
        assert_that(e.args[0]).contains(error_message)


def _assert_files_are_equal(file, expected_file):
    with open(file, "r") as f, open(expected_file, "r") as exp_f:
        expected_file_content = exp_f.read()
        expected_file_content = expected_file_content.replace("<DIR>", os.path.dirname(file))
        assert_that(f.read()).is_equal_to(expected_file_content)
