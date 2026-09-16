from datetime import datetime, timezone

from framework.tests_configuration import config_renderer


def test_get_gpu_instance_type_candidates_prioritizes_requested_placeholder():
    instance_type_parameters = {
        "US_WEST_2_GPU_INSTANCE_TYPE_0": "g4dn.xlarge",
        "US_WEST_2_GPU_INSTANCE_TYPE_1": "g5.xlarge",
        "US_WEST_2_GPU_INSTANCE_TYPE_2": "g6.xlarge",
    }

    candidates = config_renderer._get_gpu_instance_type_candidates(
        "US_WEST_2_GPU_INSTANCE_TYPE_1", instance_type_parameters
    )

    assert candidates == ["g5.xlarge", "g6.xlarge", "g4dn.xlarge"]


def test_create_capacity_reservations_tries_each_gpu_type_in_all_regions_before_next_type(monkeypatch):
    attempted_specs = []

    def fake_create_reservations(az_for_cr, regions, specs, var):
        attempted_specs.append(([spec[0] for spec in specs], regions, var))
        return len(attempted_specs) == 2

    monkeypatch.setattr(
        config_renderer,
        "_create_capacity_reservations_for_instance_types",
        fake_create_reservations,
    )
    now = datetime.now(timezone.utc)
    specs = [
        (["g5.xlarge", "g4dn.xlarge"], "Linux/UNIX", 2, now, False),
        (["c5.xlarge"], "Linux/UNIX", 1, now, False),
    ]
    regions = ["us-east-1", "us-west-2"]

    created = config_renderer._create_capacity_reservations({}, regions, specs, "GPU_RESERVATION")

    assert created
    assert attempted_specs == [
        (["g5.xlarge", "c5.xlarge"], regions, "GPU_RESERVATION"),
        (["g4dn.xlarge", "c5.xlarge"], regions, "GPU_RESERVATION"),
    ]


def test_check_or_create_capacity_reservations_overlays_successful_gpu_type(monkeypatch):
    reservation_variable = (
        "US_WEST_2_GPU_INSTANCE_TYPE_0_CAPACITY_RESERVATION_4_INSTANCES_2_HOURS_NOPG_OS_X86_5"
    )
    successful_specs = [("g4dn.4xlarge", "Linux/UNIX", 4, datetime.now(timezone.utc), False)]

    monkeypatch.setattr(config_renderer, "_get_all_jinja_variables", lambda _: {reservation_variable})
    monkeypatch.setattr(config_renderer.random, "shuffle", lambda _: None)

    def fake_create_reservations(az_for_cr, regions, specs, var):
        az_for_cr[var] = "usw2-az1"
        return successful_specs

    monkeypatch.setattr(config_renderer, "_create_capacity_reservations", fake_create_reservations)

    rendered_parameters = config_renderer._check_or_create_capacity_reservations(
        "unused.yaml",
        {"OS_X86_5": "alinux2023"},
        {
            "US_WEST_2_GPU_INSTANCE_TYPE_0": "g5.xlarge",
            "US_WEST_2_GPU_INSTANCE_TYPE_1": "g4dn.4xlarge",
        },
    )

    assert rendered_parameters[reservation_variable] == "usw2-az1"
    assert rendered_parameters["US_WEST_2_GPU_INSTANCE_TYPE_0"] == "g4dn.4xlarge"
