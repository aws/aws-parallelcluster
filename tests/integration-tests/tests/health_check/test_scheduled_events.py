# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import json
import logging
import os
import time

import boto3
import pytest
from configparser import ConfigParser

from assertpy import assert_that
from cfn_stacks_factory import CfnStack, CfnStacksFactory
from remote_command_executor import RemoteCommandExecutor
from tests.common.assertions import (
    assert_initial_conditions,
    assert_no_errors_in_logs,
    assert_nodes_not_terminated_by_nodewatcher,
    assert_nodes_removed_and_replaced_in_scheduler,
)
from tests.common.schedulers_common import get_scheduler_commands
from utils import (
    get_compute_nodes_instance_ids,
    get_instance_ids_compute_hostnames_conversion_dict,
    random_alphanumeric,
)

DISABLED_STATES = {
    "slurm": ["draining", "drained"],
    "torque": ["offline"],
}


@pytest.fixture()
def fake_rule_stack_factory(request):
    """Define a fixture to manage the creation and destruction of CloudFormation stacks."""
    factory = CfnStacksFactory(request.config.getoption("credential"))

    def _create_network(region, template_path, parameters):
        file_content = extract_template(template_path)
        stack = CfnStack(
            name="integ-tests-events-fake-rule-{}{}{}".format(
                random_alphanumeric(),
                "-" if request.config.getoption("stackname_suffix") else "",
                request.config.getoption("stackname_suffix"),
            ),
            region=region,
            template=file_content,
            parameters=parameters,
        )
        logging.info("Building fake CW event rule stack...")
        factory.create_stack(stack)
        return stack

    def extract_template(template_path):
        with open(template_path) as cfn_file:
            file_content = cfn_file.read()
        return file_content

    yield _create_network
    factory.delete_all_stacks()


# Create stack, get health queue arn
# create fake rule, push events(one for master and one for compute)
# see that node is terminated, modify sqs config to disable health check
# restart sqswatcher, push events and see that node is kept
@pytest.mark.regions(["us-west-1", "us-gov-east-1", "cn-northwest-1"])
@pytest.mark.instances(["c5.xlarge"])
@pytest.mark.oss(["ubuntu1804"])
@pytest.mark.skip_schedulers(["awsbatch"])
@pytest.mark.usefixtures("region", "os", "scheduler", "instance")
def test_scheduled_events(
    scheduler, region, pcluster_config_reader, clusters_factory, fake_rule_stack_factory, test_datadir
):
    """Test handling of EC2 health scheduled events."""
    os.environ["AWS_DEFAULT_REGION"] = region
    num_compute_nodes = 2
    cluster_config = pcluster_config_reader(initial_queue_size=num_compute_nodes)
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    # Test that the default rule is able to match a sample AWS health event
    _test_real_event_pattern(test_datadir)

    # We cannot push real scheduled events to event bus
    # Create a fake rule that will be trigger by a fake health event in order to test end-to-end behavior of the cluster
    path = os.path.join("..", "..", "cloudformation", "cw-events", "fake-event-rule.cfn.json")
    health_queue_arn = _get_health_queue_arn(remote_command_executor)
    fake_rule_stack_factory(region, path, [{"ParameterKey": "HealthQueueArn", "ParameterValue": health_queue_arn}])

    _test_health_event_behavior(
        cluster.cfn_name,
        scheduler,
        remote_command_executor,
        scheduler_commands,
        num_compute_nodes,
        health_check_enabled=True,
    )
    remote_command_executor.run_remote_script(str(test_datadir / "disable_health_check.sh"))
    _test_health_event_behavior(
        cluster.cfn_name,
        scheduler,
        remote_command_executor,
        scheduler_commands,
        num_compute_nodes,
        health_check_enabled=False,
    )

    assert_no_errors_in_logs(remote_command_executor, ["/var/log/sqswatcher"])


def _test_real_event_pattern(test_datadir):
    logging.info("Testing that ScheduledEventRule will match a real AWS scheduled event notification.")
    events_substack_path = os.path.join("..", "..", "cloudformation", "cw-events-substack.cfn.json")
    with open(events_substack_path) as substack_file:
        events_substack = json.load(substack_file)
    real_event_pattern = (
        events_substack.get("Resources").get("ScheduledEventRule").get("Properties").get("EventPattern")
    )
    with open(str(test_datadir / "sample_scheduled_event.json")) as sample_event_file:
        sample_event = json.load(sample_event_file)
    region = os.environ.get("AWS_DEFAULT_REGION")
    events_client = boto3.client("events", region_name=region)
    response = events_client.test_event_pattern(
        EventPattern=json.dumps(real_event_pattern), Event=json.dumps(sample_event)
    )
    assert_that(response.get("Result")).is_true()
    logging.info("ScheduledEventRule successfully matched a real AWS scheduled event notification.")


