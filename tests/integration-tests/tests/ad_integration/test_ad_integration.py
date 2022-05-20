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
import string
import time
import zipfile
from collections import defaultdict

import boto3
import pytest
from assertpy import assert_that
from cfn_stacks_factory import CfnStack, CfnStacksFactory
from OpenSSL import crypto
from OpenSSL.crypto import FILETYPE_PEM, TYPE_RSA, X509, dump_certificate, dump_privatekey
from paramiko import RSAKey

from framework.fixture_utils import xdist_session_fixture
from framework.tests_configuration.config_utils import get_all_regions
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import seconds
from utils import generate_stack_name, random_alphanumeric, render_jinja_template, render_jinja_template_in_memory

from tests.ad_integration.cluster_user import ClusterUser
from tests.common.osu_common import compile_osu
from tests.common.utils import get_sts_endpoint, retrieve_latest_ami, run_system_analyzer


MICROSOFT_AD_DIRECTORY_TYPE = "MicrosoftAD"
SIMPLE_AD_DIRECTORY_TYPE = "SimpleAD"
NUM_USERS_TO_CREATE = 5
NUM_USERS_TO_TEST = 3


def get_infra_stack_outputs(stack_name):
    cfn = boto3.client("cloudformation")
    return {
        entry.get("OutputKey"): entry.get("OutputValue")
        for entry in cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    }


def get_infra_stack_parameters(stack_name):
    cfn = boto3.client("cloudformation")
    return {
        entry.get("ParameterKey"): entry.get("ParameterValue")
        for entry in cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Parameters"]
    }


