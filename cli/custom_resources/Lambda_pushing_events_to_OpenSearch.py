import json
import base64
import datetime
import math
from botocore.auth import SigV4Auth
import requests
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
import botocore.session
import zlib

session = botocore.session.Session()
# Now using hard coded signature and endpoint
sigv4 = SigV4Auth(session.get_credentials(), 'es', 'us-east-1')
endpoint = 'https://search-myfirstdomain-rzzmn4tktxvewmsi6hmc7tumli.us-east-1.es.amazonaws.com/_bulk'
def lambda_handler(event, context):
    # TODO implement
    data = event['awslogs']['data']
    # decode input from base 64
    decodedStr = zlib.decompress(base64.b64decode(data), zlib.MAX_WBITS | 32).decode('utf-8')
    awslogsData = json.loads(decodedStr)
    elasticsearchBulkData = transform(awslogsData)

    # skip control messages
    if not elasticsearchBulkData:
        print('Received a control message')
        context.succeed('Control message handled successfully')
        return
    response = post(elasticsearchBulkData)
    print(response)
    return {
        'statusCode': 200,
        'body': json.dumps('Hello from Lambda!'),
    }

def transform(payload):
    if (payload['messageType'] == "CONTROL_MESSAGE"):
        return None
    bulkRequestBody = ""
    for logEvent in payload['logEvents']:
        timestamp = str(datetime.datetime.fromtimestamp(logEvent['timestamp']/1000.0))
        indexName = timestamp[:10].split('-')
        indexName = 'cwl-' + '.'.join(indexName)

        source = buildSource(logEvent['message'], logEvent.get('extractedFields', None))
        source['@id'] = logEvent['id']
        source['@timestamp'] = timestamp
        source['@message'] = logEvent['message']
        source['@owner'] = payload['owner']
        source['@log_group'] = payload['logGroup']
        source['@log_stream'] = payload['logStream']

        action = { 'index': {} }
        action['index']['_index'] = indexName
        action['index']['_id'] = logEvent['id']

        bulkRequestBody += json.dumps(action) + "\n" + json.dumps(source) +"\n"

    return bulkRequestBody

def buildSource(message, extractedFields):
    if extractedFields:
        source = {}
        for key in extractedFields:
            if extractedFields.hasOwnProperty(key) and extractedFields[key]:
                value = extractedFields[key]

                if math.isnan(value):
                    source[key] = 1 * value;
                    continue

            jsonSubString = extractJson(value)
            if jsonSubString:
                source['$' + key] = json.loads(jsonSubString)

            source[key] = value
        return source

    jsonSubString = extractJson(message)
    if jsonSubString:
        return json.loads(jsonSubString)

    return {}

def extractJson(message):
    jsonStart = message.index('{')
    if jsonStart < 0:
        return None
    jsonSubString = message[jsonStart:]
    if isValidJson(jsonSubString):
        return jsonSubString
    return None

def isValidJson(message):
    try:
        json.loads(message)
        return True
    except json.JSONDecodeError:
        return False

def post(body):
    headers = {'Content-Type': 'application/json'}
    request = AWSRequest(method='POST', url=endpoint, data=body, headers=headers)
    request.context["payload_signing_enabled"] = True # This is mandatory since VpcLattice does not support payload signing. Not providing this will result in error.
    sigv4.add_auth(request)
    prepped = request.prepare()
    response = requests.post(prepped.url, data=body, headers=prepped.headers)
    return response
