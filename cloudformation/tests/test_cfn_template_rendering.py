import hashlib
import importlib.util
import sys
from unittest.mock import patch

from cfnlint.__main__ import main as cfnlint
from jinja2 import Environment, FileSystemLoader

spec = importlib.util.spec_from_file_location("cfn_formatter", "../utils/cfn_formatter.py")
cfn_formatter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cfn_formatter)


def test_hit_substack_rendering(tmp_path):
    test_config = {
        "queues_config": {
            "multiple": {
                "instances": {
                    "c5.xlarge": {
                        "static_size": 1,
                        "dynamic_size": 20,
                        "spot_price": 1.5,
                        "vcpus": 4,
                        "gpus": 0,
                        "enable_efa": False,
                    },
                    "c5.2xlarge": {"static_size": 1, "dynamic_size": 10, "vcpus": 8, "gpus": 0, "enable_efa": False},
                },
                "placement_group": "AUTO",
                "disable_hyperthreading": False,
                "compute_type": "spot",
                "is_default": True,
            },
            "gpu": {
                "instances": {
                    "g3.8xlarge": {"static_size": 0, "dynamic_size": 20, "vcpus": 16, "gpus": 2, "enable_efa": False}
                },
                "placement_group": None,
                "disable_hyperthreading": True,
                "compute_type": "ondemand",
            },
            "efa": {
                "instances": {
                    "c5n.18xlarge": {"static_size": 0, "dynamic_size": 20, "vcpus": 36, "gpus": 0, "enable_efa": True}
                },
                "placement_group": "AUTO",
                "disable_hyperthreading": True,
                "compute_type": "ondemand",
            },
        },
        "scaling_config": {"scaledown_idletime": 10},
    }

    env = Environment(loader=FileSystemLoader(".."))
    env.filters["sha1"] = lambda value: hashlib.sha1(value.strip().encode()).hexdigest()
    template = env.get_template("hit-substack.cfn.yaml")
    output_from_parsed_template = template.render(hit_config=test_config)
    rendered_file = tmp_path / "hit-substack.cfn.yaml"
    rendered_file.write_text(output_from_parsed_template)

    # Run cfn-lint
    cfn_lint_args = ["--info", str(rendered_file)]
    with patch.object(sys, "argv", cfn_lint_args):
        assert cfnlint() == 0

    # Run format check
    assert cfn_formatter.check_formatting([str(rendered_file)], "yaml")
