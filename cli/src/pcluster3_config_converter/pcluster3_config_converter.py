# - pcluster3_config_converter v3.0.0
#
#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import errno
import json
import os
import re
import stat
import sys

import argparse
import boto3
import configparser
import yaml


class ConfigDumper(yaml.Dumper):
    """Dumper to increase the indent when dump a list."""

    def increase_indent(self, flow=False, indentless=False):
        """Increase the indent when dump a list."""
        return super(ConfigDumper, self).increase_indent(flow, False)


def _role_name_to_arn(role_name, partition):
    """Convert role name to arn."""
    return "arn:{0}:iam::{1}:role/{2}".format(partition, _get_account_id(), role_name)


def _get_account_id():
    """Get account id from boto3 call."""
    return boto3.client("sts").get_caller_identity().get("Account")


def _error(message):
    """Raise SystemExit exception to the stderr."""
    sys.exit("ERROR: {0}".format(message))


def _warn(message):
    """Print warning message to stdout."""
    print("Warning: {0}".format(message))


def _note(message):
    """Print a note to stdout."""
    print("Note: {0}".format(message))


def _get_partition(region):
    """Get partition from the given region."""
    return next(("aws-" + partition for partition in ["us-gov", "cn"] if region.startswith(partition)), "aws")


def _add_if(section, section_name, value):
    """Add value to the dictionary only if the value exists."""
    if value:
        section[section_name] = value


def _append_if(value_list, value):
    """Add value to the dictionary only if the value exists."""
    if value:
        value_list.append(value)


def _get_bucket_name_and_key(resource_arn):
    """
    Get bucket name and key from the resource arn.

    Example input and output:
    arn:aws:s3:::my_corporate_bucket/Development/*    bucket_name:my_corporate_bucket key_name: Development/*
    arn:aws:s3:::my_corporate_bucket/*    bucket_name:my_corporate_bucket key_name: *
    arn:aws:s3:::my_corporate_bucket*    bucket_name:my_corporate_bucket key_name: *
    arn:aws:s3:::*   bucket_name:* key_name: *
    """
    if resource_arn == "*":
        return "*", None
    match = re.match(r"arn:(.*?):s3:::([^\/\*]*)((\/)?(.*))?", resource_arn)
    bucket_name, key_name = match.groups()[1], match.groups()[4]
    if bucket_name and key_name == "*":
        key_name = None
    elif not bucket_name and key_name == "*":
        bucket_name, key_name = "*", None
    return bucket_name, key_name


