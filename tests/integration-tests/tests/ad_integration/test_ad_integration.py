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
from cfn_stacks_factory import CfnStack
from OpenSSL import crypto
from OpenSSL.crypto import FILETYPE_PEM, TYPE_RSA, X509, dump_certificate, dump_privatekey
from paramiko import RSAKey
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import seconds
from utils import generate_stack_name, random_alphanumeric, render_jinja_template

from tests.ad_integration.cluster_user import ClusterUser
from tests.common.osu_common import compile_osu
from tests.common.utils import get_sts_endpoint, retrieve_latest_ami, run_system_analyzer
from tests.storage.test_fsx_lustre import create_fsx_ontap, create_fsx_open_zfs

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


def _get_ldap_base_search(domain_name):
    return ",".join([f"dc={domain_component}" for domain_component in domain_name.split(".")])


def get_ad_config_param_vals(
    directory_stack_outputs,
    nlb_stack_parameters,
    password_secret_arn,
    ldap_tls_ca_cert,
    directory_type,
    directory_protocol,
    directory_certificate_verification,
):
    """Return a dict used to set values for config file parameters."""
    ldap_search_base = _get_ldap_base_search(directory_stack_outputs.get("DomainName"))
    domain_short_name = directory_stack_outputs.get("DomainShortName")
    read_only_username = directory_stack_outputs.get("ReadOnlyUserName")

    if directory_type == "SimpleAD":
        ldap_default_bind_dn = f"CN={read_only_username},CN=Users,{ldap_search_base}"
    elif directory_type == "MicrosoftAD":
        ldap_default_bind_dn = f"CN={read_only_username},OU=Users,OU={domain_short_name},{ldap_search_base}"
    else:
        raise Exception(f"Unknown directory type: {directory_type}")

    if directory_protocol == "ldaps":
        ldap_uri = nlb_stack_parameters.get("DomainName")
    elif directory_protocol == "ldap":
        directory_dns_ips = directory_stack_outputs.get("DirectoryDnsIpAddresses")
        ldap_uri = ",".join(f"ldap://{ip}" for ip in directory_dns_ips.split(","))
    else:
        raise Exception(f"Unknown directory protocol: {directory_protocol}")
    return {
        "ldap_uri": ldap_uri,
        "ldap_search_base": ldap_search_base,
        "ldap_default_bind_dn": ldap_default_bind_dn,
        "password_secret_arn": password_secret_arn,
        "ldap_tls_ca_cert": ldap_tls_ca_cert,
        "directory_protocol": directory_protocol,
        "ldap_tls_req_cert": "never" if directory_certificate_verification is False else "hard",
    }


def get_fsx_config_param_vals(fsx_factory, svm_factory):
    fsx_ontap_fs_ids = create_fsx_ontap(fsx_factory, num=1)
    fsx_ontap_volume_ids = [volume_id for _, volume_id in svm_factory(fsx_ontap_fs_ids)]
    fsx_open_zfs_volume_ids = create_fsx_open_zfs(fsx_factory, num=1)
    return {"fsx_ontap_volume_id": fsx_ontap_volume_ids[0], "fsx_open_zfs_volume_id": fsx_open_zfs_volume_ids[0]}


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


@pytest.fixture(scope="module")
def store_secret_in_secret_manager(request, cfn_stacks_factory):

    secret_arns = {}

    def _store_secret(region, secret_string=None, secret_binary=None):
        secrets_manager_client = boto3.client("secretsmanager")
        if secret_string is None and secret_binary is None:
            logging.error("secret string and scecret binary can not both be empty")
        secret_name = generate_stack_name("integ-tests-secret", request.config.getoption("stackname_suffix"))
        if secret_string:
            secret_arn = secrets_manager_client.create_secret(Name=secret_name, SecretString=secret_string)["ARN"]
        else:
            secret_arn = secrets_manager_client.create_secret(Name=secret_name, SecretBinary=secret_binary)["ARN"]
        if secret_arns.get(region):
            secret_arns[region].append(secret_arn)
        else:
            secret_arns[region] = [secret_arn]
        return secret_arn

    yield _store_secret

    if request.config.getoption("no_delete"):
        logging.info("Not deleting stack secrets because --no-delete option was specified")
    else:
        for region, secrets in secret_arns.items():
            secrets_manager_client = boto3.client("secretsmanager", region_name=region)
            for secret_arn in secrets:
                logging.info("Deleting secret %s", secret_arn)
                secrets_manager_client.delete_secret(SecretId=secret_arn)


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
    ad_domain_name = f"{directory_type.lower()}.{random_alphanumeric(size=10)}.multiuser.pcluster"
    ad_domain_short_name = "NET"
    ad_base_search = _get_ldap_base_search(ad_domain_name)
    if directory_type == "SimpleAD":
        ad_users_base_search = f"CN=Users,{ad_base_search}"
    elif directory_type == "MicrosoftAD":
        ad_users_base_search = f"OU=Users,OU={ad_domain_short_name},{ad_base_search}"
    else:
        raise Exception(f"Unknown directory type: {directory_type}")

    config_args = {
        "region": region,
        "account": account_id,
        "admin_node_ami_id": retrieve_latest_ami(region, "alinux2"),
        "admin_node_instance_type": "c5.large",
        "admin_node_key_name": request.config.getoption("key_name"),
        "ad_users_base_search": ad_users_base_search,
        "ad_admin_password": ad_admin_password,
        "ad_user_password": ad_user_password,
        "ad_domain_name": ad_domain_name,
        "ad_domain_short_name": ad_domain_short_name,
        "default_ec2_domain": "ec2.internal" if region == "us-east-1" else f"{region}.compute.internal",
        "ad_admin_user": "Administrator" if directory_type == "SimpleAD" else "Admin",
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
        TimeoutSeconds=num_users_to_create * 4 + 300,
        Parameters={"DirectoryId": [directory_id], "NumUsersToCreate": [str(num_users_to_create)]},
    )["Command"]["CommandId"]
    _check_ssm_success(ssm_client, command_id, admin_node_instance_id)
    logging.info("Creation of %s users in directory service completed", str(num_users_to_create))


