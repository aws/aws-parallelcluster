import logging
import os

import boto3
from crhelper import CfnResource

CODEBUILD_BUILD_ID_KEY = "CodeBuildBuildId"
helper = CfnResource(json_logging=False, log_level="INFO")


def trigger_codebuild_project(**kwargs):
    """Trigger CodeBuild projects using the given configuration."""
    codebuild_client = boto3.client("codebuild", region_name=os.environ["AWS_REGION"])
    response = codebuild_client.start_build(**kwargs)
    logging.info(
        "Started build #%s of CodeBuild project %s with ID %s",
        response.get("build", {}).get("buildNumber"),
        response.get("build").get("projectName"),
        response.get("build").get("id"),
    )
    return response


def get_build_status(build_id):
    """Get the status of specified build of a CodeBuild project."""
    codebuild_client = boto3.client("codebuild", region_name=os.environ["AWS_REGION"])
    response = codebuild_client.batch_get_builds(ids=[build_id])
    logging.info(f"detailed status for build {build_id}:\n{response}")
    return response.get("builds")[0].get("buildStatus")


@helper.create
def on_create(event, context):
    logging.info(event)
    props = event["ResourceProperties"]
    physical_id = trigger_codebuild_project(projectName=props["codebuild_project_name"]).get("build").get("id")
    helper.Data.update({CODEBUILD_BUILD_ID_KEY: physical_id})
    return physical_id


@helper.update
def on_update(event, context):
    physical_id = event["PhysicalResourceId"]
    props = event["ResourceProperties"]
    old_props = event["OldResourceProperties"]
    logging.info(f"Not updating resource {physical_id} with {props=}, {old_props=}. Not implemented yet.")
    return physical_id


@helper.delete
def on_delete(event, context):
    physical_id = event["PhysicalResourceId"]
    logging.info(f"Nothing to do to delete resource {physical_id}.")


@helper.poll_create
def is_complete(event, context):
    logging.info(event)
    is_ready = False

    build_id = helper.Data.get(CODEBUILD_BUILD_ID_KEY)
    build_status = get_build_status(build_id)
    success_statuses = ["SUCCEEDED"]
    failure_statuses = ["FAILED", "FAULT", "TIMED_OUT"]
    if build_status in success_statuses:
        is_ready = True
    elif build_status in failure_statuses:
        logging.info(f"Build {build_id} failed with status {build_status}")
        is_ready = True
    else:
        logging.info(f"Build {build_id} has unanticipated status {build_status}")
        is_ready = False

    return is_ready


def handler(event, context):
    helper(event, context)
