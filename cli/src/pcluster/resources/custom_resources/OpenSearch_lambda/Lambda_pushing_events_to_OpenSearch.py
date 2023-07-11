import base64
import datetime
import json
import math
import zlib

import botocore.session
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

session = botocore.session.Session()
# Now using hard coded signature and endpoint
sigv4 = SigV4Auth(session.get_credentials(), "es", "us-east-1")
endpoint = "https://search-myfirstdomain-rzzmn4tktxvewmsi6hmc7tumli.us-east-1.es.amazonaws.com/_bulk"


def lambda_handler(event, context):
    # TODO implement
    data = event["awslogs"]["data"]
    # decode input from base 64
    decoded_str = zlib.decompress(base64.b64decode(data), zlib.MAX_WBITS | 32).decode("utf-8")
    aws_logs_data = json.loads(decoded_str)
    elasticsearch_bulk_data = transform(aws_logs_data)

    # skip control messages
    if not elasticsearch_bulk_data:
        print("Received a control message")
        context.succeed("Control message handled successfully")
        return
    response = post(elasticsearch_bulk_data)
    print(response)
    return None


def transform(payload):
    if payload["messageType"] == "CONTROL_MESSAGE":
        return None
    bulk_request_body = ""
    for log_event in payload["logEvents"]:
        timestamp = str(datetime.datetime.fromtimestamp(log_event["timestamp"] / 1000.0))
        index_name = timestamp[:10].split("-")
        index_name = "cwl-" + ".".join(index_name)

        source = build_source(log_event["message"], log_event.get("extractedFields", None))
        source["@id"] = log_event["id"]
        source["@timestamp"] = timestamp
        source["@message"] = log_event["message"]
        source["@owner"] = payload["owner"]
        source["@log_group"] = payload["logGroup"]
        source["@log_stream"] = payload["logStream"]

        action = {"index": {}}
        action["index"]["_index"] = index_name
        action["index"]["_id"] = log_event["id"]

        bulk_request_body += json.dumps(action) + "\n" + json.dumps(source) + "\n"

    return bulk_request_body


def build_source(message, extracted_fields):
    if extracted_fields:
        source = {}
        for key in extracted_fields:
            if extracted_fields.hasOwnProperty(key) and extracted_fields[key]:
                value = extracted_fields[key]

                if math.isnan(value):
                    source[key] = 1 * value
                    continue

            json_substring = extract_json(value)
            if json_substring:
                source["$" + key] = json.loads(json_substring)

            source[key] = value
        return source

    json_substring = extract_json(message)
    if json_substring:
        return json.loads(json_substring)
    return {}


def extract_json(message):
    json_start = message.index("{")
    if json_start < 0:
        return None
    json_substring = message[json_start:]
    if is_valid_json(json_substring):
        return json_substring
    return None


def is_valid_json(message):
    try:
        json.loads(message)
        return True
    except json.JSONDecodeError:
        return False


def post(body):
    headers = {"Content-Type": "application/json"}
    request = AWSRequest(method="POST", url=endpoint, data=body, headers=headers)
    request.context[
        "payload_signing_enabled"
    ] = True  # This is mandatory since VpcLattice does not support payload signing.
    sigv4.add_auth(request)
    prepped = request.prepare()
    response = requests.post(prepped.url, data=body, headers=prepped.headers, timeout=20)
    return response
