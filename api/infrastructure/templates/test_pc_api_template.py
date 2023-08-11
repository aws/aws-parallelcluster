import pytest
from cfn import CfnClient
import json


@pytest.mark.parametrize(
    "template_file_name",
    [
        "parallelcluster-api.yaml"
    ],
)
def test_permission_boundary(template_file_name):
    cfn_client = CfnClient()
    with open(template_file_name, "r") as file:
        cf_template = json.load(file)
    cf_template["Resources"][""]
    stack_name = "test-pb-stack"
    cfn_client.create_stack(stack_name, template_body=json.dumps(cf_template))

    resources = cfn_client.get_stack_resources(stack_name)
