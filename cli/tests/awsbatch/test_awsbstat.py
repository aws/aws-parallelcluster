import json
import os

import pytest

from awsbatch import awsbstat
from tests.common import MockedBoto3Request, read_text
from tests.conftest import DEFAULT_AWSBATCHCLICONFIG_MOCK_CONFIG

ALL_JOB_STATUS = ["SUBMITTED", "PENDING", "RUNNABLE", "STARTING", "RUNNING", "SUCCEEDED", "FAILED"]
DEFAULT_JOB_STATUS = ["SUBMITTED", "PENDING", "RUNNABLE", "STARTING", "RUNNING"]


class TestArgs(object):
    def test_missing_cluster_parameter(self, failed_with_message):
        failed_with_message(awsbstat.main, "Error: cluster parameter is required\n", argv=[])


@pytest.fixture()
def boto3_stubber_path():
    # we need to set the region in the environment because the Boto3ClientFactory requires it.
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    return "awsbatch.common.boto3"


@pytest.mark.usefixtures("awsbatchcliconfig_mock")
@pytest.mark.usefixtures("convert_to_date_mock")
class TestOutput(object):
    def test_no_jobs_default_status(self, capsys, boto3_stubber, test_datadir):
        empty_response = {"jobSummaryList": []}
        mocked_requests = []
        for status in DEFAULT_JOB_STATUS:
            mocked_requests.append(
                MockedBoto3Request(
                    method="list_jobs",
                    response=empty_response,
                    expected_params={
                        "jobQueue": DEFAULT_AWSBATCHCLICONFIG_MOCK_CONFIG["job_queue"],
                        "jobStatus": status,
                        "nextToken": "",
                    },
                )
            )
        boto3_stubber("batch", mocked_requests)

        awsbstat.main(["-c", "cluster"])

        assert capsys.readouterr().out == read_text(test_datadir / "expected_output.txt")

    def test_no_jobs_all_status(self, capsys, boto3_stubber, test_datadir):
        empty_response = {"jobSummaryList": []}
        mocked_requests = []
        for status in ALL_JOB_STATUS:
            mocked_requests.append(
                MockedBoto3Request(
                    method="list_jobs",
                    response=empty_response,
                    expected_params={
                        "jobQueue": DEFAULT_AWSBATCHCLICONFIG_MOCK_CONFIG["job_queue"],
                        "jobStatus": status,
                        "nextToken": "",
                    },
                )
            )
        boto3_stubber("batch", mocked_requests)

        awsbstat.main(["-c", "cluster", "-s", "ALL"])

        assert capsys.readouterr().out == read_text(test_datadir / "expected_output.txt")

    def test_succeeded_status(self, capsys, boto3_stubber, test_datadir, shared_datadir):
        response = json.loads(read_text(shared_datadir / "aws_api_responses/batch_list-jobs_SUCCEEDED.json"))
        boto3_stubber(
            "batch",
            MockedBoto3Request(
                method="list_jobs",
                response=response,
                expected_params={
                    "jobQueue": DEFAULT_AWSBATCHCLICONFIG_MOCK_CONFIG["job_queue"],
                    "jobStatus": "SUCCEEDED",
                    "nextToken": "",
                },
            ),
        )

        awsbstat.main(["-c", "cluster", "-s", "SUCCEEDED"])

        assert capsys.readouterr().out == read_text(test_datadir / "expected_output.txt")

    def test_all_status(self, capsys, boto3_stubber, test_datadir, shared_datadir):
        mocked_requests = []
        for status in ALL_JOB_STATUS:
            response = json.loads(
                read_text(shared_datadir / "aws_api_responses/batch_list-jobs_{0}.json".format(status))
            )
            mocked_requests.append(
                MockedBoto3Request(
                    method="list_jobs",
                    response=response,
                    expected_params={
                        "jobQueue": DEFAULT_AWSBATCHCLICONFIG_MOCK_CONFIG["job_queue"],
                        "jobStatus": status,
                        "nextToken": "",
                    },
                )
            )
        boto3_stubber("batch", mocked_requests)

        awsbstat.main(["-c", "cluster", "-s", "ALL"])

        assert capsys.readouterr().out == read_text(test_datadir / "expected_output.txt")

    def test_single_job_detailed(self, capsys, boto3_stubber, test_datadir, shared_datadir):
        response = json.loads(read_text(shared_datadir / "aws_api_responses/batch_describe-jobs_single_job.json"))
        boto3_stubber(
            "batch",
            MockedBoto3Request(
                method="describe_jobs",
                response=response,
                expected_params={"jobs": ["ab2cd019-1d84-43c7-a016-9772dd963f3b"]},
            ),
        )

        awsbstat.main(["-c", "cluster", "ab2cd019-1d84-43c7-a016-9772dd963f3b"])

        assert capsys.readouterr().out == read_text(test_datadir / "expected_output.txt")

    @pytest.mark.parametrize(
        "args, expected",
        [
            (["3286a19c-68a9-47c9-8000-427d23ffc7ca"], "expected_output.txt"),
            (["-d", "3286a19c-68a9-47c9-8000-427d23ffc7ca"], "expected_output_detailed.txt"),
        ],
        ids=["single_array", "single_array_detailed"],
    )
    def test_single_array_job(self, args, expected, capsys, boto3_stubber, test_datadir, shared_datadir):
        response_parent = json.loads(
            read_text(shared_datadir / "aws_api_responses/batch_describe-jobs_single_array_job.json")
        )
        response_children = json.loads(
            read_text(shared_datadir / "aws_api_responses/batch_describe-jobs_single_array_job_children.json")
        )
        boto3_stubber(
            "batch",
            [
                MockedBoto3Request(
                    method="describe_jobs",
                    response=response_parent,
                    expected_params={"jobs": ["3286a19c-68a9-47c9-8000-427d23ffc7ca"]},
                ),
                MockedBoto3Request(
                    method="describe_jobs",
                    response=response_children,
                    expected_params={
                        "jobs": ["3286a19c-68a9-47c9-8000-427d23ffc7ca:0", "3286a19c-68a9-47c9-8000-427d23ffc7ca:1"]
                    },
                ),
            ],
        )

        awsbstat.main(["-c", "cluster"] + args)

        assert capsys.readouterr().out == read_text(test_datadir / expected)

    @pytest.mark.parametrize(
        "args, expected",
        [
            (["6abf3ecd-07a8-4faa-8a65-79e7404eb50f"], "expected_output.txt"),
            (["-d", "6abf3ecd-07a8-4faa-8a65-79e7404eb50f"], "expected_output_detailed.txt"),
        ],
        ids=["single_mnp", "single_mnp_detailed"],
    )
    def test_single_mnp_job(self, args, expected, capsys, boto3_stubber, test_datadir, shared_datadir):
        response_parent = json.loads(
            read_text(shared_datadir / "aws_api_responses/batch_describe-jobs_single_mnp_job.json")
        )
        response_children = json.loads(
            read_text(shared_datadir / "aws_api_responses/batch_describe-jobs_single_mnp_job_children.json")
        )
        boto3_stubber(
            "batch",
            [
                MockedBoto3Request(
                    method="describe_jobs",
                    response=response_parent,
                    expected_params={"jobs": ["6abf3ecd-07a8-4faa-8a65-79e7404eb50f"]},
                ),
                MockedBoto3Request(
                    method="describe_jobs",
                    response=response_children,
                    expected_params={
                        "jobs": ["6abf3ecd-07a8-4faa-8a65-79e7404eb50f#0", "6abf3ecd-07a8-4faa-8a65-79e7404eb50f#1"]
                    },
                ),
            ],
        )

        awsbstat.main(["-c", "cluster"] + args)

        assert capsys.readouterr().out == read_text(test_datadir / expected)

    def test_all_status_detailed(self, capsys, boto3_stubber, test_datadir, shared_datadir):
        mocked_requests = []
        jobs_ids = []
        describe_jobs_response = {"jobs": []}
        for status in ALL_JOB_STATUS:
            list_jobs_response = json.loads(
                read_text(shared_datadir / "aws_api_responses/batch_list-jobs_{0}.json".format(status))
            )
            describe_jobs_response["jobs"].extend(
                json.loads(read_text(shared_datadir / "aws_api_responses/batch_describe-jobs_{0}.json".format(status)))[
                    "jobs"
                ]
            )
            jobs_ids.extend([job["jobId"] for job in list_jobs_response["jobSummaryList"]])
            mocked_requests.append(
                MockedBoto3Request(
                    method="list_jobs",
                    response=list_jobs_response,
                    expected_params={
                        "jobQueue": DEFAULT_AWSBATCHCLICONFIG_MOCK_CONFIG["job_queue"],
                        "jobStatus": status,
                        "nextToken": "",
                    },
                )
            )

        mocked_requests.append(
            MockedBoto3Request(
                method="describe_jobs", response=describe_jobs_response, expected_params={"jobs": jobs_ids}
            )
        )
        boto3_stubber("batch", mocked_requests)

        awsbstat.main(["-c", "cluster", "-s", "ALL", "-d"])

        # describe-jobs api validation made by the Stubber requires startedAt to be always present.
        # Removing it from output when value is default (1970-01-01T00:00:00+00:00) since this is the
        # behavior for not stubbed calls.
        output = capsys.readouterr().out.replace("1970-01-01T00:00:00+00:00", "-")
        expcted_jobs_count_by_status = {
            "SUBMITTED": 2,
            "PENDING": 1,
            "RUNNABLE": 2,
            "STARTING": 2,
            "RUNNING": 2,
            "SUCCEEDED": 3,
            "FAILED": 3,
        }
        for status, count in expcted_jobs_count_by_status.items():
            assert output.count(status) == count
        assert output.count("jobId") == 15
        assert output == read_text(test_datadir / "expected_output.txt")

    def test_expanded_children(self, capsys, boto3_stubber, test_datadir, shared_datadir):
        mocked_requests = []
        # Mock all list-jobs requests
        for status in ALL_JOB_STATUS:
            list_jobs_response = json.loads(
                read_text(shared_datadir / "aws_api_responses/batch_list-jobs_{0}.json".format(status))
            )
            mocked_requests.append(
                MockedBoto3Request(
                    method="list_jobs",
                    response=list_jobs_response,
                    expected_params={
                        "jobQueue": DEFAULT_AWSBATCHCLICONFIG_MOCK_CONFIG["job_queue"],
                        "jobStatus": status,
                        "nextToken": "",
                    },
                )
            )
        # Mock describe-jobs on parents
        describe_parent_jobs_response = json.loads(
            read_text(shared_datadir / "aws_api_responses/batch_describe-jobs_ALL_parents.json")
        )
        jobs_with_children_ids = []
        for job in describe_parent_jobs_response["jobs"]:
            jobs_with_children_ids.append(job["jobId"])
        mocked_requests.append(
            MockedBoto3Request(
                method="describe_jobs",
                response=describe_parent_jobs_response,
                expected_params={"jobs": jobs_with_children_ids},
            )
        )
        # Mock describe-jobs on children
        describe_children_jobs_response = json.loads(
            read_text(shared_datadir / "aws_api_responses/batch_describe-jobs_ALL_children.json")
        )
        mocked_requests.append(
            MockedBoto3Request(
                method="describe_jobs",
                response=describe_children_jobs_response,
                expected_params={
                    "jobs": [
                        "3c6ee190-9121-464e-a0ac-62e4084e6bf1#0",
                        "3c6ee190-9121-464e-a0ac-62e4084e6bf1#1",
                        "11aa9096-1e98-4a7c-a44b-5ac3442df177:0",
                        "11aa9096-1e98-4a7c-a44b-5ac3442df177:1",
                        "77712b12-71eb-4007-a865-85f05de13a71#0",
                        "77712b12-71eb-4007-a865-85f05de13a71#1",
                        "bbbbbcbc-2647-4d8b-a1ef-da65bffe0dd0#0",
                        "bbbbbcbc-2647-4d8b-a1ef-da65bffe0dd0#1",
                        "qwerfcbc-2647-4d8b-a1ef-da65bffe0dd0#0",
                        "qwerfcbc-2647-4d8b-a1ef-da65bffe0dd0#1",
                        "3286a19c-68a9-47c9-8000-427d23ffc7ca:0",
                        "3286a19c-68a9-47c9-8000-427d23ffc7ca:1",
                        "3ec00225-8b85-48ba-a321-f61d005bec46#0",
                        "3ec00225-8b85-48ba-a321-f61d005bec46#1",
                        "44db07a9-f8a2-48d9-8d67-dcb04ceca54c:0",
                        "44db07a9-f8a2-48d9-8d67-dcb04ceca54c:1",
                        "7a712b12-71eb-4007-a865-85f05de13a71#0",
                        "7a712b12-71eb-4007-a865-85f05de13a71#1",
                    ]
                },
            )
        )
        boto3_stubber("batch", mocked_requests)

        awsbstat.main(["-c", "cluster", "-s", "ALL", "-e"])

        # describe-jobs api validation made by the Stubber requires startedAt to be always present.
        # Removing it from output when value is default (1970-01-01T00:00:00+00:00) since this is the
        # behavior for not stubbed calls.
        output = capsys.readouterr().out.replace("1970-01-01T00:00:00+00:00", "-                        ")
        assert output == read_text(test_datadir / "expected_output.txt")

    @pytest.mark.parametrize(
        "args, expected",
        [
            (
                [
                    "3286a19c-68a9-47c9-8000-427d23ffc7ca",
                    "ab2cd019-1d84-43c7-a016-9772dd963f3b",
                    "6abf3ecd-07a8-4faa-8a65-79e7404eb50f",
                ],
                "expected_output.txt",
            ),
            (
                [
                    "-d",
                    "3286a19c-68a9-47c9-8000-427d23ffc7ca",
                    "ab2cd019-1d84-43c7-a016-9772dd963f3b",
                    "6abf3ecd-07a8-4faa-8a65-79e7404eb50f",
                ],
                "expected_output_detailed.txt",
            ),
        ],
        ids=["tabular", "detailed"],
    )
    def test_default_ordering_by_id(self, args, expected, capsys, boto3_stubber, test_datadir, shared_datadir):
        parent_jobs_response = {"jobs": []}
        for file in [
            "batch_describe-jobs_single_mnp_job.json",
            "batch_describe-jobs_single_array_job.json",
            "batch_describe-jobs_single_job.json",
        ]:
            parent_jobs_response["jobs"].extend(
                json.loads(read_text(shared_datadir / "aws_api_responses/{0}".format(file)))["jobs"]
            )

        children_jobs_response = {"jobs": []}
        for file in [
            "batch_describe-jobs_single_mnp_job_children.json",
            "batch_describe-jobs_single_array_job_children.json",
        ]:
            children_jobs_response["jobs"].extend(
                json.loads(read_text(shared_datadir / "aws_api_responses/{0}".format(file)))["jobs"]
            )

        boto3_stubber(
            "batch",
            [
                MockedBoto3Request(
                    method="describe_jobs",
                    response=parent_jobs_response,
                    expected_params={
                        "jobs": [
                            "3286a19c-68a9-47c9-8000-427d23ffc7ca",
                            "ab2cd019-1d84-43c7-a016-9772dd963f3b",
                            "6abf3ecd-07a8-4faa-8a65-79e7404eb50f",
                        ]
                    },
                ),
                MockedBoto3Request(
                    method="describe_jobs",
                    response=children_jobs_response,
                    expected_params={
                        "jobs": [
                            "6abf3ecd-07a8-4faa-8a65-79e7404eb50f#0",
                            "6abf3ecd-07a8-4faa-8a65-79e7404eb50f#1",
                            "3286a19c-68a9-47c9-8000-427d23ffc7ca:0",
                            "3286a19c-68a9-47c9-8000-427d23ffc7ca:1",
                        ]
                    },
                ),
            ],
        )

        awsbstat.main(["-c", "cluster"] + args)

        assert capsys.readouterr().out == read_text(test_datadir / expected)

    @pytest.mark.parametrize(
        "args, expected",
        [
            (
                [
                    "3286a19c-68a9-47c9-8000-427d23ffc7ca:0",
                    "ab2cd019-1d84-43c7-a016-9772dd963f3b",
                    "6abf3ecd-07a8-4faa-8a65-79e7404eb50f#1",
                ],
                "expected_output.txt",
            ),
            (
                [
                    "-d",
                    "3286a19c-68a9-47c9-8000-427d23ffc7ca:0",
                    "ab2cd019-1d84-43c7-a016-9772dd963f3b",
                    "6abf3ecd-07a8-4faa-8a65-79e7404eb50f#1",
                ],
                "expected_output_detailed.txt",
            ),
        ],
        ids=["tabular", "detailed"],
    )
    def test_children_by_ids(self, args, expected, capsys, boto3_stubber, test_datadir, shared_datadir):
        boto3_stubber(
            "batch",
            MockedBoto3Request(
                method="describe_jobs",
                response=json.loads(
                    read_text(shared_datadir / "aws_api_responses/batch_describe-jobs_children_jobs.json")
                ),
                expected_params={
                    "jobs": [
                        "3286a19c-68a9-47c9-8000-427d23ffc7ca:0",
                        "ab2cd019-1d84-43c7-a016-9772dd963f3b",
                        "6abf3ecd-07a8-4faa-8a65-79e7404eb50f#1",
                    ]
                },
            ),
        )

        awsbstat.main(["-c", "cluster"] + args)

        assert capsys.readouterr().out == read_text(test_datadir / expected)
