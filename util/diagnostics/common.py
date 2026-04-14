import json
import logging
import re

# nosec B404: The subprocess module is used intentionally to run trusted system commands.
import subprocess  # nosec B404

import boto3
import yaml
from botocore.exceptions import ClientError

CHEF_DNA_JSON_FILE = "/etc/chef/dna.json"
LOCAL_CLUSTER_CONFIG_FILE = "/opt/parallelcluster/shared/cluster-config.yaml"


def setup_logging():
    """Set up common logging configuration for all diagnosis scripts."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    return logging.getLogger(__name__)


def print_success(message):
    print(f"\033[32m[✓] {message}\033[0m")


def print_failure(message):
    print(f"\033[31m[✗] {message}\033[0m")


def print_skipped(message):
    print(f"\033[33m[~] {message}\033[0m")


def read_dna_json():
    try:
        with open(CHEF_DNA_JSON_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to read {CHEF_DNA_JSON_FILE}: {str(e)}") from e


def parse_db_uri(uri):
    if ":" in uri:
        endpoint, port_str = uri.split(":", 1)
        return endpoint, int(port_str)
    else:
        return uri, 3306


def get_cluster_config_from_s3(region=None):
    try:
        dna = read_dna_json()
        bucket = dna["cluster"]["cluster_s3_bucket"]
        key = dna["cluster"]["cluster_config_s3_key"]
        version = dna["cluster"]["cluster_config_version"]

        s3 = boto3.client("s3", region_name=region) if region else boto3.client("s3")

        response = s3.get_object(Bucket=bucket, Key=key, VersionId=version)
        config = yaml.safe_load(response["Body"])

        print_success("Downloaded cluster configuration from S3")
        return config
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to get config from S3: {str(e)}") from e


def read_yaml(path):
    """Read a YAML file and return its contents as a dictionary."""
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to read YAML file {path}: {str(e)}") from e


def get_cluster_config_local():
    try:
        return read_yaml(LOCAL_CLUSTER_CONFIG_FILE)
    except RuntimeError:
        raise


def get_slurm_config_value(conf_file, property_name):
    try:
        # A nosec comment is appended to the following line in order to disable the B603 and B607 checks.
        # The command is constructed from a trusted, hardcoded path (conf_file) and a fixed executable (sudo, cat).
        result = subprocess.run(
            ["sudo", "cat", conf_file], capture_output=True, text=True, check=True
        )  # nosec B603 B607 nosemgrep
        content = result.stdout
        match = re.search(f"{property_name}=(.*?)(?:\n|$)", content)
        if match:
            return match.group(1)
        print_failure(f"{property_name} not found in configuration file")
        return None
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print_failure(f"Failed to read configuration file {conf_file}: {str(e)}")
        return None


def get_secret(secret_arn, region=None):
    try:
        session = boto3.session.Session()
        client = session.client(service_name="secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_arn)
        return response["SecretString"]
    except ClientError as e:
        print_failure(f"Failed to retrieve secret from AWS Secrets Manager: {str(e)}")
        return None
