import json


def test_scheduled_events_template_syntax():
    print("Checking syntax of scheduled-events-substack.cfn.json")
    with open("scheduled-events-substack.cfn.json", "r") as substack_file:
        events_substack = json.load(substack_file)
    # Double check to make sure syntax are correct
    # For example, making sure Arn is used instead of logical ID for applicable resource/condition
    resources = events_substack.get("Resources")
    for statement in resources.get("EventsSQSPolicy").get("Properties").get("PolicyDocument").get("Statement"):
        assert "Arn" in (statement.get("Condition").get("ArnEquals").get("aws:SourceArn").get("Fn::GetAtt"))
    for target in resources.get("ScheduledEventRule").get("Properties").get("Targets"):
        assert "Arn" in target.get("Arn").get("Fn::GetAtt")
    print("SUCCEEDED: syntax for scheduled-events-substack.cfn.json looks good")
