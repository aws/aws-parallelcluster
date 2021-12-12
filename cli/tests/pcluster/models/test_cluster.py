# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import datetime
import json
from io import BytesIO
from unittest.mock import PropertyMock

import pytest
import yaml
from assertpy import assert_that
from botocore.response import StreamingBody
from dateutil import tz

from pcluster.api.models import ClusterStatus
from pcluster.aws.common import AWSClientError
from pcluster.config.cluster_config import Tag
from pcluster.config.common import AllValidatorsSuppressor
from pcluster.constants import PCLUSTER_CLUSTER_NAME_TAG, PCLUSTER_S3_ARTIFACTS_DICT
from pcluster.models.cluster import (
    BadRequestClusterActionError,
    Cluster,
    ClusterActionError,
    ClusterUpdateError,
    NodeType,
)
from pcluster.models.cluster_resources import ClusterStack
from pcluster.models.s3_bucket import S3Bucket, S3FileFormat
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.config.dummy_cluster_config import dummy_slurm_cluster_config
from tests.pcluster.models.dummy_s3_bucket import mock_bucket, mock_bucket_object_utils, mock_bucket_utils
from tests.pcluster.test_utils import FAKE_NAME

LOG_GROUP_TYPE = "AWS::Logs::LogGroup"
ARTIFACT_DIRECTORY = "s3_artifacts_dir"


