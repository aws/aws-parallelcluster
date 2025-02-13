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

import io
import logging
import os as os_lib
import random
import string
import time
import zipfile
from collections import defaultdict

import boto3
import pytest
from assertpy import assert_that
from cfn_stacks_factory import CfnStack, CfnVpcStack
from paramiko import Ed25519Key
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import seconds
from utils import find_stack_by_tag, generate_stack_name, is_directory_supported, random_alphanumeric

from tests.ad_integration.cluster_user import ClusterUser
from tests.common.utils import run_system_analyzer

NUM_USERS_TO_CREATE = 5
NUM_USERS_TO_TEST = 3


def get_infra_stack_outputs(stack_name):
    cfn = boto3.client("cloudformation")
    return {
        entry.get("OutputKey"): entry.get("OutputValue")
        for entry in cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    }


def get_user_password(secret_arn):
    client = boto3.client("secretsmanager")
    return client.get_secret_value(SecretId=secret_arn)["SecretString"]


def get_vpc_public_subnet(vpc_id):
    ec2 = boto3.client("ec2")
    for entry in ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Subnets"]:
        if entry.get("MapPublicIpOnLaunch"):
            return {"public_subnet_id": entry.get("SubnetId")}
    return None


def get_infra_stack_parameters(stack_name):
    cfn = boto3.client("cloudformation")
    return {
        entry.get("ParameterKey"): entry.get("ParameterValue")
        for entry in cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Parameters"]
    }


def _get_ldap_base_search(domain_name):
    return ",".join([f"dc={domain_component}" for domain_component in domain_name.split(".")])


def get_ad_config_param_vals(
    directory_stack_outputs,
    ldap_tls_ca_cert,
    directory_type,
    directory_protocol,
    directory_certificate_verification,
):
    """Return a dict used to set values for config file parameters."""
    if directory_type not in ("MicrosoftAD", "SimpleAD"):
        raise Exception(f"Unknown directory type: {directory_type}")

    if directory_protocol == "ldaps":
        ldap_uri = directory_stack_outputs.get("DomainAddrLdaps")
    elif directory_protocol == "ldap":
        ldap_uri = directory_stack_outputs.get("DomainAddrLdap")
    else:
        raise Exception(f"Unknown directory protocol: {directory_protocol}")
    return {
        "ldap_uri": ldap_uri,
        "domain_name": directory_stack_outputs.get("DomainName"),
        "domain_read_only_user": directory_stack_outputs.get("DomainReadOnlyUser"),
        "password_secret_arn": directory_stack_outputs.get("PasswordSecretArn"),
        "ldap_tls_ca_cert": ldap_tls_ca_cert,
        "directory_protocol": directory_protocol,
        "ldap_tls_req_cert": "never" if directory_certificate_verification is False else "hard",
        "private_subnet_id": directory_stack_outputs.get("PrivateSubnetIds").split(",")[0],
    }


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


def add_tag_to_stack(stack_name, key, value):
    cfn = boto3.resource("cloudformation")
    stack = cfn.Stack(stack_name)
    add_tag = True
    for tag in stack.tags:
        if tag.get("Key") == "DO-NOT-DELETE":
            add_tag = False
            break
    if add_tag:
        stack.update(
            UsePreviousTemplate=True,
            Capabilities=["CAPABILITY_IAM"],
            Tags=[
                {"Key": key, "Value": value},
            ],
        )


