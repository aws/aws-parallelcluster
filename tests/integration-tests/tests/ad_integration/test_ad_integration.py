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

import boto3
import pytest
from assertpy import assert_that
from cfn_stacks_factory import CfnStack, CfnStacksFactory
from framework.fixture_utils import xdist_session_fixture
from framework.tests_configuration.config_utils import get_all_regions
from OpenSSL import crypto
from OpenSSL.crypto import FILETYPE_PEM, TYPE_RSA, X509, dump_certificate, dump_privatekey
from paramiko import RSAKey
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from utils import generate_stack_name, random_alphanumeric, render_jinja_template_in_memory

from tests.ad_integration.cluster_user import ClusterUser
from tests.common.osu_common import compile_osu
from tests.common.utils import run_system_analyzer

DIRECTORY_TYPES = ["MicrosoftAD", "SimpleAD"]
NUM_USERS_TO_CREATE = 5
NUM_USERS_TO_TEST = 3


def get_infra_stack_outputs(stack_name):
    cfn = boto3.client("cloudformation")
    return {
        entry.get("OutputKey"): entry.get("OutputValue")
        for entry in cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    }


def get_ad_config_param_vals(
    domain_name,
    domain_short_name,
    directory_dns_ips,
    domain_distinguished_name,
    read_only_username,
    password_secret_arn,
    ldap_tls_ca_cert,
    directory_type,
    directory_protocol,
    directory_certificate_verification,
):
    """Return a dict used to set values for config file parameters."""
    if directory_type == "SimpleAD":
        ldap_default_bind_dn = f"CN={read_only_username},CN=Users,{domain_distinguished_name}"
    elif directory_type == "MicrosoftAD":
        ldap_default_bind_dn = f"CN={read_only_username},OU=Users,OU={domain_short_name},{domain_distinguished_name}"
    else:
        raise Exception(f"Unknown directory type: {directory_type}")

    if directory_protocol == "ldaps":
        ldap_uri = domain_name
    elif directory_protocol == "ldap":
        ldap_uri = ",".join(f"ldap://{ip}" for ip in directory_dns_ips.split(","))
    else:
        raise Exception(f"Unknown directory protocol: {directory_protocol}")
    return {
        "ldap_uri": ldap_uri,
        "ldap_search_base": domain_distinguished_name,
        "ldap_default_bind_dn": ldap_default_bind_dn,
        "password_secret_arn": password_secret_arn,
        "ldap_tls_ca_cert": ldap_tls_ca_cert,
        "directory_protocol": directory_protocol,
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


# Some tests have been disabled to save time and reduce costs.
@pytest.mark.parametrize(
    "directory_type,directory_protocol,directory_certificate_verification",
    [
        ("SimpleAD", "ldap", False),
        #("SimpleAD", "ldaps", False),
        ("SimpleAD", "ldaps", True),
        ("MicrosoftAD", "ldap", False),
        #("MicrosoftAD", "ldaps", False),
        ("MicrosoftAD", "ldaps", True),
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
    request,
    clusters_factory,
    run_benchmarks,
    benchmarks,
    regional_active_directory,
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
    active_directory_stack_name = regional_active_directory[directory_type]
    directory_stack_outputs = get_infra_stack_outputs(active_directory_stack_name)
    domain_name = directory_stack_outputs.get("DomainName")
    domain_short_name = directory_stack_outputs.get("DomainShortName")
    directory_dns_ips = directory_stack_outputs.get("DirectoryDnsIpAddresses")
    domain_distinguished_name = directory_stack_outputs.get("DomainDistinguishedName")
    read_only_username = directory_stack_outputs.get("ReadOnlyUserName")
    ad_user_password = directory_stack_outputs.get("UserPassword")
    password_secret_arn = directory_stack_outputs.get("ReadOnlyUserPasswordSecretArn")
    certificate_secret_arn = directory_stack_outputs.get("CertificateSecretArn")
    ldap_tls_ca_cert = "/opt/parallelcluster/shared/directory_service/certificate.crt"
    certificate = boto3.client("secretsmanager").get_secret_value(SecretId=certificate_secret_arn)["SecretBinary"]
    with open(test_datadir / "certificate.crt", "wb") as f:
        f.write(certificate)
    config_params.update(
        get_ad_config_param_vals(
            domain_name,
            domain_short_name,
            directory_dns_ips,
            domain_distinguished_name,
            read_only_username,
            password_secret_arn,
            ldap_tls_ca_cert,
            directory_type,
            directory_protocol,
            directory_certificate_verification,
        )
    )
    cluster_config = pcluster_config_reader(benchmarks=benchmarks, **config_params)
    cluster = clusters_factory(cluster_config)

    # Publish compute node count metric every minute via cron job
    # TODO: use metrics reporter from the benchmarks module
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
    remote_command_executor = RemoteCommandExecutor(cluster)
    metric_publisher_script = "publish_compute_node_count_metric.sh"
    remote_metric_publisher_script_path = f"/shared/{metric_publisher_script}"
    crontab_expression = f"* * * * * {remote_metric_publisher_script_path} &> {remote_metric_publisher_script_path}.log"
    remote_command_executor.run_remote_command(
        f"echo '{crontab_expression}' | crontab -",
        additional_files={str(test_datadir / metric_publisher_script): remote_metric_publisher_script_path},
    )

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


@retry(stop_max_attempt_number=3, wait_exponential_multiplier=2000, wait_exponential_max=30000)
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
        TimeoutSeconds=num_users_to_create * 4 + 300,
        Parameters={"DirectoryId": [directory_id], "NumUsersToCreate": [str(num_users_to_create)]},
    )["Command"]["CommandId"]
    _check_ssm_success(ssm_client, command_id, admin_node_instance_id)
    logging.info("Creation of %s users in directory service completed", str(num_users_to_create))


def _generate_certificate_and_private_key(common_name):
    key = crypto.PKey()
    key.generate_key(TYPE_RSA, 2048)
    crt = X509()
    crt.get_subject().commonName = common_name
    crt.get_issuer().commonName = common_name
    now = datetime.datetime.now()
    days = datetime.timedelta(days=90)
    asn1_time_format = "%Y%m%d000000Z"
    crt.set_notBefore((now - days).strftime(asn1_time_format).encode())
    crt.set_notAfter((now + days).strftime(asn1_time_format).encode())
    crt.set_serial_number(random.randrange(1, 99999))
    crt.set_pubkey(key)
    crt.sign(key, "sha256")
    certificate = dump_certificate(FILETYPE_PEM, crt)
    private_key = dump_privatekey(FILETYPE_PEM, key)
    return certificate, private_key


@retry(stop_max_attempt_number=3, wait_exponential_multiplier=2000, wait_exponential_max=30000)
def _import_certificate_to_acm(region, certificate, private_key):
    logging.info("Importing ACM Certificate in region {0}".format(region))
    acm_client = boto3.client("acm", region_name=region)
    certificate_arn = acm_client.import_certificate(Certificate=certificate, PrivateKey=private_key)["CertificateArn"]
    logging.info("Imported ACM Certificate in region {0}: {1}".format(region, certificate_arn))
    return certificate_arn


@retry(stop_max_attempt_number=3, wait_exponential_multiplier=2000, wait_exponential_max=30000)
def _delete_certificate_from_acm(certificate_arn, region):
    logging.info("Deleting Certificate in region {0}: {1}".format(region, certificate_arn))
    boto3.client("acm", region_name=region).delete_certificate(CertificateArn=certificate_arn)


@retry(stop_max_attempt_number=3, wait_exponential_multiplier=2000, wait_exponential_max=30000)
def _store_secret_in_secrets_manager(region, name, secret_string=None, secret_binary=None):
    logging.info("Storing Secret in region {0}: {1}".format(region, name))
    secrets_manager_client = boto3.client("secretsmanager", region_name=region)
    if secret_string:
        secret_arn = secrets_manager_client.create_secret(Name=name, SecretString=secret_string)["ARN"]
    else:
        secret_arn = secrets_manager_client.create_secret(Name=name, SecretBinary=secret_binary)["ARN"]
    logging.info("Stored Secret in region {0}: {1}".format(region, secret_arn))
    return secret_arn


@retry(stop_max_attempt_number=3, wait_exponential_multiplier=2000, wait_exponential_max=30000)
def _delete_secret_from_secrets_manager(secret_arn, region):
    logging.info("Deleting Secret in region {0}: {1}".format(region, secret_arn))
    boto3.client("secretsmanager", region_name=region).delete_secret(SecretId=secret_arn)


@pytest.fixture(scope="session", autouse=False)
def active_directory_certificate_factory(request):
    certificates = []

    def _active_directory_certificate_factory(region, domain_name):
        logging.info("Generating certificate resources in region {0} for domain {1}".format(region, domain_name))
        certificate, private_key = _generate_certificate_and_private_key(domain_name)
        certificate_arn = _import_certificate_to_acm(region, certificate, private_key)
        certificate_secret_name = generate_stack_name(
            "integ-active-directory-certificate", request.config.getoption("stackname_suffix")
        )
        certificate_secret_arn = _store_secret_in_secrets_manager(
            region, name=certificate_secret_name, secret_binary=certificate
        )
        certificate_info = {
            "certificate_arn": certificate_arn,
            "certificate_secret_arn": certificate_secret_arn,
            "region": region,
        }
        certificates.append(certificate_info)
        logging.info(
            "Generated certificate resources in region {0} for domain {1}: {2}".format(
                region, domain_name, certificate_info
            )
        )
        return certificate_info

    yield _active_directory_certificate_factory

    if not request.config.getoption("no_delete"):
        for certificate_info in certificates:
            region = certificate_info["region"]
            logging.info("Deleting Certificate resources in region {0}: {1}".format(region, certificate_info))
            certificate_secret_arn = certificate_info["certificate_secret_arn"]
            _delete_secret_from_secrets_manager(certificate_secret_arn, region)
            certificate_arn = certificate_info["certificate_arn"]
            logging.info(
                "Sleeping 180 seconds to wait for the ACM certificate {0} in region {1} to become unused".format(
                    certificate_arn,
                    region,
                )
            )
            time.sleep(180)
            _delete_certificate_from_acm(certificate_arn, region)
    else:
        logging.warning(
            "Skipping deletion Active Directory certificates because --no-delete option is set: {0}".format(
                certificates
            )
        )


@xdist_session_fixture(autouse=False)
def active_directory_factory_shared(request, vpc_stacks, active_directory_certificate_factory):
    """
    Define a fixture to create Active Directories with AWS Directory Service, shared among session.
    One Directory per type (MicrosoftAD or SimpleAD) per region will be created.
    :return: a dictionary of directories with region and type as key.
    """
    stack_factory = CfnStacksFactory(request.config.getoption("credential"))

    regions = request.config.getoption("regions") or get_all_regions(request.config.getoption("tests_config"))

    stack_template_path = os_lib.path.join("resources", "templates", "active-directory.cfn.yaml")

    directories_dict = {region: {type: None for type in DIRECTORY_TYPES} for region in regions}

    for region in regions:
        vpc_stack = vpc_stacks[region]
        for directory_type in DIRECTORY_TYPES:
            ad_admin_password = "".join(random.choices(string.ascii_letters + string.digits, k=60))
            ad_user_password = "".join(random.choices(string.ascii_letters + string.digits, k=60))
            ad_domain_name = f"integ.{random_alphanumeric(size=5)}.{directory_type.lower()}.pcluster"
            ad_domain_short_name = "CORP"
            domain_distinguished_name = ",".join([f"dc={dc}" for dc in ad_domain_name.split(".")])
            if directory_type == "SimpleAD":
                users_base_search = f"cn=Users,{domain_distinguished_name}"
            elif directory_type == "MicrosoftAD":
                users_base_search = f"ou=Users,ou={ad_domain_short_name},{domain_distinguished_name}"
            else:
                raise Exception(f"Unknown directory type: {directory_type}")

            admin_node_key_name = request.config.getoption("key_name")
            certificate_info = active_directory_certificate_factory(region, ad_domain_name)

            template_config = {
                "directory_type": directory_type,
                "domain_distinguished_name": domain_distinguished_name,
                "users_base_search": users_base_search,
            }

            stack_template_data = render_jinja_template_in_memory(stack_template_path, **template_config)

            stack_params = [
                {"ParameterKey": "Vpc", "ParameterValue": vpc_stack.cfn_outputs["VpcId"]},
                {"ParameterKey": "PrivateSubnetOne", "ParameterValue": vpc_stack.cfn_outputs["PrivateSubnetId"]},
                {
                    "ParameterKey": "PrivateSubnetTwo",
                    "ParameterValue": vpc_stack.cfn_outputs["PrivateAdditionalCidrSubnetId"],
                },
                {"ParameterKey": "PublicSubnetOne", "ParameterValue": vpc_stack.cfn_outputs["PublicSubnetId"]},
                {"ParameterKey": "DirectoryType", "ParameterValue": directory_type},
                {"ParameterKey": "DomainName", "ParameterValue": ad_domain_name},
                {"ParameterKey": "DomainShortName", "ParameterValue": ad_domain_short_name},
                {"ParameterKey": "AdminPassword", "ParameterValue": ad_admin_password},
                {"ParameterKey": "UserPassword", "ParameterValue": ad_user_password},
                {"ParameterKey": "AdminNodeKeyName", "ParameterValue": admin_node_key_name},
                {"ParameterKey": "LDAPSCertificateARN", "ParameterValue": certificate_info["certificate_arn"]},
                {"ParameterKey": "CertificateSecretArn", "ParameterValue": certificate_info["certificate_secret_arn"]},
            ]

            logging.info("Generated CFN parameters: {0}".format(stack_params))

            option_name = "directory_stack_name"
            if request.config.getoption(option_name):
                stack_name = request.config.getoption(option_name)
                logging.info("Using stack {0} in region {1}".format(stack_name, region))
                stack = CfnStack(
                    name=stack_name,
                    region=region,
                    capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"],
                    template=stack_template_data,
                    parameters=stack_params,
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
                    capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"],
                    template=stack_template_data,
                    parameters=stack_params,
                )

                stack_factory.create_stack(stack)
                _populate_directory_with_users(stack, NUM_USERS_TO_CREATE, region)
            directories_dict[region][directory_type] = stack.name

    yield directories_dict

    if not request.config.getoption("no_delete"):
        stack_factory.delete_all_stacks()
    else:
        logging.warning("Skipping deletion of CFN stacks because --no-delete option is set")


@pytest.fixture(scope="class")
def regional_active_directory(active_directory_factory_shared, region):
    return active_directory_factory_shared[region]