class TestCluster:
    @pytest.fixture()
    def cluster(self, mocker):
        mocker.patch(
            "pcluster.models.cluster.Cluster.bucket",
            new_callable=PropertyMock(
                return_value=S3Bucket(
                    service_name=FAKE_NAME, stack_name=FAKE_NAME, artifact_directory=ARTIFACT_DIRECTORY
                )
            ),
        )
        return Cluster(
            FAKE_NAME, stack=ClusterStack({"StackName": FAKE_NAME, "CreationTime": "2021-06-04 10:23:20.199000+00:00"})
        )

    @pytest.mark.parametrize(
        "node_type, expected_response, expected_instances",
        [
            (NodeType.HEAD_NODE, [{}], 1),
            (NodeType.COMPUTE, [{}, {}, {}], 3),
            (NodeType.COMPUTE, [{}, {}], 2),
            (NodeType.COMPUTE, [], 0),
        ],
    )
    def test_describe_instances(self, cluster, mocker, node_type, expected_response, expected_instances):
        mock_aws_api(mocker)
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.describe_instances",
            return_value=(expected_response, None),
            expected_params=[
                {"Name": f"tag:{PCLUSTER_CLUSTER_NAME_TAG}", "Values": ["test-cluster"]},
                {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
                {"Name": "tag:parallelcluster:node-type", "Values": [node_type.value]},
            ],
        )

        instances, _ = cluster.describe_instances(node_type=node_type)
        assert_that(instances).is_length(expected_instances)

    @pytest.mark.parametrize(
        "existing_tags", [({}), ({"test": "testvalue"}), ({"Version": "OldVersionToBeOverridden"})]
    )
    def test_tags(self, cluster, mocker, existing_tags):
        """Verify that the function to get the tags list behaves as expected."""
        mock_aws_api(mocker)
        cluster.config = dummy_slurm_cluster_config(mocker)

        # Populate config with list of existing tags
        existing_tags_list = [Tag(key=tag_name, value=tag_value) for tag_name, tag_value in existing_tags.items()]
        cluster.config.tags = existing_tags_list

        # Expected tags:
        installed_version = "FakeInstalledVersion"
        tags = existing_tags
        tags["parallelcluster:version"] = installed_version
        expected_tags_list = self._sort_tags(
            [Tag(key=tag_name, value=tag_value) for tag_name, tag_value in tags.items()]
        )

        # Test method to add version tag
        get_version_patch = mocker.patch(
            "pcluster.models.cluster.get_installed_version", return_value=installed_version
        )
        cluster._add_version_tag()
        assert_that(get_version_patch.call_count).is_equal_to(1)
        assert_that(len(cluster.config.tags)).is_equal_to(len(expected_tags_list))
        assert_that(
            all(
                [
                    source.value == target.value
                    for source, target in zip(self._sort_tags(cluster.config.tags), expected_tags_list)
                ]
            )
        ).is_true()

        # Test method to retrieve CFN tags
        expected_cfn_tags = self._sort_cfn_tags(
            [{"Key": tag_name, "Value": tag_value} for tag_name, tag_value in tags.items()]
        )
        cfn_tags = self._sort_cfn_tags(cluster._get_cfn_tags())
        assert_that(len(cfn_tags)).is_equal_to(len(expected_cfn_tags))
        assert_that(
            all([source["Value"] == target["Value"] for source, target in zip(cfn_tags, expected_cfn_tags)])
        ).is_true()

    @staticmethod
    def _sort_tags(tags):
        return sorted(tags, key=lambda tag: tag.key)

    @staticmethod
    def _sort_cfn_tags(tags):
        return sorted(tags, key=lambda tag: tag["Key"])

    @pytest.mark.parametrize(
        "stack_statuses",
        [
            [
                "UPDATE_IN_PROGRESS",
                "UPDATE_IN_PROGRESS",
                "UPDATE_IN_PROGRESS",
                "UPDATE_IN_PROGRESS",
                "UPDATE_COMPLETE",
                "UPDATE_COMPLETE",
            ],
            [
                "UPDATE_IN_PROGRESS",
                "UPDATE_IN_PROGRESS",
                "UPDATE_IN_PROGRESS",
                "UPDATE_IN_PROGRESS",
                "anything other than UPDATE_IN_PROGRESS",
                "anything other than UPDATE_IN_PROGRESS",
            ],
            [
                "UPDATE_IN_PROGRESS",
                "UPDATE_IN_PROGRESS",
                "UPDATE_IN_PROGRESS",
                "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
                "UPDATE_COMPLETE",
            ],
            ["UPDATE_COMPLETE", "UPDATE_COMPLETE"],
        ],
    )
    def test_wait_for_stack_update(self, cluster, mocker, stack_statuses):
        """
        Verify that _wait_for_stack_update behaves as expected.

        _wait_for_stack_update should call updated_status until the StackStatus is anything besides UPDATE_IN_PROGRESS
        and UPDATE_COMPLETE_CLEANUP_IN_PROGRESS.
        use that to get expected call count for updated_status
        """
        expected_call_count = len(stack_statuses)
        updated_status_mock = mocker.patch.object(cluster, "_get_updated_stack_status", side_effect=stack_statuses)
        mocker.patch("pcluster.models.cluster.time.sleep")  # so we don't actually have to wait

        cluster._wait_for_stack_update()
        assert_that(updated_status_mock.call_count).is_equal_to(expected_call_count)

    @pytest.mark.parametrize(
        "template_body,error_message",
        [
            ({"TemplateKey": "TemplateValue"}, None),
            ({}, "Unable to retrieve template for stack {0}.*".format(FAKE_NAME)),
            (None, "Unable to retrieve template for stack {0}.*".format(FAKE_NAME)),
        ],
    )
    def test_get_stack_template(self, cluster, mocker, template_body, error_message):
        """Verify that _get_stack_template method behaves as expected."""
        response = json.dumps(template_body) if template_body is not None else error_message
        mock_aws_api(mocker)
        mocker.patch(
            "pcluster.aws.cfn.CfnClient.get_stack_template",
            return_value=response,
            expected_params=FAKE_NAME,
            side_effect=AWSClientError(function_name="get_template", message="error") if not template_body else None,
        )

        if error_message:
            with pytest.raises(ClusterActionError, match=error_message):
                _ = cluster._get_stack_template()
        else:
            assert_that(cluster._get_stack_template()).is_equal_to(yaml.safe_load(response))

    @pytest.mark.parametrize(
        "error_message",
        [
            None,
            "No UpDatES ARE TO BE PERformed",
            "some longer message also containing no updates are to be performed and more words at the end"
            "some other error message",
        ],
    )
    def test_update_stack_template(self, cluster, mocker, error_message):
        """Verify that _update_stack_template behaves as expected."""
        template_body = {"TemplateKey": "TemplateValue"}
        template_url = "https://{bucket_name}.s3.{region}.amazonaws.com{partition_suffix}/{template_key}"
        response = error_message or {"StackId": "stack ID"}

        mock_aws_api(mocker)
        mocker.patch("pcluster.aws.cfn.CfnClient.get_stack_template", return_value=template_body)
        mocker.patch(
            "pcluster.aws.cfn.CfnClient.update_stack_from_url",
            return_value=response,
            expected_params={
                "stack_name": FAKE_NAME,
                "template_url": template_url,
            },
            side_effect=AWSClientError(function_name="update_stack_from_url", message=error_message)
            if error_message is not None
            else None,
        )

        # mock bucket initialize
        mock_bucket(mocker)
        # mock bucket utils
        mock_bucket_utils(mocker)
        # mock bucket object utils
        mock_bucket_object_utils(mocker)

        wait_for_update_mock = mocker.patch.object(cluster, "_wait_for_stack_update")

        if error_message is None or "no updates are to be performed" in error_message.lower():
            cluster._update_stack_template(template_body)
            if error_message is None or "no updates are to be performed" not in error_message.lower():
                assert_that(wait_for_update_mock.called).is_true()
            else:
                assert_that(wait_for_update_mock.called).is_false()
        else:
            full_error_message = "Unable to update stack template for stack {stack_name}: {emsg}".format(
                stack_name=FAKE_NAME, emsg=error_message
            )
            with pytest.raises(AWSClientError, match=full_error_message) as sysexit:
                cluster._update_stack_template(template_url)
            assert_that(sysexit.value.code).is_not_equal_to(0)

    @pytest.mark.parametrize(
        "keep_logs,persist_called,terminate_instances_called",
        [
            (False, False, True),
            (False, False, True),
            (True, True, True),
        ],
    )
    def test_delete(self, cluster, mocker, keep_logs, persist_called, terminate_instances_called):
        """Verify that delete behaves as expected."""
        mocker.patch.object(cluster.stack, "delete")
        mock_aws_api(mocker)
        mocker.patch("pcluster.aws.cfn.CfnClient.describe_stack")
        mocker.patch("pcluster.aws.cfn.CfnClient.delete_stack")
        persist_cloudwatch_log_groups_mock = mocker.patch.object(cluster, "_persist_cloudwatch_log_groups")

        cluster.delete(keep_logs)

        assert_that(persist_cloudwatch_log_groups_mock.called).is_equal_to(persist_called)

    @pytest.mark.parametrize(
        "template, expected_retain, fail_on_persist",
        [
            ({}, False, False),
            (
                {"Resources": {"key": {"DeletionPolicy": "Retain"}}},
                True,
                False,
            ),
            (
                {"Resources": {"key": {"DeletionPolicy": "Retain"}}},
                True,
                True,
            ),
            (
                {"Resources": {"key": {"DeletionPolicy": "Don't Retain"}}},
                False,
                False,
            ),
            (
                {"Resources": {"key": {"DeletionPolicy": "Delete"}}},
                False,
                False,
            ),
        ],
    )
    def test_persist_cloudwatch_log_groups(self, cluster, mocker, caplog, template, expected_retain, fail_on_persist):
        """Verify that _persist_cloudwatch_log_groups behaves as expected."""
        mocker.patch("pcluster.models.cluster.Cluster._get_artifact_dir")
        mocker.patch("pcluster.models.cluster.Cluster._get_stack_template", return_value=template)

        client_error = AWSClientError("function", "Generic error.")
        update_template_mock = mocker.patch.object(
            cluster, "_update_stack_template", side_effect=client_error if fail_on_persist else None
        )
        mock_aws_api(mocker)
        mocker.patch("pcluster.aws.cfn.CfnClient.update_stack_from_url")
        mock_bucket(mocker)
        mock_bucket_utils(mocker)
        mock_bucket_object_utils(mocker)

        if expected_retain:
            keys = ["key"]
        else:
            keys = []
        get_unretained_cw_log_group_resource_keys_mock = mocker.patch.object(
            cluster, "_get_unretained_cw_log_group_resource_keys", return_value=keys
        )

        if fail_on_persist:
            with pytest.raises(ClusterActionError) as e:
                cluster._persist_cloudwatch_log_groups()
            assert_that(str(e)).contains("Unable to persist logs")
        else:
            cluster._persist_cloudwatch_log_groups()

        assert_that(get_unretained_cw_log_group_resource_keys_mock.call_count).is_equal_to(1)
        assert_that(update_template_mock.call_count).is_equal_to(1 if expected_retain else 0)

    @pytest.mark.parametrize(
        "template",
        [
            {},
            {"Resources": {}},
            {"Resources": {"key": {}}},
            {"Resources": {"key": {"DeletionPolicy": "Don't Retain"}}},
            {"Resources": {"key": {"DeletionPolicy": "Delete"}}},
            {"Resources": {"key": {"DeletionPolicy": "Retain"}}},  # Note update_stack_template still called for this
        ],
    )
    def test_persist_stack_resources(self, cluster, mocker, template):
        """Verify that _persist_stack_resources behaves as expected."""
        mocker.patch("pcluster.models.cluster.Cluster._get_artifact_dir")
        mocker.patch("pcluster.models.cluster.Cluster._get_stack_template", return_value=template)
        update_stack_template_mock = mocker.patch("pcluster.models.cluster.Cluster._update_stack_template")
        mock_aws_api(mocker)
        mocker.patch("pcluster.aws.cfn.CfnClient.update_stack_from_url")
        mock_bucket(mocker)
        mock_bucket_utils(mocker)
        mock_bucket_object_utils(mocker)

        if "Resources" not in template:
            expected_error_message = "Resources"
        elif "key" not in template.get("Resources"):
            expected_error_message = "key"
        else:
            expected_error_message = None

        if expected_error_message:
            with pytest.raises(KeyError, match=expected_error_message):
                cluster._persist_stack_resources(["key"])
            assert_that(update_stack_template_mock.called).is_false()
        else:
            cluster._persist_stack_resources(["key"])
            assert_that(update_stack_template_mock.called).is_true()
            assert_that(cluster._get_stack_template()["Resources"]["key"]["DeletionPolicy"]).is_equal_to("Retain")

    @pytest.mark.parametrize(
        "template,expected_return",
        [
            ({}, []),
            ({"Resources": {}}, []),
            ({"Resources": {"ResourceOne": {"Type": LOG_GROUP_TYPE, "DeletionPolicy": "Retain"}}}, []),
            ({"Resources": {"ResourceOne": {"Type": LOG_GROUP_TYPE, "DeletionPolicy": "NotRetain"}}}, ["ResourceOne"]),
            ({"Resources": {"ResourceOne": {"Type": LOG_GROUP_TYPE, "DeletionPolicy": "Delete"}}}, ["ResourceOne"]),
        ],
    )
    def test_get_unretained_cw_log_group_resource_keys(self, cluster, mocker, template, expected_return):
        """Verify that _get_unretained_cw_log_group_resource_keys behaves as expected."""
        mocker.patch("pcluster.models.cluster.Cluster._get_stack_template", return_value=template)
        observed_return = cluster._get_unretained_cw_log_group_resource_keys()
        assert_that(observed_return).is_equal_to(expected_return)

    @pytest.mark.parametrize(
        "stack_exists, expected_error, next_token",
        [
            (False, "Cluster .* does not exist", None),
            (True, "", None),
            (True, "", "next_token"),
        ],
    )
    def test_get_stack_events(self, cluster, mocker, set_env, stack_exists, expected_error, next_token):
        set_env("AWS_DEFAULT_REGION", "us-east-2")
        mock_events = {
            "NextToken": "nxttkn",
            "ResponseMetadata": {
                "HTTPHeaders": {
                    "content-length": "1234",
                    "content-type": "text/xml",
                    "date": "Sun, 25 Jul 2021 21:49:36 GMT",
                    "vary": "accept-encoding",
                    "x-amzn-requestid": "00000000-0000-0000-aaaa-010101010101",
                },
                "HTTPStatusCode": 200,
                "RequestId": "00000000-0000-0000-aaaa-010101010101",
                "RetryAttempts": 0,
            },
            "StackEvents": [
                {
                    "EventId": "44444444-eeee-1111-aaaa-000000000000",
                    "LogicalResourceId": "pc",
                    "PhysicalResourceId": "arn:aws:cloudformation:us-east-1:000000000000:stack/pc",
                    "ResourceStatus": "UPDATE_COMPLETE",
                    "ResourceType": "AWS::CloudFormation::Stack",
                    "StackId": "arn:aws:cloudformation:us-east-1:000000000000:stack/pc",
                    "StackName": "pc",
                    "Timestamp": datetime.datetime(2021, 7, 13, 2, 20, 20, 000000, tzinfo=tz.tzutc()),
                }
            ],
        }
        stack_exists_mock = mocker.patch("pcluster.aws.cfn.CfnClient.stack_exists", return_value=stack_exists)
        stack_events_mock = mocker.patch("pcluster.aws.cfn.CfnClient.get_stack_events", return_value=mock_events)
        if not stack_exists:
            with pytest.raises(ClusterActionError, match=expected_error):
                cluster.get_stack_events(next_token)
            stack_exists_mock.assert_called_with(cluster.stack_name)
        else:
            events = cluster.get_stack_events(next_token)
            stack_exists_mock.assert_called_with(cluster.stack_name)
            stack_events_mock.assert_called_with(cluster.stack_name, next_token=next_token)
            assert_that(events).is_equal_to(mock_events)

    @pytest.mark.parametrize(
        "stack_exists, logging_enabled, expected_error, kwargs",
        [
            (False, False, "Cluster .* does not exist", {}),
            (True, False, "", {}),
            (True, True, "", {}),
            (True, True, "", {"keep_s3_objects": True}),
            (True, True, "", {"output_file": "path"}),
            (True, True, "", {"bucket_prefix": "test_prefix"}),
        ],
    )
    def test_export_logs(
        self,
        cluster,
        mocker,
        set_env,
        stack_exists,
        logging_enabled,
        expected_error,
        kwargs,
    ):
        mock_aws_api(mocker)
        set_env("AWS_DEFAULT_REGION", "us-east-2")
        stack_exists_mock = mocker.patch("pcluster.aws.cfn.CfnClient.stack_exists", return_value=stack_exists)
        download_stack_events_mock = mocker.patch("pcluster.models.cluster.export_stack_events")
        create_logs_archive_mock = mocker.patch("pcluster.models.cluster.create_logs_archive")
        upload_archive_mock = mocker.patch("pcluster.models.cluster.upload_archive")
        presign_mock = mocker.patch("pcluster.models.cluster.create_s3_presigned_url")
        mocker.patch(
            "pcluster.models.cluster.ClusterStack.log_group_name",
            new_callable=PropertyMock(return_value="log-group-name" if logging_enabled else None),
        )

        # Following mocks are used only if CW loggins is enabled
        logs_filter_mock = mocker.patch(
            "pcluster.models.cluster.Cluster._init_export_logs_filters",
            return_value=_MockExportClusterLogsFiltersParser(),
        )
        cw_logs_exporter_mock = mocker.patch("pcluster.models.cluster.CloudWatchLogsExporter", autospec=True)

        kwargs.update({"bucket": "bucket_name"})
        if expected_error:
            with pytest.raises(ClusterActionError, match=expected_error):
                cluster.export_logs(**kwargs)
        else:
            cluster.export_logs(**kwargs)
            # check archive steps
            download_stack_events_mock.assert_called()
            create_logs_archive_mock.assert_called()

            # check preliminary steps
            stack_exists_mock.assert_called_with(cluster.stack_name)

            if logging_enabled:
                cw_logs_exporter_mock.assert_called()
                logs_filter_mock.assert_called()
            else:
                cw_logs_exporter_mock.assert_not_called()
                logs_filter_mock.assert_not_called()

            if "output_file" not in kwargs:
                print("kwargs", kwargs)
                upload_archive_mock.assert_called()
                presign_mock.assert_called()

    @pytest.mark.parametrize(
        "stack_exists, logging_enabled, client_error, expected_error",
        [
            (False, False, False, "Cluster .* does not exist"),
            (True, False, False, "CloudWatch logging is not enabled"),
            (True, True, True, "Unexpected error when retrieving"),
            (True, True, False, ""),
        ],
    )
    def test_list_log_streams(
        self,
        cluster,
        mocker,
        set_env,
        stack_exists,
        logging_enabled,
        client_error,
        expected_error,
    ):
        mock_aws_api(mocker)
        set_env("AWS_DEFAULT_REGION", "us-east-2")
        stack_exists_mock = mocker.patch("pcluster.aws.cfn.CfnClient.stack_exists", return_value=stack_exists)
        describe_logs_mock = mocker.patch(
            "pcluster.aws.logs.LogsClient.describe_log_streams",
            side_effect=AWSClientError("describe_log_streams", "error") if client_error else None,
        )
        mocker.patch(
            "pcluster.models.cluster.Cluster._init_list_logs_filters", return_value=_MockListClusterLogsFiltersParser()
        )
        mocker.patch(
            "pcluster.models.cluster.ClusterStack.log_group_name",
            new_callable=PropertyMock(return_value="log-group-name" if logging_enabled else None),
        )

        if expected_error or client_error:
            with pytest.raises(ClusterActionError, match=expected_error):
                cluster.list_log_streams()
        else:
            cluster.list_log_streams()
            if logging_enabled:
                describe_logs_mock.assert_called()

        # check preliminary steps
        stack_exists_mock.assert_called_with(cluster.stack_name)

    @pytest.mark.parametrize(
        "log_stream_name, stack_exists, logging_enabled, client_error, expected_error",
        [
            ("log-group-name", False, False, False, "Cluster .* does not exist"),
            ("log-group-name", True, False, False, "CloudWatch logging is not enabled"),
            ("log-group-name", True, True, True, "Unexpected error when retrieving log events"),
            ("log-group-name", True, True, False, ""),
        ],
    )
    def test_get_log_events(
        self,
        cluster,
        mocker,
        set_env,
        log_stream_name,
        stack_exists,
        logging_enabled,
        client_error,
        expected_error,
    ):
        mock_aws_api(mocker)
        set_env("AWS_DEFAULT_REGION", "us-east-2")
        stack_exists_mock = mocker.patch("pcluster.aws.cfn.CfnClient.stack_exists", return_value=stack_exists)
        if not logging_enabled:
            get_log_events_mock = mocker.patch(
                "pcluster.aws.logs.LogsClient.get_log_events",
                side_effect=AWSClientError("get_log_events", "The specified log group doesn't exist"),
            )
        elif client_error:
            get_log_events_mock = mocker.patch(
                "pcluster.aws.logs.LogsClient.get_log_events",
                side_effect=AWSClientError("get_log_events", "error"),
            )
        else:
            get_log_events_mock = mocker.patch("pcluster.aws.logs.LogsClient.get_log_events", side_effect=None)

        mocker.patch(
            "pcluster.models.cluster.ClusterStack.log_group_name",
            new_callable=PropertyMock(return_value="log-group-name" if logging_enabled else None),
        )

        if expected_error or client_error:
            with pytest.raises(ClusterActionError, match=expected_error):
                cluster.get_log_events(log_stream_name)
        else:
            cluster.get_log_events(log_stream_name)
            get_log_events_mock.assert_called()

        stack_exists_mock.assert_called_with(cluster.stack_name)

    @pytest.mark.parametrize("force", [False, True])
    def test_validate_empty_change_set(self, mocker, force):
        mock_aws_api(mocker)
        cluster = Cluster(
            FAKE_NAME,
            stack=ClusterStack(
                {
                    "StackName": FAKE_NAME,
                    "CreationTime": "2021-06-04 10:23:20.199000+00:00",
                    "StackStatus": ClusterStatus.CREATE_COMPLETE,
                }
            ),
            config=OLD_CONFIGURATION,
        )

        mocker.patch("pcluster.aws.cfn.CfnClient.stack_exists", return_value=True)

        if force:
            _, changes, _ = cluster.validate_update_request(
                target_source_config=OLD_CONFIGURATION,
                validator_suppressors={AllValidatorsSuppressor()},
                force=force,
            )
            assert_that(changes).is_length(1)
        else:
            with pytest.raises(BadRequestClusterActionError, match="No changes found in your cluster configuration."):
                cluster.validate_update_request(
                    target_source_config=OLD_CONFIGURATION,
                    validator_suppressors={AllValidatorsSuppressor()},
                    force=force,
                )

    @pytest.mark.parametrize("template_url", ["s3://bucketname/bucketkey", "https://test"])
    def test_render_and_upload_scheduler_plugin_template(self, mocker, cluster, template_url):
        scheduler_plugin_template = "Test"
        scheduler_plugin_template_encoded = scheduler_plugin_template.encode("utf-8")
        if template_url.startswith("s3://"):
            mocker.patch(
                "pcluster.aws.s3.S3Client.get_object",
                autospec=True,
                return_value={
                    "Body": StreamingBody(
                        BytesIO(scheduler_plugin_template_encoded), len(scheduler_plugin_template_encoded)
                    )
                },
            )
        else:
            file_mock = mocker.MagicMock()
            file_mock.read.return_value.decode.return_value = scheduler_plugin_template
            mocker.patch("pcluster.models.cluster.urlopen").return_value.__enter__.return_value = file_mock
        mocker.patch("pcluster.models.cluster.parse_config", return_value={"Test"})
        mocker.patch("pcluster.models.cluster.Cluster.source_config_text", new_callable=PropertyMock)
        cluster_config_mock = mocker.patch("pcluster.models.cluster.Cluster.config", new_callable=PropertyMock)
        cluster_config_mock.return_value.scheduling.settings.scheduler_definition.cluster_infrastructure.cloud_formation.template = (  # noqa
            template_url
        )
        cluster_config_mock.return_value.get_instance_types_data.return_value = {"t2.micro": "instance_info"}
        upload_cfn_template_mock = mocker.patch.object(cluster.bucket, "upload_cfn_template", autospec=True)

        cluster._render_and_upload_scheduler_plugin_template()

        upload_cfn_template_mock.assert_called_with(
            scheduler_plugin_template, PCLUSTER_S3_ARTIFACTS_DICT["scheduler_plugin_template_name"], S3FileFormat.TEXT
        )

    @pytest.mark.parametrize(
        "support_update, instance_type, match",
        [
            (
                "false",
                "c5.xlarge",
                "Update failure: The scheduler plugin used for this cluster does not support updating the scheduling "
                "configuration.",
            ),
            ("false", "c5.2xlarge", None),
            ("true", "c5.xlarge", None),
        ],
    )
    def test_validate_scheduling_update(self, mocker, support_update, instance_type, match):
        plugin_old_configuration = f"""
Image:
  Os: alinux2
  CustomAmi: ami-08cf50b131bcd4db2
HeadNode:
  InstanceType: t2.micro
  Networking:
    SubnetId: subnet-08a5068070f6bc23d
  Ssh:
    KeyName: ermann-dub-ef
  Iam:
    AdditionalIamPolicies:
      - Policy: arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess
Scheduling:
  Scheduler: plugin
  SchedulerSettings:
    SchedulerDefinition:
      PluginInterfaceVersion: "1.0"
      Requirements:
        SupportsClusterUpdate: {support_update}
      Events:
        HeadInit:
          ExecuteCommand:
            Command: env
  SchedulerQueues:
    - Name: queue1
      Networking:
        SubnetIds:
          - subnet-12345678
      ComputeResources:
        - Name: compute-resource1
          InstanceType: c5.2xlarge
"""

        plugin_new_configuration = f"""
Image:
  Os: alinux2
  CustomAmi: ami-08cf50b131bcd4db2
HeadNode:
  InstanceType: t2.micro
  Networking:
    SubnetId: subnet-08a5068070f6bc23d
  Ssh:
    KeyName: ermann-dub-ef
  Iam:
    AdditionalIamPolicies:
      - Policy: arn:aws:iam::aws:policy/FakePolicy
Scheduling:
  Scheduler: plugin
  SchedulerSettings:
    SchedulerDefinition:
      PluginInterfaceVersion: "1.0"
      Requirements:
        SupportsClusterUpdate: {support_update}
      Events:
        HeadInit:
          ExecuteCommand:
            Command: env
  SchedulerQueues:
    - Name: queue1
      Networking:
        SubnetIds:
          - subnet-12345678
      ComputeResources:
        - Name: compute-resource1
          InstanceType: {instance_type}
"""

        mock_aws_api(mocker)
        cluster = Cluster(
            FAKE_NAME,
            stack=ClusterStack(
                {
                    "StackName": FAKE_NAME,
                    "CreationTime": "2021-06-04 10:23:20.199000+00:00",
                    "StackStatus": ClusterStatus.CREATE_COMPLETE,
                }
            ),
            config=plugin_old_configuration,
        )

        mocker.patch("pcluster.aws.cfn.CfnClient.stack_exists", return_value=True)

        if match:
            with pytest.raises(ClusterUpdateError, match=match):
                cluster.validate_update_request(
                    target_source_config=plugin_new_configuration, validator_suppressors={AllValidatorsSuppressor()}
                )
        else:
            cluster.validate_update_request(
                target_source_config=plugin_new_configuration, validator_suppressors={AllValidatorsSuppressor()}
            )


OLD_CONFIGURATION = """
Image:
  Os: alinux2
  CustomAmi: ami-08cf50b131bcd4db2
HeadNode:
  InstanceType: t2.micro
  Networking:
    SubnetId: subnet-08a5068070f6bc23d
  Ssh:
    KeyName: ermann-dub-ef
Scheduling:
  Scheduler: slurm
  SlurmQueues:
  - Name: queue2
    ComputeResources:
    - Name: queue1-t2micro
      InstanceType: t2.small
      MinCount: 0
      MaxCount: 11
    Networking:
      SubnetIds:
      - subnet-0f621591d5d0da380
"""


class _MockExportClusterLogsFiltersParser:
    def __init__(self):
        self.log_stream_prefix = None
        self.start_time = 0
        self.end_time = 0


class _MockListClusterLogsFiltersParser:
    def __init__(self):
        self.log_stream_prefix = None
