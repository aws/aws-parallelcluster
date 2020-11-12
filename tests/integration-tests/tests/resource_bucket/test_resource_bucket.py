import logging

import boto3
import pytest
from assertpy import assert_that


@pytest.mark.regions(["us-east-2"])
@pytest.mark.schedulers(["slurm", "awsbatch"])
@pytest.mark.oss(["alinux"])
@pytest.mark.usefixtures("os", "instance")
def test_resource_bucket(region, scheduler, pcluster_config_reader, clusters_factory, s3_bucket_factory, test_datadir):
    # Bucket used to host cluster artifacts must have versioning enabled
    logging.info("Testing cluster creation/deletion behavior when specifying cluster_resource_bucket")
    bucket_name = s3_bucket_factory()
    # Upload a file to bucket, we will check to make sure this file is not removed when deleting cluster artifacts
    boto3.resource("s3").Bucket(bucket_name).upload_file(str(test_datadir / "s3_test_file"), "s3_test_file")

    cluster_config = pcluster_config_reader(
        config_file="pcluster.config_{0}.ini".format(scheduler), resource_bucket=bucket_name
    )
    cluster = clusters_factory(cluster_config)
    assert_that(cluster.cfn_outputs.get("ResourcesS3Bucket")).is_equal_to(bucket_name)
    artifact_directory = cluster.cfn_outputs.get("ArtifactS3RootDirectory")
    assert_that(artifact_directory).is_not_none()
    # Update cluster with a new resource bucket
    # We need to make sure the bucket name in cfn NEVER gets updated
    update_bucket_name = s3_bucket_factory()
    updated_config_file = pcluster_config_reader(
        config_file="pcluster.config_{0}.ini".format(scheduler), resource_bucket=update_bucket_name
    )
    cluster.config_file = str(updated_config_file)
    cluster.update()
    assert_that(cluster.cfn_outputs.get("ResourcesS3Bucket")).is_equal_to(bucket_name)
    assert_that(cluster.cfn_outputs.get("ArtifactS3RootDirectory")).is_equal_to(artifact_directory)

    cluster.delete()
    _check_delete_behavior(region, bucket_name, artifact_directory)


def _check_delete_behavior(region, bucket_name, artifact_directory):
    s3_client = boto3.client("s3", region_name=region)
    response = s3_client.list_objects_v2(Bucket=bucket_name, Delimiter="/", Prefix=artifact_directory)
    if response.get("Contents") or response.get("CommonPrefixes"):
        logging.error(
            "Objects under %s/%s not cleaned up properly!\nContents: %s\nCommonPrefixes: %s",
            bucket_name,
            artifact_directory,
            response.get("Contents"),
            response.get("CommonPrefixes"),
        )
        raise Exception
    try:
        s3_client.head_object(Bucket=bucket_name, Key="s3_test_file")
    except Exception as e:
        logging.error("Unable to verify pre-existing files in bucket are preserved, with error: %s", e)
        raise
