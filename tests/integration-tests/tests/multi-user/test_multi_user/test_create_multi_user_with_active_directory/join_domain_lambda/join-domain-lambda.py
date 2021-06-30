import json
import os

import boto3


def lambda_handler(event, context):
    json_message = json.dumps(event)
    message = json.loads(json_message)
    instance_id = message["instance"]
    ssm_client = boto3.client("ssm")
    domain_name = ssm_client.get_parameter(Name=os.environ["DOMAIN_NAME_PARAMETER"])
    domain_name_value = domain_name["Parameter"]["Value"]
    domain_password = ssm_client.get_parameter(Name=os.environ["DOMAIN_PASSWORD_PARAMETER"], WithDecryption=True)
    domain_password_value = domain_password["Parameter"]["Value"]
    ssm_client.send_command(
        InstanceIds=["%s" % instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={
            "commands": [
                'echo "%s" | realm join -U Administrator@%s %s --verbose'
                % (domain_password_value, domain_name_value, domain_name_value),
                "rm -rf /var/lib/amazon/ssm/i-*/document/orchestration/*",
            ]
        },
    )
    return {
        "statusCode": 200,
        "body": json.dumps("Command Executed with credentials: %s %s" % (domain_name_value, domain_password_value)),
    }
