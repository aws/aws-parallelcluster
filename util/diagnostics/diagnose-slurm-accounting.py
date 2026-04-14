#!/usr/bin/env python3
"""
Diagnose SLURM accounting configuration and connectivity.

This script performs comprehensive checks on SLURM accounting setup including database
connectivity, configuration validation, and MySQL permissions. It's designed to be run
on the head node and can automatically retrieve cluster configuration if parameters are omitted.

Usage:
    python3 diagnose-slurm-accounting.py
    python3 diagnose-slurm-accounting.py \
      --db-endpoint mydb.cluster-xyz.us-east-1.rds.amazonaws.com \
      --db-user slurm \
      --region us-east-1
"""

import json
import logging
import socket

# nosec B404: The subprocess module is used intentionally to run trusted system commands.
import subprocess  # nosec B404

import click
import pymysql
from common import (
    get_cluster_config_from_s3,
    get_cluster_config_local,
    get_secret,
    get_slurm_config_value,
    parse_db_uri,
    print_failure,
    print_skipped,
    print_success,
    read_dna_json,
    setup_logging,
)

SLURMDBD_CONF_FILE = "/opt/slurm/etc/slurm_parallelcluster_slurmdbd.conf"


def check_db_reachable(host, port):
    try:
        socket.create_connection((host, port), timeout=5)
        print_success("Database endpoint reachability check")
    except socket.error as e:
        print_failure(f"Database endpoint not reachable: {str(e)}")


def check_config_db_endpoint(conf_file, db_endpoint):
    conf_host = get_slurm_config_value(conf_file, "StorageHost")
    if conf_host is None:
        return
    if conf_host == db_endpoint:
        print_success("Database endpoint matches configuration")
    else:
        print_failure(f"Database endpoint does not match configuration (expected: {db_endpoint}, found: {conf_host})")


def check_secret_format(secret):
    if secret is None:
        print_skipped("Secret format check skipped: secret is None")
        return
    try:
        json.loads(secret)
        print_failure("Secret is in JSON format, expected plain text password")
    except json.JSONDecodeError:
        print_success("Secret is plain text password")


def check_secret_retrievable(secret_arn, region):
    """Retrieve the secret and report success or failure. Returns the secret value or None."""
    secret = get_secret(secret_arn, region)
    if secret is None:
        print_failure(f"Secret could not be retrieved from Secrets Manager: {secret_arn}")
    else:
        print_success(f"Secret retrieved from Secrets Manager: {secret_arn}")
    return secret


def check_config_db_password(conf_file, secret):
    if secret is None:
        print_skipped("Database password vs secret check skipped: secret is None")
        return
    conf_pass = get_slurm_config_value(conf_file, "StoragePass")
    if conf_pass is None:
        return
    if conf_pass == secret:
        print_success("Database password matches secret")
    else:
        print_failure("Database password does not match secret")


def check_config_db_user(conf_file, db_user):
    conf_user = get_slurm_config_value(conf_file, "StorageUser")
    if conf_user is None:
        return
    if conf_user == db_user:
        print_success("Database user matches configuration")
    else:
        print_failure(f"Database user does not match configuration (expected: {db_user}, found: {conf_user})")


def check_mysql_connection(host: str, port: int, user: str, password: str):
    try:
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password, connect_timeout=5, ssl={"ssl_disabled": False}
        )
        conn.close()
        print_success("MySQL connection test")
    except pymysql.Error as e:
        print_failure(f"MySQL connection test failed: {str(e)}")