def get_ad_config_param_vals(
        directory_stack_outputs,
        directory_protocol,
        directory_certificate_verification,
        ldap_tls_ca_cert
):
    """Return a dict used to set values for config file parameters."""
    domain_name = directory_stack_outputs.get("DomainName")
    ldap_default_bind_dn = directory_stack_outputs.get("DomainReadOnlyUser")
    password_secret_arn = directory_stack_outputs.get("PasswordSecretArn")

    if directory_protocol == "ldaps":
        ldap_uri = directory_stack_outputs.get("DomainAddrLdaps")
    elif directory_protocol == "ldap":
        ldap_uri = directory_stack_outputs.get("DomainAddrLdap")
    else:
        raise Exception(f"Unknown directory protocol: {directory_protocol}")
    return {
        "ldap_uri": ldap_uri,
        "ldap_search_base": domain_name,
        "ldap_default_bind_dn": ldap_default_bind_dn,
        "password_secret_arn": password_secret_arn,
        "ldap_tls_ca_cert": ldap_tls_ca_cert,
        "directory_protocol": directory_protocol,
        "directory_certificate_verification": directory_certificate_verification,
        "ldap_tls_req_cert": "never" if directory_certificate_verification is False else "hard",
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


def _run_user_workloads(users, test_datadir, remote_command_executor):
    compile_osu("openmpi", remote_command_executor)
    _check_whoami(users)
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


def _check_whoami(users):
    logging.info("Checking whoami")
    for user in users:
        result = user.run_remote_command("whoami").stdout
        assert_that(result).is_equal_to(user.alias)
        result = user.run_remote_command("srun whoami").stdout
        assert_that(result).is_equal_to(user.alias)


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
            f"{user.home_dir}/my_file",
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
    _check_home_directory(user, remote_command_executor)
    _check_ssh_key(user, generate_ssh_keys_for_user, remote_command_executor, scheduler_commands)
    logging.info(
        "Verified SSH key generation for user %s on SSH login (expected generation: %s)",
        user.alias,
        generate_ssh_keys_for_user,
    )

    ssh_key_path = f"{user.home_dir}/.ssh/id_rsa"

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

    ssh_key_path = f"{user.home_dir}/.ssh/id_rsa"

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

        user_command_executor = user.ssh_connect(pkey=RSAKey.from_private_key(io.StringIO(key_content)))
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


@pytest.mark.parametrize(
    "directory_type,directory_protocol,directory_certificate_verification",
    [
        (SIMPLE_AD_DIRECTORY_TYPE, "ldap", False),
        # (SIMPLE_AD_DIRECTORY_TYPE, "ldaps", False),
        (SIMPLE_AD_DIRECTORY_TYPE, "ldaps", True),
        (MICROSOFT_AD_DIRECTORY_TYPE, "ldap", False),
        # (MICROSOFT_AD_DIRECTORY_TYPE, "ldaps", False),
        (MICROSOFT_AD_DIRECTORY_TYPE, "ldaps", True),
    ],
)
@pytest.mark.usefixtures("os", "instance")
def test_ad_integration(
    region,
    scheduler,
    scheduler_commands_factory,
    pcluster_config_reader,
    directory_type,
    directory_protocol,
    directory_certificate_verification,
    test_datadir,
    active_directory_regional_stacks,
    request,
    clusters_factory,
    run_benchmarks,
    benchmarks,
):
    """
    Verify AD integration works as expected.
    In particular, it verifies that :
    1. AD users can access to the head node, both with password and SSH key (if created);
    2. SSH key for AD users is [not] created when the property GenerateSshKeysForUsers is true [false];
    3. SSH key for AD users is created when the property GenerateSshKeysForUsers is true;
    4. AD users can submit workloads;
    5. AD users filter out by LdapAccessFilter cannot access to the head node.

    Optionally, it executes performance tests using OSU benchmarks.
    """
    head_node_instance_type = "c5n.18xlarge" if request.config.getoption("benchmarks") else "c5.xlarge"
    compute_instance_type_info = {"name": "c5.xlarge", "num_cores": 4}
    config_params = {
        "compute_instance_type": compute_instance_type_info.get("name"),
        "head_node_instance_type": head_node_instance_type,
    }

    # Retrieve the regional Active Directory and the outputs required to populate cluster configuration
    active_directory_stack_name = active_directory_regional_stacks[directory_type]
    directory_stack_outputs = get_infra_stack_outputs(active_directory_stack_name)
    ad_user_password = directory_stack_outputs.get("UserPassword")
    ldap_tls_ca_cert = "/opt/parallelcluster/shared/directory_service/certificate.crt"
    config_params.update(
        get_ad_config_param_vals(
            directory_stack_outputs,
            directory_protocol,
            directory_certificate_verification,
            ldap_tls_ca_cert,
        )
    )
    cluster_config = pcluster_config_reader(benchmarks=benchmarks, **config_params)
    cluster = clusters_factory(cluster_config)

    # Copy the certificate from Secrets Manager to the cluster
    # TODO: this operation should be executed within a bootstrap script
    if directory_certificate_verification:
        certificate_secret_arn = directory_stack_outputs.get("DomainCertificateSecretArn")
        certificate = boto3.client("secretsmanager").get_secret_value(SecretId=certificate_secret_arn)["SecretString"]
        with open(test_datadir / "certificate.crt", "wb") as f:
            f.write(certificate.encode())
        remote_command_executor = RemoteCommandExecutor(cluster)
        remote_command_executor.run_remote_command(
            f"sudo cp certificate.crt {ldap_tls_ca_cert} && sudo service sssd restart",
            additional_files=[test_datadir / "certificate.crt"],
        )
        logging.info("Sleeping 10 minutes to wait for the SSSD agent use the certificate.")
        time.sleep(600)
        # TODO: we have to sleep for 10 minutes to wait for the SSSD agent use the newly placed certificate.
        #  We should look for other methods to let the SSSD agent use the new certificate more quickly

    remote_command_executor = RemoteCommandExecutor(cluster)
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
    _run_user_workloads(users, test_datadir, remote_command_executor)
    logging.info("Testing pcluster update and generate ssh keys for user")
    _check_ssh_key_generation(users[0], remote_command_executor, scheduler_commands, False)

    # Verify access control with ldap access provider.
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update.yaml", benchmarks=benchmarks, **config_params
    )
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
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config.update2.yaml", benchmarks=benchmarks, **config_params
    )
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
    run_benchmarks(users[0].remote_command_executor(), users[0].scheduler_commands(), diretory_type=directory_type)


def _check_ssh_auth(user, expect_success=True):
    try:
        user.ssh_connect()
    except Exception as e:
        if expect_success:
            logging.error(f"SSH access denied for user {user.alias}")
            raise e
        else:
            logging.info(f"SSH access denied for user {user.alias}, as expected")


