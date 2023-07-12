import base64
import datetime
import json
import math
import re
import zlib

import botocore.session
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

session = botocore.session.Session()
# Now using hard coded signature and endpoint
sigv4 = SigV4Auth(session.get_credentials(), "es", "us-east-1")
endpoint = "https://search-myfirstdomain-rzzmn4tktxvewmsi6hmc7tumli.us-east-1.es.amazonaws.com"


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
        if source["event-type"] == "scontrol-show-job-information":
            source = process(source)

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


def process(source):
    query = {
        "size": 1,
        "query": {"match": {"event-type.keyword": "node-instance-mapping-event"}},
        "sort": [{"datetime": {"order": "desc"}}],
    }
    response = json.loads(get(query).text)
    node_name = source["detail"]["node_list"]
    node_name_list = get_node_list(node_name)
    node_map = response["hits"]["hits"][0]["_source"]["detail"]["node_list"]
    nodes = []
    node_dict = get_node_dict(node_map)
    for node in node_name_list:
        nodes.append(node_dict[node])
    source["detail"]["nodes"] = nodes
    del source["detail"]["node_list"]
    return source


def get_node_list(node_names):
    """
    Convert node_names to a list of nodes.

    Example input node_names: "queue1-st-c5xlarge-[1,3,4-5],queue1-st-c5large-20"
    Example output [queue1-st-c5xlarge-1, queue1-st-c5xlarge-3, queue1-st-c5xlarge-4, queue1-st-c5xlarge-5,
    queue1-st-c5large-20]
    """
    matches = []
    if type(node_names) is str:
        matches = re.findall(r"((([a-z0-9\-]+)-(st|dy)-([a-z0-9\-]+)-)(\[[\d+,-]+\]|\d+))(,|$)", node_names)
        # [('queue1-st-c5xlarge-[1,3,4-5]', 'queue1-st-c5xlarge-', 'queue1', 'st', 'c5xlarge', '[1,3,4-5]'),
        # ('queue1-st-c5large-20', 'queue1-st-c5large-', 'queue1', 'st', 'c5large', '20')]
    node_list = []
    if not matches:
        print("Invalid Node Name Error")
    for match in matches:
        node_name, prefix, _, _, _, nodes, _ = match
        if "[" not in nodes:
            # Single node name
            node_list.append(node_name)
        else:
            # Multiple node names
            try:
                node_range = convert_range_to_list(nodes.strip("[]"))
            except ValueError:
                print("Invalid Node Name Error")
            node_list += [prefix + str(n) for n in node_range]
    return node_list


def convert_range_to_list(node_range):
    """
    Convert a number range to a list.

    Example input: Input can be like one of the format: "1-3", "1-2,6", "2, 8"
    Example output: [1, 2, 3]
    """
    return sum(
        (
            (list(range(*[int(j) + k for k, j in enumerate(i.split("-"))])) if "-" in i else [int(i)])
            for i in node_range.split(",")
        ),
        [],
    )


def get_node_dict(node_map):
    node_name_dict = {}
    for node in node_map:
        name = node["node_name"]
        node_name_dict[name] = node
    return node_name_dict


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
    if is_valid_json(message):
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


def make_request(method, endpoint, data=None):
    headers = {"Content-Type": "application/json"}
    request = AWSRequest(method=method, url=endpoint, data=data, headers=headers)
    request.context["payload_signing_enabled"] = True
    sigv4.add_auth(request)
    prepped = request.prepare()
    response = requests.request(method, prepped.url, data=prepped.body, headers=prepped.headers, timeout=200)
    return response


def post(body):
    endpoint_for_post = endpoint + "/_bulk"
    response = make_request("POST", endpoint_for_post, body)
    return response


def get(query):
    data = json.dumps(query)
    endpoint_for_get = endpoint + "/cwl-2023.07.*/_search"
    response = make_request("GET", endpoint_for_get, data)
    return response