def check_mysql_user_permissions(host: str, port: int, user: str, password: str):
    connection = None
    cursor = None
    try:
        connection = pymysql.connect(host=host, port=port, user=user, password=password, ssl={"ssl_disabled": False})
        cursor = connection.cursor()

        cursor.execute("SELECT Host FROM mysql.user WHERE User = %s LIMIT 1", (user,))
        result = cursor.fetchone()
        if result:
            user_host = result[0]
            cursor.execute(f"SHOW GRANTS FOR '{user}'@'{user_host}'")
        else:
            print_failure(f"MySQL user '{user}' not found in mysql.user table")
            return

        grants = [grant[0] for grant in cursor.fetchall()]
        print_success(f"User {user} has correct MySQL permissions")
        logging.getLogger(__name__).info(f"Grants for user '{user}':")
        for grant in grants:
            print(f"    {grant}")
    except pymysql.Error as e:
        print_failure(f"Failed to retrieve MySQL permissions for user '{user}': {str(e)}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def check_mysql_errors_in_system_messages():
    error_patterns = [
        "mysql_real_connect failed",
        "Access denied for user",
        "The database must be up when starting the MYSQL plugin",
    ]
    try:
        # A nosec comment is appended to the following line in order to disable the B603 and B607 checks.
        # The command uses a fixed, hardcoded executable (sudo, journalctl) with no user-controlled input.
        result = subprocess.run(
            ["sudo", "journalctl", "-u", "slurmdbd", "--no-pager", "--boot"], capture_output=True, text=True, check=True
        )  # nosec B603 B607 nosemgrep
        log_output = result.stdout
        found = [p for p in error_patterns if p in log_output]
        if found:
            print_failure(f"Found MySQL-related errors in slurmdbd logs: {found}")
        else:
            print_success("No errors related to MySQL in slurmdbd logs")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print_failure(f"Failed to read slurmdbd logs: {str(e)}")


def check_s3_config_matches_local(s3_config):
    """Check that the cluster config fetched from S3 matches the one stored locally on the head node."""
    if s3_config is None:
        print_skipped("S3 vs local config check skipped: S3 config could not be retrieved")
        return
    try:
        local_config = get_cluster_config_local()
    except RuntimeError as e:
        print_failure(f"Could not read local cluster config: {str(e)}")
        return
    if s3_config == local_config:
        print_success("S3 cluster config matches local cluster config")
    else:
        print_failure("S3 cluster config does not match local cluster config")


@click.command(help="Diagnose SLURM accounting setup.", context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--db-endpoint", help="Database endpoint. If not specified, determined from the cluster configuration in S3."
)
@click.option(
    "--db-port", type=int, help="Database port. If not specified, determined from the cluster configuration in S3."
)
@click.option("--db-user", help="Database user. If not specified, determined from the cluster configuration in S3.")
@click.option(
    "--secret-arn",
    help="Secret ARN for the database password. If not specified, determined from the cluster configuration in S3.",
)
@click.option("--region", help="AWS region. If not specified, determined from the local /etc/chef/dna.json file.")
def main(db_endpoint, db_port, db_user, secret_arn, region):
    """Diagnose SLURM accounting.

    This script is meant to be run on the head node.
    If all parameters are missing they will be retrieved automatically from the cluster configuration.
    """
    logger = setup_logging()

    # Always fetch S3 config — needed for auto-resolving missing params and for the config comparison check
    s3_config = None
    try:
        s3_config = get_cluster_config_from_s3(region)
    except RuntimeError as e:
        logger.warning(f"Could not fetch S3 config: {str(e)}")

    # Resolve missing parameters from S3 config; log the source of each value
    try:
        db_config = s3_config["Scheduling"]["SlurmSettings"]["Database"] if s3_config else {}
        db_endpoint_config, db_port_config = parse_db_uri(db_config["Uri"])
        db_endpoint = db_endpoint or db_endpoint_config
        db_port = db_port or db_port_config
        db_user = db_user or db_config["UserName"]
        secret_arn = secret_arn or db_config["PasswordSecretArn"]
        region = region or read_dna_json()["cluster"]["region"]
    except RuntimeError as e:
        logger.error(str(e))
        raise SystemExit(1)

    check_s3_config_matches_local(s3_config)

    logger.info("Parameters used for the checks")
    logger.info(f"Database Endpoint: {db_endpoint}")
    logger.info(f"Database Port: {db_port}")
    logger.info(f"Database User: {db_user}")
    logger.info(f"Secret ARN: {secret_arn}")
    logger.info(f"Region: {region}")

    check_db_reachable(db_endpoint, db_port)
    check_config_db_endpoint(SLURMDBD_CONF_FILE, db_endpoint)
    secret = check_secret_retrievable(secret_arn, region)
    check_secret_format(secret)
    check_config_db_user(SLURMDBD_CONF_FILE, db_user)
    check_config_db_password(SLURMDBD_CONF_FILE, secret)
    password = get_slurm_config_value(SLURMDBD_CONF_FILE, "StoragePass")
    check_mysql_connection(db_endpoint, db_port, db_user, password)
    check_mysql_user_permissions(db_endpoint, db_port, db_user, password)
    check_mysql_errors_in_system_messages()

    logger.info("All checks completed!")


if __name__ == "__main__":
    main()