class Pcluster3ConfigConverter(object):
    """Class to manage the configuration conversion of a ParallelCluster 2 configuration file to ParallelCluster 3."""

    def __init__(self, config_file, cluster_template, output_file, input_as_string=False, force_convert=None):
        self.config_parser = None
        self.force_convert = force_convert
        self.config_file = config_file
        self.cluster_label = cluster_template  # args.cluster_template
        self.output_file = output_file
        self.input_as_string = input_as_string
        self.pcluster3_configuration = dict()
        self.convert_shared_storage_name = list()
        self.cluster_section_name = None
        self.vpc_section_label = None
        self.comments = ""
        self.init_config_parser()

    def init_config_parser(self):
        """Read config from config file or from string."""
        try:
            self.config_parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
            self.config_parser.read_string(self.config_file) if self.input_as_string else self.config_parser.read(
                self.config_file
            )
        except (configparser.ParsingError, configparser.DuplicateOptionError) as e:
            _error("Error parsing configuration file {0}.\n{1}".format(self.config_file, str(e)))

    def validate(self):
        """Validate fields in AWS ParallelCluster version 2 configuration file."""
        self.validate_cluster_section_name()
        self.validate_vpc_settings()
        self.validate_required_fields()
        self.validate_deprecated_fields()
        self.validate_ambiguous_fields()
        self.validate_dev_settings()
        self.validate_shared_storages_name()
        self.validate_slurm_queues()
        self.validate_default_ebs()

    def convert_to_pcluster3_config(self):
        """Convert config_parser object to AWS ParallelCluster version 3 configuration file."""
        convert_function_mappings = {
            "Region": self.convert_region,
            "Image": self.convert_image,
            "CustomS3Bucket": self.convert_custom_s3_bucket,
            "AdditionalResources": self.convert_additional_resources,
            "Iam": self.convert_iam,
            "AdditionalPackages": self.convert_additional_packages,
            "Tags": self.convert_tags,
            "SharedStorage": self.convert_shared_storage,
            "Monitoring": self.convert_monitoring,
            "HeadNode": self.convert_headnode,
            "Scheduling": self.convert_scheduling,
            "DevSettings": self.convert_dev_settings,
        }
        for section_name, convert_function in convert_function_mappings.items():
            convert_function(section_name)

    def convert_region(self, section_name):
        """Convert Region section."""
        self.convert_single_field("aws", "aws_region_name", self.pcluster3_configuration, section_name)

    def convert_image(self, section_name):
        """Convert Image section."""
        image = dict()
        self.convert_single_field(self.cluster_section_name, "custom_ami", image, "CustomAmi")
        self.convert_single_field(self.cluster_section_name, "base_os", image, "Os")
        _add_if(self.pcluster3_configuration, section_name, image)

    def convert_iam(self, section_name):
        """Convert Iam section."""
        iam = dict()
        role = dict()
        iam_lambda_role = self.cluster_config_get("iam_lambda_role")
        if iam_lambda_role:
            role["LambdaFunctionRole"] = _role_name_to_arn(iam_lambda_role, _get_partition(self.get_region()))
        _add_if(iam, "Role", role)
        _add_if(self.pcluster3_configuration, section_name, iam)

    def convert_additional_packages(self, section_name):
        """Convert AdditionalPackages section."""
        additional_packages = dict()
        intel_software = dict()
        self.convert_single_field(
            self.cluster_section_name, "enable_intel_hpc_platform", intel_software, "IntelHpcPlatform", "getboolean"
        )
        _add_if(additional_packages, "IntelSoftware", intel_software)
        _add_if(self.pcluster3_configuration, section_name, additional_packages)

    def convert_tags(self, section_name):
        """Convert Tags section."""
        tags = self.cluster_config_get("tags")
        if not tags:
            return
        try:
            tags = json.loads(tags)
        except Exception as e:
            _error(f"Tags should be in the format of dictionary, {e}")
        self.pcluster3_configuration["Tags"] = []
        for key, value in tags.items():
            self.pcluster3_configuration[section_name].append({"Key": key, "Value": value})

    def convert_shared_storage(self, section_name):
        """Convert SharedStorage section."""
        shared_storage = []
        function_section_mappings = {
            self.convert_ebs_settings: "EbsSettings",
            self.convert_raid_settings: "EbsSettings",
            self.convert_efs_settings: "EfsSettings",
            self.convert_fsx_settings: "FsxLustreSettings",
        }
        for convert_function, storage_section_name in function_section_mappings.items():
            storage = convert_function(storage_section_name)
            if storage:
                shared_storage += storage
        _add_if(self.pcluster3_configuration, section_name, shared_storage)

    def convert_storage_base(self, storage_type, label, additional_items=None):
        """Convert common parameters for SharedStorage section."""
        if not additional_items:
            additional_items = list()
        storage_section = dict()
        settings = dict()
        storage_section["Name"] = label
        storage_type_mapping = {"ebs": "Ebs", "raid": "Ebs", "fsx": "FsxLustre", "efs": "Efs"}
        storage_section["StorageType"] = storage_type_mapping[storage_type]
        section_label = f"{storage_type} {label}"
        for item in [
            (section_label, "shared_dir", storage_section, "MountDir"),
            (section_label, "encrypted", settings, "Encrypted", "getboolean"),
        ]:
            self.convert_single_field(*item)
        for item in additional_items:
            pc2_label, pc3_label = item[0], item[1]
            conversion_type = item[2] if len(item) == 3 else None
            self.convert_single_field(section_label, pc2_label, settings, pc3_label, conversion_type)
        return storage_section, settings, section_label

    def convert_ebs_settings(self, section_name):
        """Convert ebs_settings in AWS ParallelCluster version 2 to EbsSettings in SharedStorage section."""
        ebs_settings = self.cluster_config_get("ebs_settings")
        ebs_lists = []
        # When ebs_settings is not specified, a default ebs volume will be created under /shared directory.
        if not ebs_settings:
            return self.convert_default_ebs(ebs_lists)
        for ebs_label in ebs_settings.split(","):
            additional_items = [
                ("volume_type", "VolumeType"),
                ("volume_size", "Size", "getint"),
                ("volume_iops", "Iops", "getint"),
                ("ebs_snapshot_id", "SnapshotId"),
                ("ebs_kms_key_id", "KmsKeyId"),
                ("ebs_volume_id", "VolumeId"),
                ("volume_throughput", "Throughput", "getint"),
            ]
            ebs_section, settings, _section_label = self.convert_storage_base(
                "ebs", ebs_label.strip(), additional_items
            )
            # If there's only one EBS and shared_dir is specify in the cluster section, it will be used as shared_dir.
            if len(ebs_settings.split(",")) == 1 and self.cluster_config_get("shared_dir"):
                self.convert_single_field(self.cluster_section_name, "shared_dir", ebs_section, "MountDir")
            _add_if(ebs_section, section_name, settings)
            _append_if(ebs_lists, ebs_section)
        return ebs_lists

    def convert_raid_settings(self, section_name):
        """Convert raid_settings in AWS ParallelCluster version 2 to EbsSettings in SharedStorage section."""
        raid_settings = self.cluster_config_get("raid_settings")
        if not raid_settings:
            return None
        raid_list = []
        for raid_label in raid_settings.split(","):
            additional_items = [
                ("volume_type", "VolumeType"),
                ("volume_size", "Size", "getint"),
                ("volume_iops", "Iops", "getint"),
                ("ebs_kms_key_id", "KmsKeyId"),
                ("volume_throughput", "Throughout", "getint"),
            ]
            ebs_section, ebs_settings, section_label = self.convert_storage_base(
                "raid", raid_label.strip(), additional_items
            )
            raid_dict = dict()
            for item in [
                (section_label, "num_of_raid_volumes", raid_dict, "NumberOfVolumes", "getint"),
                (section_label, "raid_type", raid_dict, "Type", "getint"),
            ]:
                self.convert_single_field(*item)
            _add_if(ebs_settings, "Raid", raid_dict)
            _add_if(ebs_section, section_name, ebs_settings)
            _append_if(raid_list, ebs_section)
        return raid_list

    def convert_efs_settings(self, section_name):
        """Convert efs_settings in SharedStorage section."""
        efs_settings = self.cluster_config_get("efs_settings")
        if not efs_settings:
            return None
        efs_list = []
        for efs_label in efs_settings.split(","):
            additional_items = [
                ("performance_mode", "PerformanceMode"),
                ("efs_fs_id", "FileSystemId"),
                ("efs_kms_key_id", "KmsKeyId"),
                ("provisioned_throughput", "ProvisionedThroughput", "getint"),
                ("throughput_mode", "ThroughputMode"),
            ]
            efs_section, efs_dict, _section_label = self.convert_storage_base(
                "efs", efs_label.strip(), additional_items
            )
            _add_if(efs_section, section_name, efs_dict)
            _append_if(efs_list, efs_section)
        return efs_list

    def convert_fsx_settings(self, section_name):
        """Convert fsx_settings in SharedStorage section."""
        fsx_settings = self.cluster_config_get("fsx_settings")
        if not fsx_settings:
            return None
        fsx_list = []
        for fsx_label in fsx_settings.split(","):
            additional_items = [
                ("auto_import_policy", "AutoImportPolicy"),
                ("fsx_fs_id", "FileSystemId"),
                ("fsx_kms_key_id", "KmsKeyId"),
                ("storage_capacity", "StorageCapacity", "getint"),
                ("deployment_type", "DeploymentType"),
                ("storage_type", "StorageType"),
                ("imported_file_chunk_size", "ImportedFileChunkSize", "getint"),
                ("data_compression_type", "DataCompressionType"),
                ("export_path", "ExportPath"),
                ("import_path", "ImportPath"),
                ("weekly_maintenance_start_time", "WeeklyMaintenanceStartTime"),
                (
                    "automatic_backup_retention_days",
                    "AutomaticBackupRetentionDays",
                    "getint",
                ),
                ("copy_tags_to_backups", "CopyTagsToBackups", "getboolean"),
                ("daily_automatic_backup_start_time", "DailyAutomaticBackupStartTime"),
                ("per_unit_storage_throughput", "PerUnitStorageThroughput", "getint"),
                ("fsx_backup_id", "BackupId"),
                ("drive_cache_type", "DriveCacheType"),
            ]
            fsx_section, fsx_dict, _section_label = self.convert_storage_base(
                "fsx", fsx_label.strip(), additional_items
            )
            _add_if(fsx_section, section_name, fsx_dict)
            _append_if(fsx_list, fsx_section)
        return fsx_list

    def convert_monitoring(self, section_name):
        """Convert Monitoring section."""
        monitoring = dict()
        logs = dict()
        cloudwatch = dict()
        cw_log_settings = self.cluster_config_get("cw_log_settings")
        if cw_log_settings:
            section_label = f"cw_log {cw_log_settings.strip()}"
            self.convert_single_field(section_label, "enable", cloudwatch, "Enabled", "getboolean")
            self.convert_single_field(section_label, "retention_days", cloudwatch, "RetentionInDays", "getint")

        dashboards = dict()
        dashboard_cloudwatch = dict()
        dashboard_settings = self.cluster_config_get("dashboard_settings")
        if dashboard_settings:
            section_label = f"dashboard {dashboard_settings.strip()}"
            self.convert_single_field(section_label, "enable", dashboard_cloudwatch, "Enabled", "getboolean")

        _add_if(logs, "CloudWatch", cloudwatch)
        _add_if(monitoring, "Logs", logs)
        _add_if(dashboards, "CloudWatch", dashboard_cloudwatch)
        _add_if(monitoring, "Dashboards", dashboards)
        _add_if(self.pcluster3_configuration, section_name, monitoring)

    def convert_headnode(self, section_name):
        """Convert HeadNode section."""
        headnode = dict()
        self.convert_instance_type(headnode, "master_instance_type")
        self.convert_networking(headnode)
        self.convert_disable_hyperthreading(headnode)
        self.convert_ssh(headnode)
        self.convert_local_storage(headnode, "master_root_volume_size")
        self.convert_dcv(headnode)
        self.convert_custom_action(headnode)
        self.covert_headnode_iam(headnode)
        self.convert_imds(headnode)
        _add_if(self.pcluster3_configuration, section_name, headnode)

    def convert_single_field(
        self, pcluster2_model, pcluster2_attribute, pcluster3_model, pcluster3_attribute, function_name=None
    ):
        """Convert a single field from config_parser object to parameter in AWS ParallelCluster version 3 model."""
        try:
            function_map = {
                "getboolean": self.config_parser.getboolean,
                "getint": self.config_parser.getint,
                "getfloat": self.config_parser.getfloat,
            }
            function = function_map.get(function_name, self.config_parser.get)
            attribute = function(pcluster2_model, pcluster2_attribute, fallback=None)
            if attribute is not None:
                pcluster3_model[pcluster3_attribute] = attribute
        except Exception as e:
            _error(f"Wrong type for {pcluster2_attribute} in {pcluster2_model} section: {e}")

    def write_configuration_file(self):
        """Write converted yaml to the output file."""
        if self.output_file:
            if os.path.isfile(self.output_file):
                _error(f"File {self.output_file} already exists, please select another output file.")
            else:
                try:
                    config_folder = os.path.dirname(self.output_file) or "."
                    os.makedirs(config_folder)
                except OSError as e:
                    if e.errno != errno.EEXIST:
                        raise
            # Fix permissions
            with open(self.output_file, "a", encoding="utf-8"):
                os.chmod(self.output_file, stat.S_IRUSR | stat.S_IWUSR)

            # Write configuration to disk
            with open(self.output_file, "w", encoding="utf-8") as config_file:
                config_file.write(self.comments)
                yaml.dump(
                    self.pcluster3_configuration,
                    config_file,
                    sort_keys=False,
                    Dumper=ConfigDumper,
                    default_flow_style=False,
                )
            print(f"Configuration file written to {self.output_file}")
        else:
            sys.stdout.write(self.comments)
            yaml.dump(
                self.pcluster3_configuration,
                sys.stdout,
                sort_keys=False,
                Dumper=ConfigDumper,
                default_flow_style=False,
            )
            sys.stdout.flush()

    def validate_cluster_section_name(self):
        """
        Validate cluster section name.

        If cluster_template is specified in the command, use specifeid cluster_template to find the cluster section.
        If cluster_label is not specified, use cluster template specified in global section.
        If no cluster_label sepcified in the cluster section, verify if default cluster section exists.
        """
        if self.cluster_label:
            self.cluster_section_name = f"cluster {self.cluster_label}"
        elif self.config_parser.get("global", "cluster_template", fallback=None):
            cluster_template = self.config_parser.get("global", "cluster_template", fallback=None)
            self.cluster_section_name = f"cluster {cluster_template}"
        elif "cluster default" in self.config_parser:
            self.cluster_section_name = "cluster default"
        else:
            _error("Can not find a valid cluster section.")
        if self.cluster_section_name not in self.config_parser.sections():
            _error("The specified cluster section is not in the configuration.")

    def validate_required_fields(self):
        """Validate required fields for conversion."""
        self.comments += (
            "# Volume encrypted defaults to True in AWS ParallelCluster version 3 while it defaults to False in "
            "AWS ParallelCluster version 2.\n"
        )
        _note(
            "Volume encrypted defaults to True in AWS ParallelCluster version 3 while it defaults to False in AWS "
            "ParallelCluster version 2."
        )
        if self.cluster_config_get("scheduler") == "slurm":
            message = (
                "In AWS ParallelCluster version 3, access to the Instance Metadata Service(IMDS) on the head node is "
                "restricted to the cluster administrator. If additional users required access to IMDS, you can set "
                "HeadNode/Imds/Secured to False."
            )
            _note(message)
            self.comments += f"# {message}\n"

        self.validate_scheduler()

    def validate_deprecated_fields(self):
        """Validate fields that are used in ParallelCluster 2 but deprecated in ParallelCluster3."""
        for item in [
            (self.vpc_section_label, "vpc_id", "ignored"),
            (self.vpc_section_label, "compute_subnet_cidr", "need_remove"),
            ("global", "update_check", "ignored"),
            ("aliases", "ssh", "ignored"),
            (self.cluster_section_name, "encrypted_ephemeral", "ignored"),
        ]:
            self.validate_single_field(*item)
        if self.config_parser.getboolean("global", "sanity_check", fallback=None) is False:
            _warn(
                "Parameter sanity_check = false is no longer supported, please specify `--suppress-validators ALL` "
                "during cluster creation."
            )
            self.comments += "# sanity_check = false is ignored\n"

    def convert_networking(self, headnode):
        """Convert HeadNode Networking."""
        networking = dict()
        security_groups = []
        additional_security_groups = []
        if self.vpc_section_label:
            for item in [
                (self.vpc_section_label, "master_subnet_id", networking, "SubnetId"),
                (self.vpc_section_label, "use_public_ips", networking, "ElasticIp", "getboolean"),
            ]:
                self.convert_single_field(*item)
            vpc_security_group_id = self.config_parser.get(
                self.vpc_section_label, "vpc_security_group_id", fallback=None
            )
            _append_if(security_groups, vpc_security_group_id)
            additional_sg = self.config_parser.get(self.vpc_section_label, "additional_sg", fallback=None)
            _append_if(additional_security_groups, additional_sg)
        proxy = dict()
        self.convert_single_field(self.cluster_section_name, "proxy_server", proxy, "HttpProxyAddress")
        _add_if(networking, "Proxy", proxy)
        _add_if(networking, "SecurityGroups", security_groups)
        _add_if(networking, "AdditionalSecurityGroups", additional_security_groups)
        _add_if(headnode, "Networking", networking)

    def convert_slurm_queue_networking(self, queue, queue_section):
        """Convert SlurmQueue Networking."""
        networking = self.convert_base_queue_networking()
        placement_group = dict()
        placement = self.config_parser.get(queue_section, "placement_group", fallback=None)
        if placement == "DYNAMIC":
            placement_group["Enabled"] = True
        elif placement:
            placement_group["Id"] = placement
        _add_if(networking, "PlacementGroup", placement_group)

        proxy = dict()
        self.convert_single_field(self.cluster_section_name, "proxy_server", proxy, "HttpProxyAddress")
        _add_if(networking, "Proxy", proxy)
        _add_if(queue, "Networking", networking)

    def convert_base_queue_networking(self):
        """Convert common networking parameters for SlurmQueues and BatchQueues."""
        networking = dict()
        security_groups = []
        additional_security_groups = []
        subnet_ids = []

        if self.vpc_section_label:
            if self.config_parser.get(self.vpc_section_label, "compute_subnet_id", fallback=None):
                subnet_field = "compute_subnet_id"
            else:
                subnet_field = "master_subnet_id"
            subnet_id = self.config_parser.get(self.vpc_section_label, subnet_field, fallback=None)
            _append_if(subnet_ids, subnet_id)
            vpc_security_group_id = self.config_parser.get(
                self.vpc_section_label, "vpc_security_group_id", fallback=None
            )
            _append_if(security_groups, vpc_security_group_id)
            additional_sg = self.config_parser.get(self.vpc_section_label, "additional_sg", fallback=None)
            _append_if(additional_security_groups, additional_sg)
        _add_if(networking, "SubnetIds", subnet_ids)
        _add_if(networking, "SecurityGroups", security_groups)
        _add_if(networking, "AdditionalSecurityGroups", additional_security_groups)
        return networking

    def convert_batch_queue_networking(self, queue):
        """Convert awsbatch queue networking."""
        networking = self.convert_base_queue_networking()
        _add_if(queue, "Networking", networking)

    def convert_instance_type(self, headnode, param_name):
        """Convert HeadNode or SIT compute resource InstanceType."""
        instance_type = self.cluster_config_get(param_name)
        headnode["InstanceType"] = instance_type if instance_type else "t2.micro"

    def convert_disable_hyperthreading(self, headnode):
        """Convert Headnode DisableSimultaneousMultithreading."""
        self.convert_single_field(
            self.cluster_section_name,
            "disable_hyperthreading",
            headnode,
            "DisableSimultaneousMultithreading",
            "getboolean",
        )

    def convert_ssh(self, headnode):
        """Convert HeadNode Ssh section."""
        ssh = dict()
        self.convert_single_field(self.cluster_section_name, "key_name", ssh, "KeyName")
        self.convert_single_field(self.vpc_section_label, "ssh_from", ssh, "AllowedIps")
        _add_if(headnode, "Ssh", ssh)

    def validate_vpc_settings(self):
        """Validate vpc settings exists in AWS ParallelCluster version 2 config."""
        vpc_settings = self.cluster_config_get("vpc_settings")
        if vpc_settings:
            self.vpc_section_label = f"vpc {vpc_settings.strip()}"
        else:
            _error("Missing vpc_settings in the configuration file.")

    def convert_local_storage(self, headnode, volume_size):
        """Convert LocalStorage for HeadNode and Queue."""
        local_storage = dict()
        root_volume = dict()
        self.convert_single_field(self.cluster_section_name, volume_size, root_volume, "Size", "getint")
        ephemeral_volume = dict()
        self.convert_single_field(self.cluster_section_name, "ephemeral_dir", ephemeral_volume, "MountDir")
        _add_if(local_storage, "RootVolume", root_volume)
        _add_if(local_storage, "EphemeralVolume", ephemeral_volume)
        _add_if(headnode, "LocalStorage", local_storage)

    def convert_dcv(self, headnode):
        """Convert HeadNode DCV section."""
        dcv = dict()
        dcv_settings = self.cluster_config_get("dcv_settings")
        if dcv_settings:
            section_label = f"dcv {dcv_settings.strip()}"
            if self.config_parser.get(section_label, "enable") == "master":
                dcv["Enabled"] = True
            self.convert_single_field(section_label, "port", dcv, "Port", "getint")
            self.convert_single_field(section_label, "access_from", dcv, "AllowedIps")
        _add_if(headnode, "Dcv", dcv)

    def convert_custom_action(self, headnode):
        """Convert CustomAction for HeadNode and SlurmQueue."""
        custom_actions = dict()
        on_node_start = dict()
        on_node_configured = dict()
        self.convert_single_field(self.cluster_section_name, "pre_install", on_node_start, "Script")
        self.convert_single_field(self.cluster_section_name, "post_install", on_node_configured, "Script")
        pre_install_args_list = []
        post_install_args_list = []
        pre_install_args = self.cluster_config_get("pre_install_args")
        if pre_install_args:
            pre_install_args_list.append(self.cluster_config_get("pre_install"))
            pre_install_args_list += pre_install_args.replace("'", "").replace('"', "").split()
        post_install_args = self.cluster_config_get("post_install_args")
        if post_install_args:
            post_install_args_list.append(self.cluster_config_get("post_install"))
            post_install_args_list += post_install_args.replace("'", "").replace('"', "").split()
        _add_if(on_node_start, "Args", pre_install_args_list)
        _add_if(on_node_configured, "Args", post_install_args_list)
        _add_if(custom_actions, "OnNodeStart", on_node_start)
        _add_if(custom_actions, "OnNodeConfigured", on_node_configured)
        _add_if(headnode, "CustomActions", custom_actions)

    def covert_headnode_iam(self, headnode):
        """Convert HeadNode and slurm queue Iam section."""
        iam = dict()
        s3_access = []
        additional_iam_policies = []
        ec2_iam_role = self.cluster_config_get("ec2_iam_role")
        if ec2_iam_role:
            iam["InstanceRole"] = _role_name_to_arn(ec2_iam_role, _get_partition(self.get_region()))
        additional_iam_policies_list = self.cluster_config_get("additional_iam_policies")
        if additional_iam_policies_list:
            for policy in additional_iam_policies_list.split(","):
                additional_iam_policies.append({"Policy": policy.strip()})

        s3_read_resource = self.cluster_config_get("s3_read_resource")
        s3_read_write_resource = self.config_parser.get(
            self.cluster_section_name, "s3_read_write_resource", fallback=None
        )
        if s3_read_resource:
            bucket_name, key = _get_bucket_name_and_key(s3_read_resource)
            if key:
                s3_access.append({"BucketName": bucket_name, "KeyName": key})
            else:
                s3_access.append({"BucketName": bucket_name})
        if s3_read_write_resource:
            bucket_name, key = _get_bucket_name_and_key(s3_read_write_resource)
            if not bucket_name:
                _error(
                    f"BucketName is required in 's3_read_write_resource = {s3_read_write_resource}' for AWS "
                    "ParallelCluster version 3 configuration."
                )
            if key:
                s3_access.append({"EnableWriteAccess": True, "BucketName": bucket_name, "KeyName": key})
            else:
                s3_access.append({"EnableWriteAccess": True, "BucketName": bucket_name})
        _add_if(iam, "AdditionalIamPolicies", additional_iam_policies)
        _add_if(iam, "S3Access", s3_access)
        _add_if(headnode, "Iam", iam)

    def convert_scheduling(self, section_name):
        """Convert Scheduling section."""
        scheduling = dict()
        self.convert_single_field(self.cluster_section_name, "scheduler", scheduling, "Scheduler")
        scheduler = self.cluster_config_get("scheduler")
        if scheduler == "slurm":
            self.convert_slurm_settings(scheduling, "SlurmSettings")
            self.convert_slurm_queues(scheduling, "SlurmQueues")
        elif scheduler == "awsbatch":
            self.convert_batch_queues(scheduling, "AwsBatchQueues")

        _add_if(self.pcluster3_configuration, section_name, scheduling)

    def convert_slurm_settings(self, scheduling, section_name):
        """Convert Slurm Settings."""
        slurm_settings = dict()
        dns = dict()
        scaling_settings = self.cluster_config_get("scaling_settings")
        if scaling_settings:
            section_label = f"scaling {scaling_settings.strip()}"
            self.convert_single_field(
                section_label, "scaledown_idletime", slurm_settings, "ScaledownIdletime", "getint"
            )
        self.convert_single_field(
            self.cluster_section_name, "disable_cluster_dns", dns, "DisableManagedDns", "getboolean"
        )
        _add_if(slurm_settings, "Dns", dns)
        _add_if(scheduling, section_name, slurm_settings)

    def cluster_config_get(self, param):
        """Get parameter from cluster section."""
        return self.config_parser.get(self.cluster_section_name, param, fallback=None)

    def convert_slurm_queues(self, scheduling, param):
        """Convert all queues from queue_settings."""
        slurm_queues = []
        queue_settings = self.cluster_config_get("queue_settings")
        if not queue_settings:
            return self.convert_sit_queue(scheduling, param)
        for queue_label in queue_settings.split(","):
            queue = self.convert_single_slurm_queue(queue_label)
            _append_if(slurm_queues, queue)
        _add_if(scheduling, param, slurm_queues)

    def convert_single_slurm_queue(self, queue_label):
        """Convert single SlurmQueue."""
        queue = dict()
        queue_name = queue_label.strip()
        queue_section = f"queue {queue_name}"
        queue["Name"] = queue_name
        self.convert_single_field(queue_section, "compute_type", queue, "CapacityType")
        if "CapacityType" in queue:
            queue["CapacityType"] = queue["CapacityType"].upper()
        self.convert_slurm_compute_resources(queue, queue_section)
        self.convert_custom_action(queue)
        self.covert_headnode_iam(queue)
        self.convert_slurm_queue_networking(queue, queue_section)
        self.convert_slurm_compute_settings(queue)
        return queue

    def convert_slurm_compute_resources(self, queue, queue_section):
        """Convert all slurm conpute resources under a Slurm Queue."""
        compute_resources = []
        compute_resource_settings = self.config_parser.get(queue_section, "compute_resource_settings", fallback=None)
        for compute_resource_label in compute_resource_settings.split(","):
            compute_resource = self.convert_single_slurm_compute_resource(compute_resource_label, queue_section)
            _append_if(compute_resources, compute_resource)
        _add_if(queue, "ComputeResources", compute_resources)

    def convert_batch_queues(self, scheduling, param):
        """Convert AwsBatch Queue."""
        batch_queues = []
        queue = dict()
        queue["Name"] = "batch-queue"
        self.convert_single_field(self.cluster_section_name, "cluster_type", queue, "CapacityType")
        if "CapacityType" in queue:
            queue["CapacityType"] = queue["CapacityType"].upper()
        self.convert_batch_queue_networking(queue)
        self.convert_batch_compute_resources(queue)

        _append_if(batch_queues, queue)
        _add_if(scheduling, param, batch_queues)

    def convert_batch_compute_resources(self, queue):
        """Convert all compute resources under a AwsBatch queue."""
        compute_resources = []
        compute_resource = dict()
        compute_resource["Name"] = "batch-compute"
        for item in [
            (self.cluster_section_name, "min_vcpus", compute_resource, "MinvCpus", "getint"),
            (self.cluster_section_name, "max_vcpus", compute_resource, "MaxvCpus", "getint"),
            (self.cluster_section_name, "desired_vcpus", compute_resource, "DesiredvCpus", "getint"),
            (self.cluster_section_name, "spot_bid_percentage", compute_resource, "SpotBidPercentage", "getfloat"),
        ]:
            self.convert_single_field(*item)
        instance_types = []
        compute_instance_type = self.cluster_config_get("compute_instance_type")
        if compute_instance_type:
            for instance_type in compute_instance_type.split(","):
                instance_types.append(instance_type.strip())
        else:
            instance_types.append("t2.micro")
        _add_if(compute_resource, "InstanceTypes", instance_types)
        _append_if(compute_resources, compute_resource)
        _add_if(queue, "ComputeResources", compute_resources)

    def validate_scheduler(self):
        """Validate if the Scheduler is the one supported by AWS ParallelCluster version 3."""
        scheduler = self.cluster_config_get("scheduler")
        if not scheduler:
            _error("scheduler must be provided in the config.")
        elif scheduler in ["sge", "torque"]:
            _error(
                "The provided scheduler is no longer supported in AWS ParallelCluster version 3, please check "
                "https://docs.aws.amazon.com/parallelcluster/latest/ug/schedulers-v3.html for supported schedulers."
            )
        elif scheduler not in ["slurm", "awsbatch"]:
            _error(f"Wrong value for scheduler: {scheduler}.")

    def validate_single_field(self, section, field, message):
        """Validate whether a filed in AWS ParallelCluster version 2 is supported in AWS ParallelCluster version 3."""
        value = self.config_parser.get(section, field, fallback=None)
        if not value:
            return
        if message == "ignored":
            self.comments += f"# {field} = {value} is ignored\n"
            _warn(f"Parameter {field} = {value} is no longer supported. Ignoring it during conversion.")
        elif message == "need_remove":
            _error(f"Parameter {field} = {value} is no longer supported. Please remove it and run the converter again.")
        elif message == "ambiguous":
            _warn(
                f"{field} = {value} is added to both headnode and scheduling sections. Please review the "
                f"configuration file after conversion and decide whether to further trim down the permissions and "
                f"specialize."
            )
        elif message == "dev_settings":
            if self.force_convert:
                self.comments += f"# {field} = {value} is not officially supported and not recommended\n"
                _warn(f"Parameter {field} = {value} is no longer supported. Ignoring it during conversion.")
            else:
                _error(
                    f"{field} is not officially supported and not recommended. If you want to proceed with "
                    f"conversion, please specify `--force-convert` and rerun the command"
                )

    def validate_default_name(self, name, section):
        """Validate if 'default' appears in SharedStorage name, Queue name or ComputeResource name."""
        if name == "default":
            message = f"'default' is not allowed as a section name for '{section}' in AWS ParallelCluster Version 3. "
            "Please rename it before cluster creation."
            _warn(message)
            self.comments += f"# {message}\n"

    def validate_underscore_in_name(self, name, section):
        """Validate if there are underscore in Queue name or ComputeResource name."""
        if "_" in name:
            message = f"'_' is not allowed in the name of '{section}'. Please rename it before cluster creation."
            _warn(message)
            self.comments += f"# {message}\n"

    def validate_ambiguous_fields(self):
        """Validate fields that may be added in both headnode and queues."""
        for item in [
            (self.cluster_section_name, "additional_iam_policies", "ambiguous"),
            (self.cluster_section_name, "s3_read_write_resource", "ambiguous"),
            (self.cluster_section_name, "s3_read_resource", "ambiguous"),
            (self.cluster_section_name, "disable_hyperthreading", "ambiguous"),
            (self.cluster_section_name, "pre_install", "ambiguous"),
            (self.cluster_section_name, "post_install", "ambiguous"),
            (self.cluster_section_name, "proxy_server", "ambiguous"),
            (self.vpc_section_label, "additional_sg", "ambiguous"),
            (self.vpc_section_label, "vpc_security_group_id", "ambiguous"),
        ]:
            self.validate_single_field(*item)

    def convert_dev_settings(self, section_name):
        """Convert DevSettings section."""
        dev_settings = dict()
        cookbook = dict()
        for item in [
            (self.cluster_section_name, "extra_json", cookbook, "ExtraChefAttributes"),
            (self.cluster_section_name, "custom_chef_cookbook", cookbook, "ChefCookbook"),
            (self.cluster_section_name, "template_url", dev_settings, "ClusterTemplate"),
            (self.cluster_section_name, "instance_types_data", dev_settings, "InstanceTypesData"),
        ]:
            self.convert_single_field(*item)
        _add_if(dev_settings, "Cookbook", cookbook)
        _add_if(self.pcluster3_configuration, section_name, dev_settings)

    def convert_custom_s3_bucket(self, section_name):
        """Convert CustomS3Bucket section."""
        self.convert_single_field(
            self.cluster_section_name, "cluster_resource_bucket", self.pcluster3_configuration, section_name
        )

    def convert_additional_resources(self, section_name):
        """Convert AdditionalResources section."""
        self.convert_single_field(
            self.cluster_section_name, "additional_cfn_template", self.pcluster3_configuration, section_name
        )

    def validate_dev_settings(self):
        """Validate fields in DevSettings."""
        dev_settings = []
        for param in ["extra_json", "custom_chef_cookbook", "template_url", "instance_types_data"]:
            if self.cluster_config_get(param):
                dev_settings.append(param)
        if dev_settings:
            if self.force_convert is True:
                _warn(f"Parameters {dev_settings} are not officially supported and not recommended.\n")
                self.comments += (
                    "# The configuration parameters under DevSettings are not officially supported and their name or "
                    "structure may change\n"
                    "# over time without any commitment to be backward compatible.\n"
                )
            else:
                _error(
                    f"{dev_settings} are not officially supported and not recommended. If you want to proceed with "
                    f"conversion, please specify `--force-convert` and rerun the command."
                )

    def convert_default_ebs(self, ebs_list):
        """If ebe_settings is not specified, create a default EBS volume."""
        shared_dir = self.cluster_config_get("shared_dir") if self.cluster_config_get("shared_dir") else "/shared"
        ebs_list.append({"MountDir": shared_dir, "Name": "default-ebs", "StorageType": "Ebs"})
        return ebs_list

    def convert_slurm_compute_settings(self, queue):
        """Convert ComputeSettings for slurm queue."""
        compute_settings = {}
        self.convert_local_storage(compute_settings, "compute_root_volume_size")
        _add_if(queue, "ComputeSettings", compute_settings)

    def get_region(self):
        """Get region to use for instance role arn and instance profile arn."""
        config_region = self.config_parser.get("aws", "aws_region_name", fallback=None)
        boto_region = boto3.Session().region_name
        if not config_region and not boto_region:
            _error("Region not found. Please specify aws_region_name in the configuration or set region in aws_config.")
        return config_region or boto_region

    def convert_imds(self, headnode):
        """Convert HeadNode Imds section."""
        imds = dict()
        if self.cluster_config_get("scheduler") == "awsbatch":
            imds["Secured"] = False
        _add_if(headnode, "Imds", imds)

    def convert_single_slurm_compute_resource(self, compute_resource_label, queue_section):
        """Convert single compute resource for a slurm queue."""
        compute_resource = dict()
        efa = dict()
        compute_resource_name = compute_resource_label.strip()
        compute_resource_section = f"compute_resource {compute_resource_name}"
        compute_resource["Name"] = compute_resource_name
        if self.cluster_config_get("enable_efa") == "compute":
            efa["Enabled"] = True
        if self.cluster_config_get("enable_efa_gdr") == "compute":
            efa["GdrSupport"] = True

        for item in [
            (compute_resource_section, "instance_type", compute_resource, "InstanceType"),
            (compute_resource_section, "min_count", compute_resource, "MinCount", "getint"),
            (compute_resource_section, "max_count", compute_resource, "MaxCount", "getint"),
            (compute_resource_section, "spot_price", compute_resource, "SpotPrice", "getfloat"),
            (
                queue_section,
                "disable_hyperthreading",
                compute_resource,
                "DisableSimultaneousMultithreading",
                "getboolean",
            ),
            (queue_section, "enable_efa", efa, "Enabled", "getboolean"),
            (queue_section, "enable_efa_gdr", efa, "GdrSupport", "getboolean"),
        ]:
            self.convert_single_field(*item)
        if self.config_parser.getboolean(queue_section, "disable_hyperthreading", fallback=None) is None:
            self.convert_disable_hyperthreading(compute_resource)

        _add_if(compute_resource, "Efa", efa)
        return compute_resource

    def convert_sit_queue(self, scheduling, param):
        """Convert Slurm SIT queue."""
        slurm_queues = []
        queue = dict()
        queue["Name"] = "default-queue"
        self.convert_slurm_compute_settings(queue)
        self.convert_single_field(self.cluster_section_name, "cluster_type", queue, "CapacityType")
        if "CapacityType" in queue:
            queue["CapacityType"] = queue["CapacityType"].upper()
        self.convert_custom_action(queue)
        self.covert_headnode_iam(queue)
        self.convert_slurm_queue_networking(queue, self.cluster_section_name)
        self.convert_slurm_sit_compute_resources(queue)
        _append_if(slurm_queues, queue)
        _add_if(scheduling, param, slurm_queues)

    def convert_slurm_sit_compute_resources(self, queue):
        """Comvert ComputeResources of Slurm single queue."""
        compute_resources = []
        compute_resource = dict()
        efa = dict()
        compute_resource["Name"] = "default-resource"
        for item in [
            (self.cluster_section_name, "spot_price", compute_resource, "SpotPrice", "getfloat"),
            (self.cluster_section_name, "max_queue_size", compute_resource, "MaxCount", "getint"),
            (
                self.cluster_section_name,
                "disable_hyperthreading",
                compute_resource,
                "DisableSimultaneousMultithreading",
                "getboolean",
            ),
        ]:
            self.convert_single_field(*item)
        initial_queue_size = self.config_parser.getint(self.cluster_section_name, "initial_queue_size", fallback=None)
        maintain_initial_size = self.config_parser.getboolean(
            self.cluster_section_name, "maintain_initial_size", fallback=None
        )
        if initial_queue_size and maintain_initial_size:
            compute_resource["MinCount"] = initial_queue_size
        else:
            self.validate_single_field(self.cluster_section_name, "initial_queue_size", "ignored")
        self.convert_instance_type(compute_resource, "compute_instance_type")

        if self.cluster_config_get("enable_efa") == "compute":
            efa["Enabled"] = True
        if self.cluster_config_get("enable_efa_gdr") == "compute":
            efa["GdrSupport"] = True
        _add_if(compute_resource, "Efa", efa)
        _append_if(compute_resources, compute_resource)
        _add_if(queue, "ComputeResources", compute_resources)

    def validate_duplicate_names(self, label):
        """Validate whether there are duplicate names in SharedStorage."""
        if label in self.convert_shared_storage_name:
            message = (
                f"Duplicate names '{label}' are not allowed in the SharedStorage section. Please change them "
                "before cluster creation."
            )
            _warn(message)
            self.comments += f"# {message}\n"
        else:
            self.convert_shared_storage_name.append(label)

    def validate_shared_storages_name(self):
        """Validate if storage names are adapted to PCluster3 validations."""
        settings = {"ebs_settings": "ebs", "fsx_settings": "fsx", "raid_settings": "raid"}
        for setting, section in settings.items():
            setting = self.cluster_config_get(setting)
            if setting:
                for label in setting.split(","):
                    name = label.strip()
                    self.validate_duplicate_names(name)
                    self.validate_default_name(name, f"{section} {name}")

    def validate_slurm_queues(self):
        """Validate if Slurm queues are adapted to PCluster3 validations."""
        if self.cluster_config_get("scheduler") == "slurm":
            queue_settings = self.cluster_config_get("queue_settings")
            if not queue_settings:
                return
            for queue_label in queue_settings.split(","):
                queue_name = queue_label.strip()
                queue_section = f"queue {queue_name}"
                self.validate_default_name(queue_name, queue_section)
                self.validate_underscore_in_name(queue_name, queue_section)
                compute_resource_settings = self.config_parser.get(
                    queue_section, "compute_resource_settings", fallback=None
                )
                if not compute_resource_settings:
                    return
                for compute_resource_label in compute_resource_settings.split(","):
                    compute_resource_name = compute_resource_label.strip()
                    compute_resource_section = f"compute_resource {compute_resource_name}"
                    self.validate_default_name(compute_resource_name, compute_resource_section)
                    self.validate_underscore_in_name(compute_resource_name, compute_resource_section)
                    self.validate_single_field(compute_resource_section, "initial_count", "ignored")

    def validate_default_ebs(self):
        """Validate the existence of ebs_settings in pcluster2 config."""
        if not self.cluster_config_get("ebs_settings"):
            message = (
                "The default setup of AWS ParallelCluster version 2 uses an EBS volume to share the /shared directory "
                "over NFS. This configuration utility preserves this behavior by default. If you do not need the "
                "/shared directory, you can remove the default-ebs from the SharedStorage section of your "
                "configuration."
            )
            _note(message)
            self.comments += f"# {message}\n"


