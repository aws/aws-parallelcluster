# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

import datetime
import io
import logging
import os as os_lib
import random
import re
import zipfile

import boto3
import pytest
from jinja2 import Environment, FileSystemLoader
from remote_command_executor import RemoteCommandExecutor

from tests.common.osu_common import run_osu_benchmarks
from tests.common.schedulers_common import get_scheduler_commands
from tests.common.utils import get_sts_endpoint, retrieve_latest_ami


def get_infra_stack_outputs(stack_name):
    cfn = boto3.client("cloudformation")
    return {
        entry.get("OutputKey"): entry.get("OutputValue")
        for entry in cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    }


def get_ad_config_param_vals(stack_name, bucket_name, post_install_script_name):
    """Return a dict used to set values for config file parameters."""
    infra_stack_outputs = get_infra_stack_outputs(stack_name)
    ldap_search_base = ",".join(
        [f"dc={domain_component}" for domain_component in infra_stack_outputs.get("DomainName").split(".")]
    )
    read_only_username = infra_stack_outputs.get("ReadOnlyUserName")
    return {
        "directory_subnet": random.choice(infra_stack_outputs.get("SubnetIds").split(",")),
        "post_install_script_uri": f"s3://{bucket_name}/{post_install_script_name}",
        "ldap_uri": infra_stack_outputs.get("LdapUris").split(",")[0],
        "ldap_search_base": ldap_search_base,
        # TODO: is the CN=Users portion of this a valid assumption?
        "ldap_default_bind_dn": f"CN={read_only_username},CN=Users,{ldap_search_base}",
        "ldap_client_password": infra_stack_outputs.get("Password"),
    }


# TODO: move this to a common place, since it's a copy of code from osu_common.py
def render_jinja_template(template_file_path, **kwargs):
    file_loader = FileSystemLoader(str(os_lib.path.dirname(template_file_path)))
    env = Environment(loader=file_loader)
    rendered_template = env.get_template(os_lib.path.basename(template_file_path)).render(**kwargs)
    logging.info("Writing the following to %s\n%s", template_file_path, rendered_template)
    with open(template_file_path, "w", encoding="utf-8") as f:
        f.write(rendered_template)
    return template_file_path


def _add_file_to_zip(zip_file, path, arcname):
    """
    Add the file at path under the name arcname to the archive represented by zip_file.

    :param zip_file: zipfile.ZipFile object
    :param path: string; path to file being added
    :param arcname: string; filename to put bytes from path under in created archive
    """
    with open(path, "rb") as input_file:
        zinfo = zipfile.ZipInfo(filename=arcname)
        zinfo.external_attr = 0o644 << 16
        zip_file.writestr(zinfo, input_file.read())


def zip_dir(path):
    """
    Create a zip archive containing all files and dirs rooted in path.

    The archive is created in memory and a file handler is returned by the function.
    :param path: directory containing the resources to archive.
    :return file handler pointing to the compressed archive.
    """
    file_out = io.BytesIO()
    with zipfile.ZipFile(file_out, "w", zipfile.ZIP_DEFLATED) as ziph:
        for root, _, files in os_lib.walk(path):
            for file in files:
                _add_file_to_zip(
                    ziph,
                    os_lib.path.join(root, file),
                    os_lib.path.relpath(os_lib.path.join(root, file), start=path),
                )
    file_out.seek(0)
    return file_out


def upload_custom_resources(test_resources_dir, bucket_name):
    """
    Upload custom resources to S3 bucket.

    :param test_resources_dir: resource directory containing the resources to upload.
    :bucket_name: bucket to upload resources to
    """
    for dirname in ("custom_resources_code", "codebuild_sources"):
        dirpath = os_lib.path.join(test_resources_dir, dirname)
        boto3.client("s3").upload_fileobj(
            Fileobj=zip_dir(dirpath),
            Bucket=bucket_name,
            Key=f"{dirname}/archive.zip",
        )


@pytest.fixture(scope="module")
def directory_factory(request):
    created_directory_stacks = []

    def _directory_factory(existing_stack_name, directory_type, bucket_name, test_resources_dir, region):
        if existing_stack_name:
            logging.info("Using pre-existing directory stack named %s", existing_stack_name)
            return existing_stack_name

        if directory_type not in ("MicrosoftAD", "SimpleAD"):
            raise Exception(f"Unknown directory type: {directory_type}")

        upload_custom_resources(test_resources_dir, bucket_name)
        template_path = os_lib.path.join(test_resources_dir, f"{directory_type}_stack.yaml")
        account_id = (
            boto3.client("sts", region_name=region, endpoint_url=get_sts_endpoint(region))
            .get_caller_identity()
            .get("Account")
        )
        config_args = {
            "region": region,
            "account": account_id,
            "admin_node_ami_id": retrieve_latest_ami(region, "alinux2"),
            "admin_node_instance_type": "c5.large",
            "admin_node_key_name": request.config.getoption("key_name"),
            "ad_admin_password": "MultiUserInfraDirectoryReadOnlyPassword!",  # TODO: not secure
            "ad_domain_name": f"{directory_type.lower()}.multiuser.pcluster",
            "default_ec2_domain": "ec2.internal" if region == "us-east-1" else f"{region}.compute.internal",
            "ad_admin_user": "Administrator" if directory_type == "SimpleAD" else "Admin",
            "num_users_to_create": 100,
            "bucket_name": bucket_name,
            "directory_type": directory_type,
        }
        stack_name = f"MultiUserInfraStack{directory_type}"
        cfn_client = boto3.client("cloudformation")
        logging.info("Creating stack %s", stack_name)
        with open(render_jinja_template(template_path, **config_args)) as template:
            cfn_client.create_stack(
                StackName=stack_name,
                TemplateBody=template.read(),
                Capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"],
                OnFailure="DO_NOTHING",
            )
        logging.info("Waiting for creation of stack %s to complete", stack_name)
        waiter = cfn_client.get_waiter("stack_create_complete")
        waiter.wait(StackName=stack_name)
        logging.info("Creation of stack %s complete", stack_name)
        created_directory_stacks.append(stack_name)
        return stack_name

    yield _directory_factory

    for directory_stack in created_directory_stacks:
        if request.config.getoption("no_delete"):
            logging.info("Not deleting stack %s because --no-delete option was specified", directory_stack)
        else:
            logging.info("Deleting stack %s", directory_stack)
            boto3.client("cloudformation").delete_stack(StackName=directory_stack)


