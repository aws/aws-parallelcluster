import json

import pytest
import yaml
from assertpy import assert_that

from common.utils import load_yaml_dict
from pcluster.schemas.imagebuilder_schema import ImageBuilderSchema


@pytest.mark.parametrize("config_file_name", ["imagebuilder_schema_required.yaml", "imagebuilder_schema_dev.yaml"])
def test_imagebuilder_schema(test_datadir, config_file_name):
    # Load imagebuilder model from Yaml file
    input_yaml = load_yaml_dict(test_datadir / config_file_name)
    print(input_yaml)
    imagebuilder_config = ImageBuilderSchema().load(input_yaml)
    print(imagebuilder_config)

    # Re-create Yaml file from model and compare content
    output_json = ImageBuilderSchema().dump(imagebuilder_config)

    # Assert imagebuilder config file can be convert to imagebuilder config
    assert_that(json.dumps(input_yaml, sort_keys=True)).is_equal_to(json.dumps(output_json, sort_keys=True))

    # Print output yaml
    output_yaml = yaml.dump(output_json)
    print(output_yaml)