def zip_dir(path):
    """
    Create a zip archive containing all files and dirs rooted in path.

    The archive is created in memory and a file handler is returned by the function.
    :param path: directory containing the resources to archive.
    :return: file handler pointing to the compressed archive.
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


def _get_stack_parameters(directory_type, vpc_stack, keypair):
    private_subnet = vpc_stack.get_private_subnet()
    private_subnets = vpc_stack.get_all_private_subnets().copy()
    private_subnets.remove(private_subnet)

    users = ""
    for i in range(NUM_USERS_TO_CREATE):
        users += f"PclusterUser{i},"

    stack_parameters = [
        {
            "ParameterKey": "DomainName",
            "ParameterValue": f"{directory_type.lower()}.{random_alphanumeric(size=10)}.multiuser.pcluster",
        },
        {
            "ParameterKey": "AdminPassword",
            "ParameterValue": "".join(random.choices(string.ascii_letters + string.digits, k=60)),
        },
        {
            "ParameterKey": "ReadOnlyPassword",
            "ParameterValue": "".join(random.choices(string.ascii_letters + string.digits, k=60)),
        },
        {"ParameterKey": "UserNames", "ParameterValue": users[:-1]},
        {
            "ParameterKey": "UserPassword",
            "ParameterValue": "".join(random.choices(string.ascii_letters + string.digits, k=60)),
        },
        {"ParameterKey": "DirectoryType", "ParameterValue": directory_type},
        {"ParameterKey": "Vpc", "ParameterValue": vpc_stack.cfn_outputs["VpcId"]},
        {"ParameterKey": "PrivateSubnetOne", "ParameterValue": private_subnet},
        {"ParameterKey": "PrivateSubnetTwo", "ParameterValue": private_subnets[0]},
        {"ParameterKey": "Keypair", "ParameterValue": keypair},
    ]
    return stack_parameters


def _create_directory_stack(cfn_stacks_factory, request, directory_type, region, vpc_stack: CfnVpcStack):
    directory_stack_name = generate_stack_name(
        f"integ-tests-MultiUserInfraStack{directory_type}", request.config.getoption("stackname_suffix")
    )

    if directory_type not in ("MicrosoftAD", "SimpleAD"):
        raise Exception(f"Unknown directory type: {directory_type}")

    directory_stack_template_path = "../../cloudformation/ad/ad-integration.yaml"

    logging.info("Creating stack %s", directory_stack_name)

    with open(directory_stack_template_path) as directory_stack_template:
        stack_parameters = _get_stack_parameters(directory_type, vpc_stack, request.config.getoption("key_name"))
        tags = [{"Key": "parallelcluster:integ-tests-ad-stack", "Value": directory_type}]
        if request.config.getoption("retain_ad_stack"):
            tags.append({"Key": "DO-NOT-DELETE", "Value": "Retained for integration testing"})

        directory_stack = CfnStack(
            name=directory_stack_name,
            region=region,
            template=directory_stack_template.read(),
            parameters=stack_parameters,
            capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
            tags=tags,
        )
    cfn_stacks_factory.create_stack(directory_stack)
    logging.info("Creation of stack %s complete", directory_stack_name)

    return directory_stack


@retry(wait_fixed=seconds(20), stop_max_delay=seconds(700))
def _check_ssm_success(ssm_client, command_id, instance_id):
    assert_that(
        ssm_client.get_command_invocation(CommandId=command_id, InstanceId=instance_id)["Status"] == "Success"
    ).is_true()


@pytest.fixture(scope="class")
def directory_factory(request, cfn_stacks_factory, vpc_stack):  # noqa: C901
    # TODO: use external data file and file locking in order to share directories across processes
    created_directory_stacks = defaultdict(dict)

    def _directory_factory(
        existing_directory_stack_name,
        directory_type,
        region,
    ):
        if existing_directory_stack_name:
            directory_stack_name = existing_directory_stack_name
            logging.info("Using pre-existing directory stack named %s", directory_stack_name)
        elif created_directory_stacks.get(region, {}).get("directory"):
            directory_stack_name = created_directory_stacks.get(region, {}).get("directory")
            logging.info("Using directory stack named %s created by another test", directory_stack_name)
        else:
            stack_prefix = f"integ-tests-MultiUserInfraStack{directory_type}"
            directory_stack_name = find_stack_by_tag("parallelcluster:integ-tests-ad-stack", region, stack_prefix)

            if not directory_stack_name:
                directory_stack = _create_directory_stack(
                    cfn_stacks_factory,
                    request,
                    directory_type,
                    region,
                    vpc_stack,
                )
                directory_stack_name = directory_stack.name
                created_directory_stacks[region]["directory"] = directory_stack_name
                if request.config.getoption("retain_ad_stack"):
                    add_tag_to_stack(vpc_stack.name, "DO-NOT-DELETE", "Retained for integration testing")
        return directory_stack_name

    yield _directory_factory

    for region, stack_dict in created_directory_stacks.items():
        for stack_type in stack_dict:
            stack_name = stack_dict[stack_type]
            if request.config.getoption("no_delete") or request.config.getoption("retain_ad_stack"):
                logging.info(
                    "Not deleting %s stack named %s in region %s because --no-delete option was specified",
                    stack_type,
                    stack_name,
                    region,
                )
            else:
                logging.info("Deleting %s stack named %s in region %s", stack_type, stack_name, region)
                cfn_stacks_factory.delete_stack(stack_name, region)


def _run_user_workloads(users, test_datadir, shared_storage_mount_dirs):
    _check_whoami(users)
    _check_files_permissions(users, shared_storage_mount_dirs)
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


def _check_whoami(users):
    logging.info("Checking whoami")
    for user in users:
        result = user.run_remote_command("whoami").stdout
        assert_that(result).is_equal_to(user.alias)
        result = user.run_remote_command("srun whoami").stdout
        assert_that(result).is_equal_to(user.alias)


def _check_files_permissions(users, shared_storage_mount_dirs):
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
        paths = [f"{user.home_dir}/my_file"]
        paths.extend(
            [f"{shared_storage_mount_dir}/{user.alias}_file" for shared_storage_mount_dir in shared_storage_mount_dirs]
        )
        for path in paths:
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


def _check_ssh_key_generation(user, remote_command_executor, scheduler_commands, generate_ssh_keys_for_user):
    # SSH login
    logging.info(
        "Checking SSH key generation for user %s on SSH login (expected generation: %s)",
        user.alias,
        generate_ssh_keys_for_user,
    )
    # Remove user's home directory to ensure public SSH key doesn't exist
    user.cleanup()
    user.ssh_connect()
    time.sleep(3)
    _check_home_directory(user, remote_command_executor)
    _check_ssh_key(user, generate_ssh_keys_for_user, remote_command_executor, scheduler_commands)
    logging.info(
        "Verified SSH key generation for user %s on SSH login (expected generation: %s)",
        user.alias,
        generate_ssh_keys_for_user,
    )

    ssh_key_path = f"{user.home_dir}/.ssh/id_ed25519"

    # Switch User - Interactive
    switch_user_commands = [
        f"sudo su {user.alias} --command='ls {ssh_key_path}'",
        f"sudo su - {user.alias} --command='ls {ssh_key_path}'",
        # TODO: Checks for below commands are failing, even if a manual check on the same cluster succeeds.
        # We need to double check these failures, but we can consider them as not blocking.
        # f"sudo -u {user.alias} ls {ssh_key_path}",
        # f"sudo -i -u {user.alias} ls {ssh_key_path}",
    ]

    for command in switch_user_commands:
        logging.info(
            "Checking SSH key generation for user %s on switch user (%s) (expected generation: %s)",
            user.alias,
            command,
            generate_ssh_keys_for_user,
        )
        user.cleanup()
        result = remote_command_executor.run_remote_command(command, raise_on_error=generate_ssh_keys_for_user)
        assert_that(result.failed).is_equal_to(not generate_ssh_keys_for_user)
        _check_home_directory(user, remote_command_executor)
        _check_ssh_key(user, generate_ssh_keys_for_user, remote_command_executor, scheduler_commands)
        logging.info(
            "Verified SSH key generation for user %s on switch user (%s) (expected generation: %s)",
            user.alias,
            command,
            generate_ssh_keys_for_user,
        )


def _check_home_directory(user, remote_command_executor):
    """
    This check verifies that:
    1. The user home directory exists;
    2. The user home directory has the right permissions.
    """
    logging.info("Checking home directory for user %s", user.alias)

    # Reset underlying ssh connection to prevent occasional `file not found` issues
    remote_command_executor.reset_connection()
    check_existence = f"sudo ls {user.home_dir}"
    result = remote_command_executor.run_remote_command(check_existence)
    assert_that(result.failed).is_false()

    check_ownership = f"sudo stat -c '%U' {user.home_dir}"
    result = remote_command_executor.run_remote_command(check_ownership)
    assert_that(result.failed).is_false()
    assert_that(result.stdout.strip()).is_equal_to(user.alias)
    logging.info("Verified home directory for user %s", user.alias)


def _check_ssh_key(user, ssh_generation_enabled, remote_command_executor, scheduler_commands):
    """
    This check verifies that:
    1. The SSH key exists [does not exist] for the user, if SSH key generation is enabled [disabled];
    2. The SSH key has the right permission, if it exists;
    3. The SSH key can be used to log in to the head node;
    4. The SSH key can be used to log in to a compute node.
    """
    logging.info("Checking SSH key for user %s (expected to exist: %s)", user.alias, ssh_generation_enabled)

    ssh_key_path = f"{user.home_dir}/.ssh/id_ed25519"

    # Reset underlying ssh connection to prevent occasional `file not found` issues
    remote_command_executor.reset_connection()

    # Check existence
    check_existence = f"sudo ls {ssh_key_path}"
    result = remote_command_executor.run_remote_command(check_existence, raise_on_error=ssh_generation_enabled)
    assert_that(result.failed).is_equal_to(not ssh_generation_enabled)

    logging.info(
        "Verified existence of SSH key for user %s (expected to exist: %s)",
        user.alias,
        ssh_generation_enabled,
    )

    if ssh_generation_enabled:
        # Check permissions
        logging.info(
            "Checking SSH key permissions for user %s (expected to exist: %s)",
            user.alias,
            ssh_generation_enabled,
        )
        check_permissions = f"sudo stat -c '%U %a' {ssh_key_path}"
        result = remote_command_executor.run_remote_command(check_permissions)
        assert_that(result.failed).is_false()
        assert_that(result.stdout.strip()).is_equal_to(f"{user.alias} 600")
        logging.info(
            "Verified SSH key permissions for user %s (expected to exist: %s)",
            user.alias,
            ssh_generation_enabled,
        )

        # Check SSH login with SSH key to head node and to a static compute nodes
        logging.info(
            "Checking SSH key usable for SSH login for user %s (expected to exist: %s)",
            user.alias,
            ssh_generation_enabled,
        )
        read_ssh_key = f"sudo cat {ssh_key_path}"
        result = remote_command_executor.run_remote_command(read_ssh_key)
        assert_that(result.failed).is_false()
        key_content = result.stdout
        assert_that(key_content).is_not_empty()

        user_command_executor = user.ssh_connect(pkey=Ed25519Key.from_private_key(io.StringIO(key_content)))
        logging.info(
            "Verified SSH key usable for SSH login to the head node for user %s (expected to exist: %s)",
            user.alias,
            ssh_generation_enabled,
        )
        compute_nodes = scheduler_commands.get_compute_nodes()
        static_compute_node = None
        for node in compute_nodes:
            if "-st" in node:
                static_compute_node = node
                break
        user_command_executor.exec_command(f"ssh {static_compute_node} hostname")
        logging.info(
            "Verified SSH key usable for SSH login to the compute node for user %s (expected to exist: %s)",
            user.alias,
            ssh_generation_enabled,
        )


# Some tests have been disabled to save time and reduce costs.
@pytest.mark.parametrize(
    "directory_type,directory_protocol,directory_certificate_verification",
    [
        ("SimpleAD", "ldap", False),
        ("MicrosoftAD", "ldaps", True),
    ],
)
@pytest.mark.usefixtures("os", "instance")
def test_ad_integration(  # noqa: C901
    region,
    scheduler,
    scheduler_commands_factory,
    pcluster_config_reader,
    directory_type,
    directory_protocol,
    directory_certificate_verification,
    test_datadir,
    directory_factory,
    request,
    clusters_factory,
):
    """
    Verify AD integration works as expected.
    In particular, it verifies that :
    1. AD users can access to the head node, both with password and SSH key (if created);
    2. SSH key for AD users is [not] created when the property GenerateSshKeysForUsers is true [false];
    3. SSH key for AD users is created when the property GenerateSshKeysForUsers is true;
    4. AD users can submit workloads;
    5. AD users filter out by LdapAccessFilter cannot access to the head node.
    """
    if not is_directory_supported(region, directory_type):
        pytest.skip(f"Skipping the test because directory type {directory_type} is not supported in region {region}")

    directory_stack_name = directory_factory(
        request.config.getoption("directory_stack_name"),
        directory_type,
        region,
    )
    directory_stack_outputs = get_infra_stack_outputs(directory_stack_name)
    ad_user_password = get_user_password(directory_stack_outputs.get("UserPasswordSecretArn"))

    ldap_tls_ca_cert = "/opt/parallelcluster/shared/directory_service/certificate.crt"
    config_params = get_ad_config_param_vals(
        directory_stack_outputs,
        ldap_tls_ca_cert,
        directory_type,
        directory_protocol,
        directory_certificate_verification,
    )

    vpc = directory_stack_outputs.get("VpcId")
    config_params.update(get_vpc_public_subnet(vpc))

    cluster_config = pcluster_config_reader(**config_params)
    cluster = clusters_factory(cluster_config)

    certificate_secret_arn = directory_stack_outputs.get("DomainCertificateSecretArn")
    certificate = boto3.client("secretsmanager").get_secret_value(SecretId=certificate_secret_arn)["SecretString"]
    with open(test_datadir / "certificate.crt", "w") as f:
        f.write(certificate)

    remote_command_executor = RemoteCommandExecutor(cluster)
    remote_command_executor.run_remote_command(
        f"sudo cp certificate.crt {ldap_tls_ca_cert} && sudo service sssd restart",
        additional_files=[test_datadir / "certificate.crt"],
    )
    if directory_certificate_verification:
        logging.info("Sleeping 10 minutes to wait for the SSSD agent use the certificate.")
        time.sleep(600)
        # TODO: we have to sleep for 10 minutes to wait for the SSSD agent use the newly placed certificate.
        #  We should look for other methods to let the SSSD agent use the new certificate more quickly

    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    assert_that(NUM_USERS_TO_TEST).is_less_than_or_equal_to(NUM_USERS_TO_CREATE)
    users = []
    for user_num in range(NUM_USERS_TO_TEST):
        users.append(
            ClusterUser(
                user_num,
                test_datadir,
                cluster,
                scheduler,
                remote_command_executor,
                ad_user_password,
                scheduler_commands_factory,
            )
        )
    shared_storage_mount_dirs = ["/shared"]
    _run_user_workloads(users, test_datadir, shared_storage_mount_dirs)
    logging.info("Testing pcluster update and generate ssh keys for user")
    _check_ssh_key_generation(users[0], remote_command_executor, scheduler_commands, False)

    # Verify access control with ldap access provider.
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update.yaml", **config_params)
    cluster.update(str(updated_config_file), force_update="true")
    # Reset stateful connection variables after the cluster update
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    for user in users:
        user.reset_stateful_connection_objects(remote_command_executor, scheduler_commands_factory)
    _check_ssh_key_generation(users[1], remote_command_executor, scheduler_commands, True)
    for user in users:
        logging.info(f"Checking SSH access for user {user.alias}")
        _check_ssh_auth(user=user, expect_success=user.alias != "PclusterUser2")

    # Verify access control with simple access provider.
    # With this test we also verify that AdditionalSssdConfigs is working properly.
    updated_config_file = pcluster_config_reader(config_file="pcluster.config.update2.yaml", **config_params)
    cluster.update(str(updated_config_file), force_update="true")
    # Reset stateful connection variables after the cluster update
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    for user in users:
        user.reset_stateful_connection_objects(remote_command_executor, scheduler_commands_factory)
    _check_ssh_key_generation(users[1], remote_command_executor, scheduler_commands, True)
    for user in users:
        logging.info(f"Checking SSH access for user {user.alias}")
        _check_ssh_auth(user=user, expect_success=user.alias != "PclusterUser0")

    run_system_analyzer(cluster, scheduler_commands_factory, request)


def _check_ssh_auth(user, expect_success=True):
    try:
        user.ssh_connect()
    except Exception as e:
        if expect_success:
            logging.error(f"SSH access denied for user {user.alias}")
            raise e
        else:
            logging.info(f"SSH access denied for user {user.alias}, as expected")


@pytest.mark.parametrize(
    "directory_type,directory_protocol,directory_certificate_verification",
    [
        ("SimpleAD", "ldap", False),
        ("MicrosoftAD", "ldaps", True),
    ],
)
@pytest.mark.usefixtures("os", "instance")
def test_ad_integration_on_login_nodes(
    region,
    scheduler,
    scheduler_commands_factory,
    pcluster_config_reader,
    directory_type,
    directory_protocol,
    directory_certificate_verification,
    test_datadir,
    directory_factory,
    request,
    store_secret_in_secret_manager,
    clusters_factory,
):
    """
    Verify AD integration works as expected.
    In particular, it verifies that :
    1. AD users can access to the login node, both with password and SSH key (if created);
    2. SSH key for AD users is created when the property GenerateSshKeysForUsers is true;
    3. AD users can submit workloads;
    """
    directory_stack_name = directory_factory(
        request.config.getoption("directory_stack_name"),
        directory_type,
        region,
    )
    directory_stack_outputs = get_infra_stack_outputs(directory_stack_name)
    ad_user_password = get_user_password(directory_stack_outputs.get("PasswordSecretArn"))
    ldap_tls_ca_cert = "/opt/parallelcluster/shared_login_nodes/directory_service/certificate.crt"
    config_params = get_ad_config_param_vals(
        directory_stack_outputs,
        ldap_tls_ca_cert,
        directory_type,
        directory_protocol,
        directory_certificate_verification,
    )
    config_params.update(get_vpc_public_subnet(directory_stack_outputs.get("VpcId")))
    cluster_config = pcluster_config_reader(**config_params)
    cluster = clusters_factory(cluster_config)

    certificate_secret_arn = directory_stack_outputs.get("DomainCertificateSecretArn")
    certificate = boto3.client("secretsmanager").get_secret_value(SecretId=certificate_secret_arn)["SecretString"]
    with open(test_datadir / "certificate.crt", "w") as f:
        f.write(certificate)

    # Publish compute node count metric every minute via cron job
    remote_command_executor = RemoteCommandExecutor(cluster)
    remote_command_executor.run_remote_command(
        f"sudo cp certificate.crt {ldap_tls_ca_cert} && sudo service sssd restart",
        additional_files=[test_datadir / "certificate.crt"],
    )
    if directory_certificate_verification:
        logging.info("Sleeping 10 minutes to wait for the SSSD agent use the certificate.")
        time.sleep(600)
        # TODO: we have to sleep for 10 minutes to wait for the SSSD agent use the newly placed certificate.
        #  We should look for other methods to let the SSSD agent use the new certificate more quickly

    login_node_command_executor = RemoteCommandExecutor(cluster, use_login_node=True)
    scheduler_commands = scheduler_commands_factory(login_node_command_executor)
    users = []
    for user_num in range(NUM_USERS_TO_TEST):
        users.append(
            ClusterUser(
                user_num,
                test_datadir,
                cluster,
                scheduler,
                login_node_command_executor,
                ad_user_password,
                scheduler_commands_factory,
            )
        )

    # Let's test that AD users can login into a LoginNode and they'll have their home and ssh-key created
    # With the same behavior we have in the HeadNode
    for user in users:
        _check_ssh_key_generation(user, login_node_command_executor, scheduler_commands, True)

    run_system_analyzer(cluster, scheduler_commands_factory, request)
