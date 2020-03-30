import argparse

import troposphere.events as events
import troposphere.sqs as sqs
from troposphere import GetAtt, Output, Ref, Template


def main(args):

    t = Template()
    health_queue = t.add_resource(sqs.Queue(title="HealthEventQueue", MessageRetentionPeriod=1209600))
    target = events.Target(
        title="ScheduledEventTarget",
        Arn=GetAtt(health_queue, "Arn"),
        Id="sqswatcher_target",
        InputTransformer=events.InputTransformer(
            title="ScheduledEventInputeTransformer",
            InputPathsMap={"Instances": "$.resources[0]"},
            InputTemplate=(
                '"{\\"Type\\" : \\"Notification\\", \\"Message\\" : '
                '\\"{\\\\\\"StatusCode\\\\\\":\\\\\\"Scheduled_Events\\\\\\",\\\\\\"Description\\\\\\":'
                '\\\\\\"Detected scheduled events for instance <Instances>\\\\\\"'
                ',\\\\\\"Event\\\\\\":\\\\\\"parallelcluster:EC2_SCHEDULED_EVENT\\\\\\",'
                '\\\\\\"EC2InstanceId\\\\\\":\\\\\\"<Instances>\\\\\\"}\\"}"'
            ),
        ),
    )
    t.add_resource(
        events.Rule(
            title="ScheduledEventRule",
            EventPattern={
                "source": ["aws.health"],
                "detail-type": ["AWS Health Event"],
                "detail": {"service": ["EC2"], "eventTypeCategory": ["scheduledChange"]},
            },
            State="ENABLED",
            Targets=[target],
        )
    )
    t.add_resource(
        sqs.QueuePolicy(
            title="EventsSQSPolicy",
            PolicyDocument={
                "Id": "EventsQueuePolicy",
                "Statement": [
                    {
                        "Sid": "Allow-SendMessage-From-CW-Events",
                        "Effect": "Allow",
                        "Principal": {"Service": ["events.amazonaws.com"]},
                        "Action": ["sqs:SendMessage"],
                        "Resource": "*",
                    }
                ],
            },
            Queues=[Ref(health_queue)],
        )
    )
    t.add_output(
        Output("HealthSQSQueueName", Description="Name of SQS health queue", Value=GetAtt(health_queue, "QueueName"))
    )
    t.add_output(Output("HealthSQSQueueARN", Description="ARN of SQS health queue", Value=GetAtt(health_queue, "Arn")))
    json_file_path = args.target_path
    output_file = open(json_file_path, "w")
    output_file.write(t.to_json())
    output_file.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Take in generator related parameters")
    parser.add_argument(
        "--target-path", type=str, help="The target path for generated substack template", required=True
    )
    args = parser.parse_args()
    main(args)