def _test_health_event_behavior(
    cluster_name, scheduler, remote_command_executor, scheduler_commands, num_compute_nodes, health_check_enabled
):
    logging.info(
        "Testing the handling of EC2 health scheduled events when health_check_enabled is {}".format(
            health_check_enabled
        )
    )
    region = os.environ.get("AWS_DEFAULT_REGION")
    # Do not assert states becuase scheduler_commands.get_nodes_status is not implemented for sge and torque
    compute_nodes = assert_initial_conditions(scheduler_commands, num_compute_nodes, assert_state=False)
    compute_instance_ids = get_compute_nodes_instance_ids(cluster_name, region)
    hostname_to_id = get_instance_ids_compute_hostnames_conversion_dict(compute_instance_ids, id_to_hostname=False)
    # Run job on all nodes
    job_id = _submit_sleep_job(scheduler, scheduler_commands, num_compute_nodes)
    nodes_to_remove = compute_nodes[:-1]
    nodes_to_retain = compute_nodes[-1:]
    instances_to_remove = [hostname_to_id[hostname] for hostname in nodes_to_remove]

    # Push the fake scheduled event
    _push_scheduled_event(instances_to_remove)
    # Check that nodes locked by scheduled events are not replaced while they have running jobs
    assert_nodes_not_terminated_by_nodewatcher(scheduler_commands, compute_nodes)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    # Check that nodes are eventually removed if health_check_enabled or retained if not health_check_enabled
    if health_check_enabled:
        assert_nodes_removed_and_replaced_in_scheduler(
            scheduler_commands, nodes_to_remove, nodes_to_retain, desired_capacity=num_compute_nodes
        )
    else:
        assert_nodes_not_terminated_by_nodewatcher(scheduler_commands, compute_nodes)


def _push_scheduled_event(instance_ids):
    logging.info("Pushing fake scheduled events for instances: {}".format(instance_ids))
    region = os.environ.get("AWS_DEFAULT_REGION")
    events_client = boto3.client("events", region_name=region)
    entries = []
    for instance_id in instance_ids:
        entries.append(
            {
                "Source": "fake.aws.health",
                "Resources": [instance_id],
                "DetailType": "Fake AWS Health Event",
                "Detail": (
                    '{"eventArn": "arn:aws:health:region::event/id",'
                    '"service": "EC2","eventTypeCode": "AWS_EC2_DEDICATED_HOST_NETWORK_MAINTENANCE_SCHEDULED",'
                    '"eventTypeCategory": "scheduledChange","startTime": "Sat, 05 Jun 2019 15:10:09 GMT",'
                    '"eventDescription": [{"language": "en_US",'
                    '"latestDescription": "A description of the event will be provided here"}],'
                    '"affectedEntities": [{"entityValue": "some_instance_id",'
                    '"tags": {"Stage": "prod","App": "my-app"}}]}"'
                ),
            },
        )
    response = events_client.put_events(Entries=entries)
    assert_that(response.get("FailedEntryCount")).is_equal_to(0)
    logging.info("Successfully pushed fake scheduled events for instances: {}".format(instance_ids))


def _submit_sleep_job(scheduler, scheduler_commands, num_compute_nodes):
    # submit job with --no-requeue so that we do not have to wait for job to finish
    # if job is automatically requeued by slurm after node replacement
    func_args = {
        "command": "sleep 450",
        "nodes": num_compute_nodes,
        "slots": 4,
    }
    if scheduler == "slurm":
        func_args["other_options"] = "--no-requeue"
    result = scheduler_commands.submit_command(**func_args)
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    # sleep for 10 seconds to avoid case of node is put into a state before job is assigned to the node
    time.sleep(10)
    return job_id


def _get_health_queue_arn(remote_command_executor):
    region = os.environ.get("AWS_DEFAULT_REGION")
    sqs_config = remote_command_executor.run_remote_command("cat /etc/sqswatcher.cfg").stdout
    config = ConfigParser()
    config.read_string(sqs_config)
    health_queue_name = config.get("sqswatcher", "healthsqsqueue")
    sqs_client = boto3.client("sqs", region_name=region)
    queue_url = sqs_client.get_queue_url(QueueName=health_queue_name).get("QueueUrl")
    queue_arn = (
        sqs_client.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])
        .get("Attributes")
        .get("QueueArn")
    )
    return queue_arn
