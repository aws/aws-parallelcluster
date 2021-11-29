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
from assertpy import assert_that
from cfn_stacks_factory import CfnStack
from jinja2 import Environment, FileSystemLoader
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import seconds
from troposphere import Template
from troposphere.secretsmanager import Secret
from utils import generate_stack_name

from tests.ad_integration.cluster_user import ClusterUser
from tests.common.osu_common import compile_osu, run_osu_benchmarks
from tests.common.schedulers_common import get_scheduler_commands
from tests.common.utils import get_sts_endpoint, retrieve_latest_ami

NUM_USERS_TO_CREATE = 100
NUM_USERS_TO_TEST = 10


def get_infra_stack_outputs(stack_name):
    cfn = boto3.client("cloudformation")
    return {
        entry.get("OutputKey"): entry.get("OutputValue")
        for entry in cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    }


def get_ad_config_param_vals(stack_name, bucket_name, password_secret_arn):
    """Return a dict used to set values for config file parameters."""
    infra_stack_outputs = get_infra_stack_outputs(stack_name)
    ldap_search_base = ",".join(
        [f"dc={domain_component}" for domain_component in infra_stack_outputs.get("DomainName").split(".")]
    )
    read_only_username = infra_stack_outputs.get("ReadOnlyUserName")
    return {
        "directory_subnet": random.choice(infra_stack_outputs.get("SubnetIds").split(",")),
        "ldap_uri": infra_stack_outputs.get("LdapUris").split(",")[0],
        "ldap_search_base": ldap_search_base,
        # TODO: is the CN=Users portion of this a valid assumption?
        "ldap_default_bind_dn": f"CN={read_only_username},CN=Users,{ldap_search_base}",
        "password_secret_arn": password_secret_arn,
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


@pytest.fixture(scope="class")
def store_secret_in_secret_manager(request, region, cfn_stacks_factory):

    secret_stack_name = generate_stack_name("integ-tests-secret", request.config.getoption("stackname_suffix"))

    def _store_secret(secret):
        template = Template()
        template.set_version("2010-09-09")
        template.set_description("stack to store a secret string")
        template.add_resource(Secret("Secret", SecretString=secret))
        stack = CfnStack(
            name=secret_stack_name,
            region=region,
            template=template.to_json(),
        )
        cfn_stacks_factory.create_stack(stack)
        return stack.cfn_resources["Secret"]

    yield _store_secret

    if request.config.getoption("no_delete"):
        logging.info("Not deleting stack %s because --no-delete option was specified", secret_stack_name)
    else:
        logging.info("Deleting stack %s", secret_stack_name)
        cfn_stacks_factory.delete_stack(secret_stack_name, region)


@pytest.fixture(scope="module")
def directory_factory(request, cfn_stacks_factory):
    created_directory_stacks = {}

    @retry(wait_fixed=seconds(20), stop_max_delay=seconds(700))
    def _check_ssm_success(ssm_client, command_id, instance_id):
        assert_that(
            ssm_client.get_command_invocation(CommandId=command_id, InstanceId=instance_id)["Status"] == "Success"
        ).is_true()

    def _directory_factory(
        existing_stack_name, directory_type, bucket_name, test_resources_dir, region, ad_admin_password
    ):
        if existing_stack_name:
            logging.info("Using pre-existing directory stack named %s", existing_stack_name)
            return existing_stack_name
        created_directory_stack_in_region = created_directory_stacks.get(region)
        if created_directory_stack_in_region:
            logging.info("Using directory stack named %s created by another test", created_directory_stack_in_region)
            return created_directory_stack_in_region

        if directory_type not in ("MicrosoftAD", "SimpleAD"):
            raise Exception(f"Unknown directory type: {directory_type}")

        upload_custom_resources(test_resources_dir, bucket_name)
        template_path = os_lib.path.join(test_resources_dir, "ad_stack.yaml")
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
            "ad_admin_password": ad_admin_password,
            "ad_domain_name": f"{directory_type.lower()}.multiuser.pcluster",
            "default_ec2_domain": "ec2.internal" if region == "us-east-1" else f"{region}.compute.internal",
            "ad_admin_user": "Administrator" if directory_type == "SimpleAD" else "Admin",
            "num_users_to_create": 100,
            "bucket_name": bucket_name,
            "directory_type": directory_type,
        }
        stack_name = generate_stack_name(
            f"integ-tests-MultiUserInfraStack{directory_type}", request.config.getoption("stackname_suffix")
        )
        logging.info("Creating stack %s", stack_name)
        with open(render_jinja_template(template_path, **config_args)) as template:
            stack = CfnStack(
                name=stack_name,
                region=region,
                template=template.read(),
                capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"],
            )
        cfn_stacks_factory.create_stack(stack)
        logging.info("Creation of stack %s complete", stack_name)
        created_directory_stacks[region] = stack_name
        logging.info("Creating %s users in directory service", str(NUM_USERS_TO_CREATE))
        ssm_client = boto3.client("ssm", region_name=region)
        document_name = stack.cfn_resources["MultiUserInfraUserAddingDocument"]
        admin_node_instance_id = stack.cfn_resources["MultiUserInfraAdDomainAdminNode"]
        directory_id = stack.cfn_resources["MultiUserInfraDirectory"]
        command_id = ssm_client.send_command(
            DocumentName=document_name,
            InstanceIds=[stack.cfn_resources["MultiUserInfraAdDomainAdminNode"]],
            MaxErrors="0",
            TimeoutSeconds=600,
            Parameters={"DirectoryId": [directory_id], "NumUsersToCreate": [str(NUM_USERS_TO_CREATE)]},
        )["Command"]["CommandId"]
        _check_ssm_success(ssm_client, command_id, admin_node_instance_id)
        logging.info("Creation of %s users in directory service completed", str(NUM_USERS_TO_CREATE))
        return stack_name

    yield _directory_factory

    for directory_stack in created_directory_stacks.values():
        if request.config.getoption("no_delete"):
            logging.info("Not deleting stack %s because --no-delete option was specified", directory_stack)
        else:
            logging.info("Deleting stack %s", directory_stack)
            boto3.client("cloudformation").delete_stack(StackName=directory_stack)


