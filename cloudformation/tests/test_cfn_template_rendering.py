import hashlib
import importlib.util
import sys
from unittest.mock import patch

import pytest
from cfnlint.__main__ import main as cfnlint
from jinja2 import Environment, FileSystemLoader

spec = importlib.util.spec_from_file_location("cfn_formatter", "../utils/cfn_formatter.py")
cfn_formatter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cfn_formatter)


def substack_rendering(tmp_path, template_name, test_config):

    env = Environment(loader=FileSystemLoader(".."))
    env.filters["sha1"] = lambda value: hashlib.sha1(value.strip().encode()).hexdigest()
    env.filters["bool"] = lambda value: value.lower() == "true"
    template = env.get_template(template_name)
    output_from_parsed_template = template.render(
        config=test_config, config_version="version", tags=[{"Key": "TagKey", "Value": "TagValue"}]
    )
    rendered_file = tmp_path / template_name
    rendered_file.write_text(output_from_parsed_template)

    # Run cfn-lint
    cfn_lint_args = ["--info", str(rendered_file)]  # TODO "-i", "W2001" could be added to ignore unused vars
    with patch.object(sys, "argv", cfn_lint_args):
        assert cfnlint() == 0

    # Run format check
    assert cfn_formatter.check_formatting([str(rendered_file)], "yaml")

    return output_from_parsed_template


@pytest.mark.parametrize(
    "test_config",
    [
        (
            {
                "cluster": {
                    "label": "default",
                    "default_queue": "multiple_spot",
                    "queue_settings": {
                        "multiple_spot": {
                            "compute_type": "spot",
                            "enable_efa": False,
                            "enable_efa_gdr": False,
                            "disable_hyperthreading": True,
                            "placement_group": None,
                            "compute_resource_settings": {
                                "multiple_spot_c4.xlarge": {
                                    "instance_type": "c4.xlarge",
                                    "min_count": 0,
                                    "max_count": 10,
                                    "spot_price": None,
                                    "vcpus": 2,
                                    "gpus": 0,
                                    "enable_efa": False,
                                    "enable_efa_gdr": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": False,
                                    "network_interfaces": 1,
                                },
                                "multiple_spot_c5.2xlarge": {
                                    "instance_type": "c5.2xlarge",
                                    "min_count": 1,
                                    "max_count": 5,
                                    "spot_price": 1.5,
                                    "vcpus": 4,
                                    "gpus": 0,
                                    "enable_efa": False,
                                    "enable_efa_gdr": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                    "network_interfaces": 1,
                                },
                            },
                        },
                        "efa": {
                            "compute_resource_settings": {
                                "efa_c5n.18xlarge": {
                                    "instance_type": "c5n.18xlarge",
                                    "min_count": 0,
                                    "max_count": 5,
                                    "spot_price": None,
                                    "vcpus": 36,
                                    "gpus": 0,
                                    "enable_efa": True,
                                    "enable_efa_gdr": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                    "network_interfaces": 1,
                                }
                            },
                            "compute_type": "ondemand",
                            "enable_efa": True,
                            "enable_efa_gdr": False,
                            "disable_hyperthreading": True,
                            "placement_group": "DYNAMIC",
                        },
                        "gpu": {
                            "compute_resource_settings": {
                                "gpu_g3.8xlarge": {
                                    "instance_type": "g3.8xlarge",
                                    "min_count": 0,
                                    "max_count": 5,
                                    "spot_price": None,
                                    "vcpus": 16,
                                    "gpus": 2,
                                    "enable_efa": False,
                                    "enable_efa_gdr": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                    "network_interfaces": 1,
                                }
                            },
                            "compute_type": "ondemand",
                            "enable_efa": False,
                            "enable_efa_gdr": False,
                            "disable_hyperthreading": True,
                            "placement_group": None,
                        },
                    },
                    "scaling": {"scaledown_idletime": 10},
                    "disable_cluster_dns": False,
                    "dashboard": {"enable": True},
                }
            }
        ),
        (
            {
                "cluster": {
                    "label": "default",
                    "default_queue": "multiple_spot",
                    "queue_settings": {
                        "multiple_spot": {
                            "compute_type": "spot",
                            "enable_efa": False,
                            "enable_efa_gdr": False,
                            "disable_hyperthreading": True,
                            "placement_group": None,
                            "compute_resource_settings": {
                                "multiple_spot_c4.xlarge": {
                                    "instance_type": "c4.xlarge",
                                    "min_count": 0,
                                    "max_count": 10,
                                    "spot_price": None,
                                    "vcpus": 2,
                                    "gpus": 0,
                                    "enable_efa": False,
                                    "enable_efa_gdr": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                    "network_interfaces": 1,
                                },
                                "multiple_spot_c5.2xlarge": {
                                    "instance_type": "c5.2xlarge",
                                    "min_count": 1,
                                    "max_count": 5,
                                    "spot_price": 1.5,
                                    "vcpus": 4,
                                    "gpus": 0,
                                    "enable_efa": False,
                                    "enable_efa_gdr": False,
                                    "disable_hyperthreading": True,
                                    "disable_hyperthreading_via_cpu_options": True,
                                    "network_interfaces": 1,
                                },
                                # TODO: add test for multiple NICs
                            },
                        }
                    },
                    "scaling": {"scaledown_idletime": 10},
                    "disable_cluster_dns": True,
                    "dashboard": {"enable": True},
                }
            }
        ),
    ],
    ids=["complete", "without_route53"],
)
def test_hit_substack_rendering(tmp_path, test_config):

    substack_rendering(tmp_path, "compute-fleet-hit-substack.cfn.yaml", test_config)