def generate_active_directory_stack_parameters(request, directory_type, vpc_stack):
    ad_admin_password = "".join(random.choices(string.ascii_letters + string.digits, k=60))
    ad_readonly_password = "".join(random.choices(string.ascii_letters + string.digits, k=60))
    ad_user_password = "".join(random.choices(string.ascii_letters + string.digits, k=60))
    ad_domain_name = f"integ.{random_alphanumeric(size=5)}.{directory_type.lower()}.pcluster"
    ad_users = [f"PclusterUser{i}" for i in range(NUM_USERS_TO_CREATE)]

    admin_node_key_name = request.config.getoption("key_name")

    return [
        {"ParameterKey": "Vpc", "ParameterValue": vpc_stack.cfn_outputs["VpcId"]},
        {"ParameterKey": "PrivateSubnetOne", "ParameterValue": vpc_stack.cfn_outputs["PrivateSubnetId"]},
        {
            "ParameterKey": "PrivateSubnetTwo",
            "ParameterValue": vpc_stack.cfn_outputs["PrivateAdditionalCidrSubnetId"],
        },
        {"ParameterKey": "DomainName", "ParameterValue": ad_domain_name},
        {"ParameterKey": "AdminPassword", "ParameterValue": ad_admin_password},
        {"ParameterKey": "ReadOnlyPassword", "ParameterValue": ad_readonly_password},
        {"ParameterKey": "UserName", "ParameterValue": " ".join(ad_users)},
        {"ParameterKey": "UserPassword", "ParameterValue": ad_user_password},
        {"ParameterKey": "Keypair", "ParameterValue": admin_node_key_name},
    ]


def create_active_directory_stacks(request, stack_factory, directory_type, vpc_stacks):
    regions = request.config.getoption("regions") or get_all_regions(request.config.getoption("tests_config"))

    stack_template_path = os_lib.path.join("resources", "templates", "active-directory.cfn.yaml")

    directories_dict = {}

    for region in regions:
        vpc_stack = vpc_stacks[region]

        template_config = {"directory_type": directory_type}

        stack_template_data = render_jinja_template_in_memory(stack_template_path, **template_config)

        option_name = "directory_stack_name"
        if request.config.getoption(option_name):
            stack_name = request.config.getoption(option_name)
            logging.info("Using stack {0} in region {1}".format(stack_name, region))
            stack = CfnStack(
                name=stack_name,
                region=region,
                capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
                template=stack_template_data,
                parameters=get_infra_stack_parameters(stack_name),
            )
        else:
            stack_name = generate_stack_name(
                "integ-tests-active-directory-{0}".format(directory_type),
                request.config.getoption("stackname_suffix"),
            )
            logging.info("Creating stack {0} in region {1}".format(stack_name, region))
            stack = CfnStack(
                name=stack_name,
                region=region,
                capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
                template=stack_template_data,
                parameters=generate_active_directory_stack_parameters(request, directory_type, vpc_stack),
            )

            stack_factory.create_stack(stack)

        directories_dict[region] = stack.name

    return directories_dict


@xdist_session_fixture(autouse=False)
def active_directory_microsoftad_stacks(request, vpc_stacks):
    """
    Define a fixture to create Active Directories with AWS Directory Service, shared among session.
    One Directory per type (MicrosoftAD or SimpleAD) per region will be created.
    :return: a dictionary of directories with key [region].
    """
    stack_factory = CfnStacksFactory(request.config.getoption("credential"))
    directories_dict = create_active_directory_stacks(request, stack_factory, MICROSOFT_AD_DIRECTORY_TYPE, vpc_stacks)

    yield directories_dict

    if not request.config.getoption("no_delete"):
        stack_factory.delete_all_stacks()
    else:
        logging.warning("Skipping deletion of CFN stacks because --no-delete option is set")


@xdist_session_fixture(autouse=False)
def active_directory_simplead_stacks(request, vpc_stacks):
    """
    Define a fixture to create Active Directories with AWS Directory Service, shared among session.
    One Directory per type (MicrosoftAD or SimpleAD) per region will be created.
    :return: a dictionary of directories with key [region].
    """
    stack_factory = CfnStacksFactory(request.config.getoption("credential"))

    directories_dict = create_active_directory_stacks(request, stack_factory, SIMPLE_AD_DIRECTORY_TYPE, vpc_stacks)

    yield directories_dict

    if not request.config.getoption("no_delete"):
        stack_factory.delete_all_stacks()
    else:
        logging.warning("Skipping deletion of CFN stacks because --no-delete option is set")


@pytest.fixture(scope="class")
def active_directory_regional_stacks(region, active_directory_simplead_stacks, active_directory_microsoftad_stacks):
    return {
        MICROSOFT_AD_DIRECTORY_TYPE: active_directory_microsoftad_stacks[region],
        SIMPLE_AD_DIRECTORY_TYPE: active_directory_simplead_stacks[region],
    }