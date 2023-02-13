"""Test that all of the templates are in a valid format."""
import json
import os

import boto3
import pytest
from assertpy import assert_that


def test_valid_json():
    """Verify cfn templates are correctly formatted."""
    for filename in os.listdir("../networking"):
        if filename.endswith(".cfn.json"):
            with open(f"../networking/{filename}", encoding="utf-8") as inf:
                data = json.load(inf)
                assert_that(data).is_not_none()


@pytest.mark.parametrize("directory", [("../networking"), ("../policies"), ("../ad"), ("../database")])
@pytest.mark.local
def test_valid_template(directory):
    """Verify cfn templates are correctly formatted."""
    cfn = boto3.client("cloudformation")
    for filename in os.listdir(directory):
        if filename.endswith(".cfn.json") or filename.endswith(".yaml"):
            print(f"Validating json file: {directory}/{filename}")
            with open(f"{directory}/{filename}", encoding="utf-8") as inf:
                response = cfn.validate_template(TemplateBody=inf.read())
                assert_that(response).is_not_none()
