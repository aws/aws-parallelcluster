# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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


import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import boto3
import pkg_resources
import pytest
import urllib3
from framework.fixture_utils import xdist_session_fixture

from tests.common.utils import get_installed_parallelcluster_version

logger = logging.getLogger()
NODE_VERSION = "v16.19.0"  # maintenance version compatible with alinux2's GLIBC


def install_pc(basepath, pc_version):
    """Install ParallelCluster to a temporary directory"""
    tempdir = Path(basepath) / "python"
    root = Path(pkg_resources.resource_filename(__name__, "/../.."))
    cli_dir = root / "cli"
    try:
        logger.info("installing ParallelCluster packages...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", f"{cli_dir}[awslambda]", "-t", tempdir])
        # The following are provided by the lambda runtime
        shutil.rmtree(tempdir / "botocore")
        shutil.rmtree(tempdir / "boto3")
    except subprocess.CalledProcessError:
        logger.info(f"Error while installing ParallelCluster {get_installed_parallelcluster_version()}")
        sys.exit(-1)


def install_node(basepath, node_version):
    """Install Node to a temporary directory"""
    node_root = f"node-{node_version}-linux-x64"
    node_file = f"{node_root}.tar.xz"
    node_url = f"https://nodejs.org/dist/{node_version}/{node_file}"
    logger.info(f"Node URL: {node_url}")

    logger.info(f"Retrieving Node {node_version}")
    http = urllib3.PoolManager()
    resp = http.request("GET", node_url)

    with tempfile.TemporaryDirectory() as nodetmp:
        with open(f"{nodetmp}/{node_file}", "wb") as fout:
            fout.write(resp.data)
            fout.close()

        with tarfile.open(f"{nodetmp}/{node_file}", mode="r:xz") as tar:
            tar.extractall(f"{nodetmp}/node_install")

        tempdir = Path(basepath) / "bin"
        os.makedirs(tempdir, exist_ok=True)
        shutil.copy(f"{nodetmp}/node_install/{node_root}/bin/node", tempdir / "node")


@pytest.fixture(scope="class", name="policies_uri")
def policies_uri_fixture(request, region, resource_bucket):
    if request.config.getoption("policies_uri"):
        yield request.config.getoption("policies_uri")
        return

    yield (
        f"https://{resource_bucket}.s3.{region}.amazonaws.com{'.cn' if region.startswith('cn') else ''}"
        f"/parallelcluster/{get_installed_parallelcluster_version()}/templates/policies/policies.yaml"
    )


def get_resource_map():
    version = get_installed_parallelcluster_version()
    prefix = f"parallelcluster/{version}"
    resources = {
        "api/infrastructure/parallelcluster-api.yaml": f"{prefix}/api/parallelcluster-api.yaml",
        "api/spec/openapi/ParallelCluster.openapi.yaml": f"{prefix}/api/ParallelCluster.openapi.yaml",
        "cloudformation/custom_resource/cluster.yaml": f"{prefix}/templates/custom_resource/cluster.yaml",
        "cloudformation/networking/public.cfn.json": f"{prefix}/templates/networking/public-{version}.cfn.json",
        "cloudformation/networking/public-private.cfn.json": (
            f"{prefix}/templates/networking/public-private-{version}.cfn.json"
        ),
        "cloudformation/policies/parallelcluster-policies.yaml": f"{prefix}/templates/policies/policies.yaml",
    }
    return resources


@xdist_session_fixture()
def resource_bucket_shared(request, s3_bucket_factory_shared, lambda_layer_source):
    root = Path(pkg_resources.resource_filename(__name__, "/../.."))
    if request.config.getoption("resource_bucket"):
        return  # short-circuit this fixture if a resource-bucket is provided

    for region, s3_bucket in s3_bucket_factory_shared.items():
        logger.info(f"Uploading artifacts to: {s3_bucket}[{region}]")
        s3_resource = boto3.resource("s3", region_name=region)
        for file, key in get_resource_map().items():
            logger.info(f"  {root / file} -> {s3_bucket}/{key}")
            s3_resource.Bucket(s3_bucket).upload_file(str(root / file), key)

        layer_key = (
            f"parallelcluster/{get_installed_parallelcluster_version()}/layers/aws-parallelcluster/lambda-layer.zip"
        )
        if lambda_layer_source:
            bucket, key = re.search(r"s3://([^/]*)/(.*)", lambda_layer_source).groups()
            source = {"Bucket": bucket, "Key": key}
            logger.info(f"Copying Lambda Layer from: s3://{bucket}/{key} -> s3://{s3_bucket}/{layer_key}")
            s3_resource.Bucket(s3_bucket).copy(source, layer_key)
        else:
            with tempfile.TemporaryDirectory() as basepath:
                install_pc(basepath, get_installed_parallelcluster_version())
                install_node(basepath, NODE_VERSION)

                with tempfile.NamedTemporaryFile(suffix=".zip") as zipfile:
                    zipfilename = Path(zipfile.name)
                    logger.info(f"    {zipfilename} -> {s3_bucket}/{layer_key}")
                    shutil.make_archive(zipfilename.with_suffix(""), format="zip", root_dir=basepath)
                    s3_resource.Bucket(s3_bucket).upload_file(str(zipfilename), layer_key)

    logger.info(s3_bucket_factory_shared)
    return s3_bucket_factory_shared


@pytest.fixture(scope="class")
def resource_bucket(request, region, resource_bucket_shared):
    if request.config.getoption("resource_bucket"):
        return request.config.getoption("resource_bucket").format(region=region)
    return resource_bucket_shared[region]
