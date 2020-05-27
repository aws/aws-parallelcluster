import argparse

import troposphere.events as events
import troposphere.sqs as sqs
from troposphere import GetAtt, Output, Ref, Template


def generate_scheduled_event_rule(output_path, make_real_rule=True, input_parameters=None):

    t = Template()
    if make_real_rule:
        health_queue = t.add_resource(sqs.Queue(title="HealthEventQueue", MessageRetentionPeriod=1209600))
        t.add_output(
            Output(
                "HealthSQSQueueName", Description="Name of SQS health queue", Value=GetAtt(health_queue, "QueueName")
            )
        )
        t.add_output(
            Output("HealthSQSQueueARN", Description="ARN of SQS health queue", Value=GetAtt(health_queue, "Arn"))
        )
        health_queue_arn = GetAtt(health_queue, "Arn")
        health_queue_url = Ref(health_queue)
    else:
        health_queue_arn = input_parameters["health_queue_arn"]
        health_queue_url = input_parameters["health_queue_url"]

    resource_prefix = "" if make_real_rule else "Fake"
    target = events.Target(
        title=resource_prefix + "ScheduledEventTarget",
        Arn=health_queue_arn,
        Id="sqswatcher_target",
        InputTransformer=events.InputTransformer(
            title="ScheduledEventInputeTransformer",
            InputPathsMap={"Instances": "$.resources"},
            InputTemplate=(
                '"{\\"Type\\" : \\"Notification\\", \\"Message\\" : '
                '\\"{\\\\\\"StatusCode\\\\\\":\\\\\\"Scheduled_Events\\\\\\",\\\\\\"Description\\\\\\":'
                '\\\\\\"Detected scheduled events for instance <Instances>\\\\\\"'
                ',\\\\\\"Event\\\\\\":\\\\\\"parallelcluster:EC2_SCHEDULED_EVENT\\\\\\",'
                '\\\\\\"EC2InstanceId\\\\\\":\\\\\\"<Instances>\\\\\\"}\\"}"'
            ),
        ),
    )
    scheduled_event_rule = t.add_resource(
        events.Rule(
            title=resource_prefix + "ScheduledEventRule",
            EventPattern={
                "source": ["aws.health" if make_real_rule else "fake.aws.health"],
                "detail-type": ["AWS Health Event" if make_real_rule else "Fake AWS Health Event"],
                "detail": {"service": ["EC2"], "eventTypeCategory": ["scheduledChange"]},
            },
            State="ENABLED",
            Targets=[target],
        )
    )
    t.add_resource(
        sqs.QueuePolicy(
            title=resource_prefix + "EventsSQSPolicy",
            PolicyDocument={
                "Id": resource_prefix + "EventsQueuePolicy",
                "Statement": [
                    {
                        "Sid": resource_prefix + "Allow-SendMessage-From-Scheduled-Events-Rule",
                        "Effect": "Allow",
                        "Principal": {"Service": ["events.amazonaws.com"]},
                        "Action": ["sqs:SendMessage"],
                        "Resource": "*",
                        "Condition": {"ArnEquals": {"aws:SourceArn": GetAtt(scheduled_event_rule, "Arn")}},
                    }
                ],
            },
            Queues=[health_queue_url],
        )
    )

    output_file = open(output_path, "w")
    output_file.write(t.to_json())
    output_file.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Take in generator related parameters")
    parser.add_argument(
        "--target-path", type=str, help="The target path for generated substack template", required=True
    )
    args = parser.parse_args()
    generate_scheduled_event_rule(args.target_path)