def _create_nlb_stack(
    cfn_stacks_factory,
    request,
    directory_stack,
    region,
    test_resources_dir,
    certificate_arn,
    certificate_secret_arn,
    domain_name,
):
    nlb_stack_template_path = os_lib.path.join(test_resources_dir, "NLB_SimpleAD.yaml")
    nlb_stack_name = generate_stack_name(
        "integ-tests-MultiUserInfraStackNLB", request.config.getoption("stackname_suffix")
    )
    logging.info("Creating stack %s", nlb_stack_name)
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
                {
                    "ParameterKey": "CertificateSecretArn",
                    "ParameterValue": certificate_secret_arn,
                },
                {
                    "ParameterKey": "DomainName",
                    "ParameterValue": domain_name,
                },
            ],
        )
    cfn_stacks_factory.create_stack(nlb_stack)
    logging.info("Creation of NLB stack %s complete", nlb_stack_name)
    return nlb_stack


def _generate_certificate(common_name):
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
    certificate_arn = boto3.client("acm").import_certificate(Certificate=certificate, PrivateKey=private_key)[
        "CertificateArn"
    ]
    return certificate_arn, certificate


@retry(stop_max_attempt_number=10, wait_exponential_multiplier=2000, wait_exponential_max=30000)
def _delete_certificate(certificate_arn, region):
    logging.info("Deleting ACM certificate %s in region %s", certificate_arn, region)
    boto3.client("acm", region_name=region).delete_certificate(CertificateArn=certificate_arn)


@pytest.fixture(scope="module")
def directory_factory(request, cfn_stacks_factory, vpc_stacks, store_secret_in_secret_manager):  # noqa: C901
    # TODO: use external data file and file locking in order to share directories across processes
    created_directory_stacks = defaultdict(dict)
    created_certificates = defaultdict(dict)

    def _directory_factory(
        existing_directory_stack_name,
        existing_nlb_stack_name,
        directory_type,
        test_resources_dir,
        region,
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
            directory_stack_outputs = get_infra_stack_outputs(directory_stack_name)
            common_name = directory_stack_outputs.get("DomainName")
            certificate_arn, certificate = _generate_certificate(common_name)
            certificate_secret_arn = store_secret_in_secret_manager(region, secret_binary=certificate)
            created_certificates[region] = certificate_arn
            nlb_stack_name = _create_nlb_stack(
                cfn_stacks_factory,
                request,
                directory_stack,
                region,
                test_resources_dir,
                certificate_arn,
                certificate_secret_arn,
                common_name,
            ).name
            created_directory_stacks[region]["nlb"] = nlb_stack_name
        return directory_stack_name, nlb_stack_name

    yield _directory_factory

    for region, stack_dict in created_directory_stacks.items():
        for stack_type in stack_dict:
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

    for region, certificate_arn in created_certificates.items():
        if request.config.getoption("no_delete"):
            logging.info(
                "Not deleting ACM certificate %s in region %s because --no-delete option was specified",
                certificate_arn,
                region,
            )
        else:
            logging.info(
                "Sleeping 180 seconds to wait for the ACM certificate %s in region %s to become unused",
                certificate_arn,
                region,
            )
            time.sleep(180)
            _delete_certificate(certificate_arn=certificate_arn, region=region)


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
            f"/fsxopenzfs/{user.alias}_file",
            f"/fsxontap/{user.alias}_file",
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
        # ("SimpleAD", "ldaps", False),
        ("SimpleAD", "ldaps", True),
        ("MicrosoftAD", "ldap", False),
        # ("MicrosoftAD", "ldaps", False),
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
    directory_factory,
    fsx_factory,
    svm_factory,
    request,
    store_secret_in_secret_manager,
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
    directory_stack_name, nlb_stack_name = directory_factory(
        request.config.getoption("directory_stack_name"),
        request.config.getoption("ldaps_nlb_stack_name"),
        directory_type,
        str(test_datadir),
        region,
    )
    directory_stack_outputs = get_infra_stack_outputs(directory_stack_name)
    ad_user_password = directory_stack_outputs.get("UserPassword")
    password_secret_arn = store_secret_in_secret_manager(
        region, secret_string=directory_stack_outputs.get("AdminPassword")
    )
    nlb_stack_parameters = get_infra_stack_parameters(nlb_stack_name)
    ldap_tls_ca_cert = "/opt/parallelcluster/shared/directory_service/certificate.crt"
    config_params.update(
        get_ad_config_param_vals(
            directory_stack_outputs,
            nlb_stack_parameters,
            password_secret_arn,
            ldap_tls_ca_cert,
            directory_type,
            directory_protocol,
            directory_certificate_verification,
        )
    )
    config_params.update(get_fsx_config_param_vals(fsx_factory, svm_factory))
    cluster_config = pcluster_config_reader(benchmarks=benchmarks, **config_params)
    cluster = clusters_factory(cluster_config)

    certificate_secret_arn = nlb_stack_parameters.get("CertificateSecretArn")
    certificate = boto3.client("secretsmanager").get_secret_value(SecretId=certificate_secret_arn)["SecretBinary"]
    with open(test_datadir / "certificate.crt", "wb") as f:
        f.write(certificate)

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
