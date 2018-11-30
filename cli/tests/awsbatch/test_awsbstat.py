import json

import pytest

from awsbatch import awsbstat
from common import DEFAULT_AWSBATCHCLICONFIG_MOCK_CONFIG, MockedBoto3Request, read_text

ALL_JOB_STATUS = ["SUBMITTED", "PENDING", "RUNNABLE", "STARTING", "RUNNING", "SUCCEEDED", "FAILED"]
DEFAULT_JOB_STATUS = ["SUBMITTED", "PENDING", "RUNNABLE", "STARTING", "RUNNING"]


class TestArgs(object):
    def test_missing_cluster_parameter(self, failed_with_message):
        failed_with_message(awsbstat.main, "Error: cluster parameter is required\n", argv=[])


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

    def test_single_array_job(self, capsys, boto3_stubber, test_datadir, shared_datadir):
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

        awsbstat.main(["-c", "cluster", "3286a19c-68a9-47c9-8000-427d23ffc7ca"])

        assert capsys.readouterr().out == read_text(test_datadir / "expected_output.txt")

    def test_single_array_job_detailed(self, capsys, boto3_stubber, test_datadir, shared_datadir):
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

        awsbstat.main(["-c", "cluster", "-d", "3286a19c-68a9-47c9-8000-427d23ffc7ca"])

        assert capsys.readouterr().out == read_text(test_datadir / "expected_output.txt")

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
        # Removing it from output when value is default (1970-01-01 01:00:00) since this is the
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
