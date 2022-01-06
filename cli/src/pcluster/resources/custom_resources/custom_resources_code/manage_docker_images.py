# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
#  the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import logging

import boto3
from crhelper import CfnResource

helper = CfnResource()
logger = logging.getLogger(__name__)


def trigger_codebuild(project_name):
    """
    Start a build for a specific CodeBuild project.

    :param project_name: name of the CodeBuild project to build.
    :return: the id of the started build.
    """
    codebuild_client = boto3.client("codebuild")
    """ :type : pyboto3.codebuild """
    response = codebuild_client.start_build(projectName=project_name)
    return response["build"]["id"]


def delete_all_ecr_images(ecr_repo):
    """
    Delete all container images that are present in the specified ECR repository.

    :param ecr_repo: name of the ECR repository.
    """
    ecr_client = boto3.client("ecr")
    """ :type : pyboto3.ecr """
    paginator = ecr_client.get_paginator("list_images")
    for page in paginator.paginate(repositoryName=ecr_repo):
        if "imageIds" in page and page["imageIds"]:
            ecr_client.batch_delete_image(repositoryName=ecr_repo, imageIds=page["imageIds"])


def create_docker_images(codebuild_project):
    """
    Start the build to create Docker images.

    :param codebuild_project: CodeBuild project that builds docker container images.
    """
    build_id = trigger_codebuild(codebuild_project)
    logger.info("Docker images creation: STARTED")
    logger.info("Build id: %s", build_id)
    return build_id


@helper.create
def create(event, _):
    """
    Place your code to handle Create events here.

    To return a failure to CloudFormation simply raise an exception,
    the exception message will be sent to CloudFormation Events.
    """
    project = event["ResourceProperties"]["CodeBuildProject"]
    build_id = create_docker_images(project)

    physical_resource_id = build_id
    response_data = {}
    return physical_resource_id, response_data


@helper.update
def update(event, _):
    """
    Place your code to handle Update events here.

    To return a failure to CloudFormation simply raise an exception,
    the exception message will be sent to CloudFormation Events.
    """
    project = event["ResourceProperties"]["CodeBuildProject"]
    build_id = create_docker_images(project)

    physical_resource_id = build_id
    response_data = {}
    return physical_resource_id, response_data


@helper.delete
def delete(event, _):
    """
    Place your code to handle Delete events here.

    To return a failure to CloudFormation simply raise an exception,
    the exception message will be sent to CloudFormation Events.
    """
    ecr_repo = event["ResourceProperties"]["EcrRepository"]
    logger.info("Docker images deletion: STARTED")
    delete_all_ecr_images(ecr_repo)
    logger.info("Docker images deletion: COMPLETED")


def handler(event, context):
    helper(event, context)
