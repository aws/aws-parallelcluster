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
import string
import zipfile
from collections import defaultdict

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


def get_ad_config_param_vals(directory_stack_name, nlb_stack_name, password_secret_arn):
    """Return a dict used to set values for config file parameters."""
    directory_stack_outputs = get_infra_stack_outputs(directory_stack_name)
    nlb_stack_outputs = get_infra_stack_outputs(nlb_stack_name)
    ldap_search_base = ",".join(
        [f"dc={domain_component}" for domain_component in directory_stack_outputs.get("DomainName").split(".")]
    )
    read_only_username = directory_stack_outputs.get("ReadOnlyUserName")
    return {
        "ldaps_uri": nlb_stack_outputs.get("LDAPSURL"),
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


def _create_directory_stack(cfn_stacks_factory, request, directory_type, test_resources_dir, region, vpc_stack):
    directory_stack_name = generate_stack_name(
        f"integ-tests-MultiUserInfraStack{directory_type}", request.config.getoption("stackname_suffix")
    )

    if directory_type not in ("MicrosoftAD", "SimpleAD"):
        raise Exception(f"Unknown directory type: {directory_type}")

    directory_stack_template_path = os_lib.path.join(test_resources_dir, "ad_stack.yaml")
    account_id = (
        boto3.client("sts", region_name=region, endpoint_url=get_sts_endpoint(region))
        .get_caller_identity()
        .get("Account")
    )
    ad_admin_password = "".join(random.choices(string.ascii_letters + string.digits, k=60))
    ad_user_password = "".join(random.choices(string.ascii_letters + string.digits, k=60))
    config_args = {
        "region": region,
        "account": account_id,
        "admin_node_ami_id": retrieve_latest_ami(region, "alinux2"),
        "admin_node_instance_type": "c5.large",
        "admin_node_key_name": request.config.getoption("key_name"),
        "ad_admin_password": ad_admin_password,
        "ad_user_password": ad_user_password,
        "ad_domain_name": f"{directory_type.lower()}.multiuser.pcluster",
        "default_ec2_domain": "ec2.internal" if region == "us-east-1" else f"{region}.compute.internal",
        "ad_admin_user": "Administrator" if directory_type == "SimpleAD" else "Admin",
        "num_users_to_create": 100,
        "directory_type": directory_type,
    }
    logging.info("Creating stack %s", directory_stack_name)
    with open(render_jinja_template(directory_stack_template_path, **config_args)) as directory_stack_template:
        params = [
            {"ParameterKey": "Vpc", "ParameterValue": vpc_stack.cfn_outputs["VpcId"]},
            {"ParameterKey": "PrivateSubnetOne", "ParameterValue": vpc_stack.cfn_outputs["PrivateSubnetId"]},
            {
                "ParameterKey": "PrivateSubnetTwo",
                "ParameterValue": vpc_stack.cfn_outputs["PrivateAdditionalCidrSubnetId"],
            },
            {"ParameterKey": "PublicSubnetOne", "ParameterValue": vpc_stack.cfn_outputs["PublicSubnetId"]},
        ]
        directory_stack = CfnStack(
            name=directory_stack_name,
            region=region,
            template=directory_stack_template.read(),
            parameters=params,
            capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"],
        )
    cfn_stacks_factory.create_stack(directory_stack)
    logging.info("Creation of stack %s complete", directory_stack_name)
    return directory_stack


@retry(wait_fixed=seconds(20), stop_max_delay=seconds(700))
def _check_ssm_success(ssm_client, command_id, instance_id):
    assert_that(
        ssm_client.get_command_invocation(CommandId=command_id, InstanceId=instance_id)["Status"] == "Success"
    ).is_true()


def _populate_directory_with_users(directory_stack, num_users_to_create, region):
    logging.info("Creating %s users in directory service", str(num_users_to_create))
    ssm_client = boto3.client("ssm", region_name=region)
    document_name = directory_stack.cfn_resources["UserAddingDocument"]
    admin_node_instance_id = directory_stack.cfn_resources["AdDomainAdminNode"]
    directory_id = directory_stack.cfn_resources["Directory"]
    command_id = ssm_client.send_command(
        DocumentName=document_name,
        InstanceIds=[directory_stack.cfn_resources["AdDomainAdminNode"]],
        MaxErrors="0",
        TimeoutSeconds=600,
        Parameters={"DirectoryId": [directory_id], "NumUsersToCreate": [str(num_users_to_create)]},
    )["Command"]["CommandId"]
    _check_ssm_success(ssm_client, command_id, admin_node_instance_id)
    logging.info("Creation of %s users in directory service completed", str(num_users_to_create))


def _create_nlb_stack(cfn_stacks_factory, request, directory_stack, region, test_resources_dir):
    nlb_stack_template_path = os_lib.path.join(test_resources_dir, "NLB_SimpleAD.yaml")
    nlb_stack_name = generate_stack_name(
        "integ-tests-MultiUserInfraStackNLB", request.config.getoption("stackname_suffix")
    )
    logging.info("Creating stack %s", nlb_stack_name)
    # TODO: don't hardcode this ARN
    certificate_arn = "arn:aws:acm:us-east-1:447714826191:certificate/a17e8574-0cea-4d4c-8e79-a8ebb60f6f47"
    nlb_stack = None
    with open(nlb_stack_template_path) as nlb_stack_template:
        nlb_stack = CfnStack(
            name=nlb_stack_name,
            region=region,
            template=nlb_stack_template.read(),
            parameters=[
                {
                    "ParameterKey": "LDAPSCertificateARN",
                    "ParameterValue": certificate_arn,
                },
                {
                    "ParameterKey": "VPCId",
                    "ParameterValue": directory_stack.cfn_outputs["VpcId"],
                },
                {
                    "ParameterKey": "SubnetId1",
                    "ParameterValue": directory_stack.cfn_outputs["PrivateSubnetIds"].split(",")[0],
                },
                {
                    "ParameterKey": "SubnetId2",
                    "ParameterValue": directory_stack.cfn_outputs["PrivateSubnetIds"].split(",")[1],
                },
                {
                    "ParameterKey": "SimpleADPriIP",
                    "ParameterValue": directory_stack.cfn_outputs["DirectoryDnsIpAddresses"].split(",")[0],
                },
                {
                    "ParameterKey": "SimpleADSecIP",
                    "ParameterValue": directory_stack.cfn_outputs["DirectoryDnsIpAddresses"].split(",")[1],
                },
            ],
        )
    cfn_stacks_factory.create_stack(nlb_stack)
    logging.info("Creation of NLB stack %s complete", nlb_stack_name)
    return nlb_stack


@pytest.fixture(scope="module")
def directory_factory(request, cfn_stacks_factory, vpc_stacks):
    # TODO: use external data file and file locking in order to share directories across processes
    created_directory_stacks = defaultdict(dict)

    def _directory_factory(
        existing_directory_stack_name, existing_nlb_stack_name, directory_type, test_resources_dir, region
    ):
        if existing_directory_stack_name:
            directory_stack_name = existing_directory_stack_name
            directory_stack = CfnStack(name=directory_stack_name, region=region, template=None)
            logging.info("Using pre-existing directory stack named %s", directory_stack_name)
        elif created_directory_stacks.get(region, {}).get("directory"):
            directory_stack_name = created_directory_stacks.get(region, {}).get("directory")
            directory_stack = CfnStack(name=directory_stack_name, region=region, template=None)
            logging.info("Using directory stack named %s created by another test", directory_stack_name)
        else:
            directory_stack = _create_directory_stack(
                cfn_stacks_factory, request, directory_type, test_resources_dir, region, vpc_stacks[region]
            )
            directory_stack_name = directory_stack.name
            created_directory_stacks[region]["directory"] = directory_stack_name
            _populate_directory_with_users(directory_stack, NUM_USERS_TO_CREATE, region)
        # Create NLB that will be used to enable LDAPS
        if existing_nlb_stack_name:
            nlb_stack_name = existing_nlb_stack_name
            logging.info("Using pre-existing NLB stack named %s", nlb_stack_name)
        elif created_directory_stacks.get(region, {}).get("nlb"):
            nlb_stack_name = created_directory_stacks.get(region, {}).get("nlb")
            logging.info("Using NLB stack named %s created by another test", nlb_stack_name)
        else:
            nlb_stack_name = _create_nlb_stack(
                cfn_stacks_factory, request, directory_stack, region, test_resources_dir
            ).name
            created_directory_stacks[region]["nlb"] = nlb_stack_name
        return directory_stack_name, nlb_stack_name

    yield _directory_factory

    for region, stack_dict in created_directory_stacks.items():
        for stack_type in ["nlb", "directory"]:
            stack_name = stack_dict[stack_type]
            if request.config.getoption("no_delete"):
                logging.info(
                    "Not deleting %s stack named %s in region %s because --no-delete option was specified",
                    stack_type,
                    stack_name,
                    region,
                )
            else:
                logging.info("Deleting %s stack named %s in region %s", stack_type, stack_name, region)
                cfn_stacks_factory.delete_stack(stack_name, region)


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
            # Specify that only owner of file should have read/write access.
            user.run_remote_command(f"chmod 600 {path}")
            # If the user is the first user, choose the last user as previous user
            logging.info("Check %s is not able to read files created by %s", previous_user.alias, user.alias)
            result = previous_user.run_remote_command(f"cat {path}", raise_on_error=False)
            _check_failed_result_for_permission_denied(result)


def _check_failed_result_for_permission_denied(result):
    assert_that(result.failed).is_true()
    assert_that(result.stdout).matches("Permission denied")


def _check_ssh_key_generation(user, scheduler_commands, generate_ssh_keys_for_user):
    # Remove user's home directory to ensure public SSH key doesn't exist
    user.cleanup()
    # Run remote command as user via password so that the feature has a chance to generate
    # SSH keys if their ~/.ssh directory doesn't exist (and the cluster is configured to do so).
    user.validate_password_auth_and_automatic_homedir_creation()
    # Copy user's SSH key to the head node to facilitate the validation to follow. Note that this
    # must be done after the above validation of home directory creation. If it's done before,
    # then the user's ~/.ssh directory will have already been created and thus a keypair won't be
    # generated regardless of the value of the GenerateSshKeysForUsers parameter in the cluster config.
    user.copy_public_ssh_key_to_authorized_keys()
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
    directory_type,
    test_datadir,
    s3_bucket_factory,
    directory_factory,
    request,
    store_secret_in_secret_manager,
    clusters_factory,
):
    """Verify AD integration works as expected."""
    compute_instance_type_info = {"name": "c5.xlarge", "num_cores": 4}
    config_params = {"compute_instance_type": compute_instance_type_info.get("name")}
    directory_stack_name, nlb_stack_name = directory_factory(
        request.config.getoption("directory_stack_name"),
        request.config.getoption("ldaps_nlb_stack_name"),
        directory_type,
        str(test_datadir),
        region,
    )
    directory_stack_outputs = get_infra_stack_outputs(directory_stack_name)
    ad_user_password = directory_stack_outputs.get("UserPassword")
    password_secret_arn = store_secret_in_secret_manager(directory_stack_outputs.get("AdminPassword"))
    config_params.update(get_ad_config_param_vals(directory_stack_name, nlb_stack_name, password_secret_arn))
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
        users.append(ClusterUser(user_num, test_datadir, cluster, scheduler, remote_command_executor, ad_user_password))
    _run_user_workloads(users, test_datadir, remote_command_executor)
    logging.info("Testing pcluster update and generate ssh keys for user")
    _check_ssh_key_generation(users[0], scheduler_commands, False)
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update.yaml", **config_params)
    cluster.update(str(updated_config_file), force_update="true")
    # Reset stateful connection variables after the cluster update
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    for user in users:
        user.reset_stateful_connection_objects(remote_command_executor)
    _check_ssh_key_generation(users[1], scheduler_commands, True)
