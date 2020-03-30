import argparse

import troposphere.events as events
from troposphere import Parameter, Ref, Template


def main(args):

    t = Template()
    health_queue_arn = t.add_parameter(
        Parameter("HealthQueueArn", Type="String", Description="Arn of the target health SQS queue.",)
    )
    target = events.Target(
        title="ScheduledEventTarget",
        Arn=Ref(health_queue_arn),
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
            title="FakeScheduledEventRule",
            EventPattern={
                "source": ["fake.aws.health"],
                "detail-type": ["Fake AWS Health Event"],
                "detail": {"service": ["EC2"], "eventTypeCategory": ["scheduledChange"]},
            },
            State="ENABLED",
            Targets=[target],
        )
    )
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