# @pytest.mark.parametrize("directory_type", ["SimpleAD", "MicrosoftAD", None])
# @pytest.mark.parametrize("directory_type", ["MicrosoftAD"])
@pytest.mark.parametrize("directory_type", ["SimpleAD"])
# @pytest.mark.parametrize("directory_type", [None])
def test_ad_integration(
    region,
    scheduler,
    instance,
    os,
    pcluster_config_reader,
    clusters_factory,
    directory_type,
    test_datadir,
    s3_bucket_factory,
    directory_factory,
    request,
):
    """Verify AD integration works as expected."""
    compute_instance_type_info = {"name": "c5.xlarge", "num_cores": 4}
    config_params = {"compute_instance_type": compute_instance_type_info.get("name")}
    if directory_type:
        post_install_script_name = "all-nodes-ldap.sh"
        bucket_name = s3_bucket_factory()
        directory_stack_name = directory_factory(
            request.config.getoption("directory_stack_name"), directory_type, bucket_name, str(test_datadir), region
        )
        config_params.update(get_ad_config_param_vals(directory_stack_name, bucket_name, post_install_script_name))
        bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
        bucket.upload_file(str(test_datadir / post_install_script_name), post_install_script_name)
    cluster_config = pcluster_config_reader(**config_params)
    cluster = clusters_factory(cluster_config)

    # Publish compute node count metric every minute via cron job
    # TODO: use metrics reporter from the benchmarks module
    remote_command_executor = RemoteCommandExecutor(cluster)
    metric_publisher_script = "publish_compute_node_count_metric.sh"
    remote_metric_publisher_script_path = f"/shared/{metric_publisher_script}"
    crontab_expression = f"* * * * * {remote_metric_publisher_script_path} &> {remote_metric_publisher_script_path}.log"
    remote_command_executor.run_remote_command(
        f"echo '{crontab_expression}' | crontab -",
        additional_files={str(test_datadir / metric_publisher_script): remote_metric_publisher_script_path},
    )

    # Run all-to-all benchmark across increasingly large number of nodes.
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    cloudwatch_client = boto3.client("cloudwatch")
    for benchmark_name in [
        "osu_allgather",
        "osu_allreduce",
        "osu_alltoall",
        "osu_barrier",
        "osu_bcast",
        "osu_gather",
        "osu_reduce",
        "osu_reduce_scatter",
        "osu_scatter",
    ]:
        common_metric_dimensions = {
            "MpiFlavor": "openmpi",
            "BenchmarkGroup": "collective",
            "BenchmarkName": benchmark_name,
            "HeadNodeInstanceType": instance,
            "ComputeInstanceType": compute_instance_type_info.get("name"),
            "ProcessesPerNode": 1,
            "Os": os,
            "DirectoryType": directory_type,
        }
        metric_publishing_timestamp = datetime.datetime.now()
        for num_nodes in [100, 250, 500, 1000, 2000]:
            metric_data = []
            output = run_osu_benchmarks(
                mpi_version=common_metric_dimensions.get("MpiFlavor"),
                benchmark_group=common_metric_dimensions.get("BenchmarkGroup"),
                benchmark_name=common_metric_dimensions.get("BenchmarkName"),
                partition=None,
                remote_command_executor=remote_command_executor,
                scheduler_commands=scheduler_commands,
                num_of_instances=num_nodes,
                slots_per_instance=common_metric_dimensions.get("ProcessesPerNode"),
                test_datadir=test_datadir,
                timeout=120,
            )
            for packet_size, latency in re.findall(r"(\d+)\s+(\d+)\.", output):
                dimensions = {**common_metric_dimensions, "NumNodes": num_nodes, "PacketSize": packet_size}
                metric_data.append(
                    {
                        "MetricName": "Latency",
                        "Dimensions": [{"Name": name, "Value": str(value)} for name, value in dimensions.items()],
                        "Value": int(latency),
                        "Timestamp": metric_publishing_timestamp,
                        "Unit": "Microseconds",
                    }
                )
            cloudwatch_client.put_metric_data(Namespace="ParallelCluster/AdIntegration", MetricData=metric_data)