@pytest.fixture(scope="module")
def user_factory():
    created_users = []

    def _user_creator(user_num, test_datadir, cluster, scheduler, remote_command_executor):
        user = ClusterUser(user_num, test_datadir, cluster, scheduler, remote_command_executor)
        created_users.append(user)
        return user

    yield _user_creator

    for user in created_users:
        user.cleanup()


def _run_user_workloads(users, test_datadir, remote_command_executor):
    compile_osu("openmpi", remote_command_executor)
    _check_files_permissions(users)
    job_submission_outputs = [
        # TODO: render script from template to dynamically provide path to benchmarks and other paramters
        user.submit_script(str(test_datadir / "workload.sh"), nodes=2, slots=2).stdout
        for user in users
    ]
    job_ids = [
        user.assert_job_submitted(job_submission_output)
        for user, job_submission_output in zip(users, job_submission_outputs)
    ]
    for user, job_id in zip(users, job_ids):
        user.wait_job_completed(job_id)
        user.assert_job_succeeded(job_id)


def _check_files_permissions(users):
    logging.info("Checking file permissions")
    for index, user in enumerate(users):
        logging.info("Checking permission of sssd.conf file from user %s", user.alias)
        result = user.run_remote_command(
            "cat /opt/parallelcluster/shared/directory_service/sssd.conf", raise_on_error=False
        )
        _check_failed_result_for_permission_denied(result)
        result = user.run_remote_command("cat /etc/sssd/sssd.conf", raise_on_error=False)
        _check_failed_result_for_permission_denied(result)
        previous_user = users[index - 1]
        for path in [
            f"/home/{user.alias}/my_file",
            f"/shared/{user.alias}_file",
            f"/ebs/{user.alias}_file",
            f"/efs/{user.alias}_file",
        ]:
            user.run_remote_command(f"touch {path}")
            if not path.startswith(f"/home/{user.alias}/"):
                # Files under homedir is only readable by the owner by default.
                # Otherwise, change the permission to 600 for the test.
                user.run_remote_command(f"chmod 600 {path}")
            # If the user is the first user, choose the last user as previous user
            logging.info("Check %s is not able to read files created by %s", previous_user.alias, user.alias)
            result = previous_user.run_remote_command(f"cat {path}", raise_on_error=False)
            _check_failed_result_for_permission_denied(result)


def _check_failed_result_for_permission_denied(result):
    assert_that(result.failed).is_true()
    assert_that(result.stdout).matches("Permission denied")


def _check_ssh_key_generation(user, scheduler_commands, generate_ssh_keys_for_user):
    result = user.run_remote_command("cat ~/.ssh/id_rsa", raise_on_error=generate_ssh_keys_for_user)
    if not generate_ssh_keys_for_user:
        assert_that(result.failed).is_true()
    else:
        compute_nodes = scheduler_commands.get_compute_nodes()
        static_compute_node = None
        for node in compute_nodes:
            if "-st" in node:
                static_compute_node = node
                break
        user.run_remote_command(f"ssh {static_compute_node} hostname")


def _run_benchmarks(
    os, instance, compute_instance_type_info, directory_type, remote_command_executor, scheduler_commands, test_datadir
):
    """Run benchmarks across increasingly large number of nodes."""
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
        for num_nodes in [20, 50]:
            # ToDo: Test 100, 250, 500, 1000, 2000 nodes in a benchmark test
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
    user_factory,
    request,
    store_secret_in_secret_manager,
):
    """Verify AD integration works as expected."""
    compute_instance_type_info = {"name": "c5.xlarge", "num_cores": 4}
    config_params = {"compute_instance_type": compute_instance_type_info.get("name")}
    ad_admin_password = "MultiUserInfraDirectoryReadOnlyPassword!"  # TODO: not secure
    password_secret_arn = store_secret_in_secret_manager(ad_admin_password)
    if directory_type:
        bucket_name = s3_bucket_factory()
        directory_stack_name = directory_factory(
            request.config.getoption("directory_stack_name"),
            directory_type,
            bucket_name,
            str(test_datadir),
            region,
            ad_admin_password=ad_admin_password,
        )
        config_params.update(get_ad_config_param_vals(directory_stack_name, bucket_name, password_secret_arn))
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

    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    assert_that(NUM_USERS_TO_TEST).is_less_than_or_equal_to(NUM_USERS_TO_CREATE)
    users = []
    for user_num in range(1, NUM_USERS_TO_TEST + 1):
        users.append(user_factory(user_num, test_datadir, cluster, scheduler, remote_command_executor))
    _run_user_workloads(users, test_datadir, remote_command_executor)
    logging.info("Testing pcluster update and generate ssh keys for user")
    _check_ssh_key_generation(users[0], scheduler_commands, False)
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update.yaml", **config_params)
    cluster.update(str(updated_config_file), force_update="true")
    _check_ssh_key_generation(users[1], scheduler_commands, True)
    _run_benchmarks(
        os,
        instance,
        compute_instance_type_info,
        directory_type,
        remote_command_executor,
        scheduler_commands,
        test_datadir,
    )