def _parse_args(argv=None):
    """Parse command line args."""
    convert_parser = argparse.ArgumentParser(
        description="Convert AWS ParallelCluster configuration file.",
    )
    convert_parser.add_argument(
        "-c",
        "--config-file",
        help="Configuration file to be used as input.",
        required=True,
    )
    convert_parser.add_argument(
        "-t",
        "--cluster-template",
        help=(
            "Indicates the 'cluster' section of the configuration file to convert. "
            "If not specified the script will look for the cluster_template parameter in the [global] section "
            "or will search for '[cluster default]'."
        ),
        required=False,
    )
    convert_parser.add_argument(
        "-o",
        "--output-file",
        help="Configuration file to be written as output. By default the output will be written to stdout.",
        required=False,
    )
    convert_parser.add_argument(
        "--force-convert",
        help="Convert parameters that are not officially supported and not recommended.",
        required=False,
        action="store_true",
    )
    convert_parser.set_defaults(func=convert)

    return convert_parser.parse_args(argv)


def convert(args=None):
    try:
        converter = Pcluster3ConfigConverter(
            args.config_file, args.cluster_template, args.output_file, None, args.force_convert
        )
        converter.validate()
        converter.convert_to_pcluster3_config()
        converter.write_configuration_file()
    except KeyboardInterrupt:
        print("Exiting...")
        sys.exit(1)
    except Exception as e:
        print("Unexpected error of type %s: %s", type(e).__name__, e)
        sys.exit(1)


def main(argv=None):
    args = _parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
