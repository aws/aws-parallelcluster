import pytest
from assertpy import assert_that
import merge_version_files


@pytest.mark.parametrize(
    "files, expected_result, expected_error",
    [
        ([], {'versions': []}, None),
        (["test_json_files/non_regex_matching.json"], None, "All files should respect the 'os_(.*).json' regex"),
        (["os_3.0.0.json"], {
            "versions": [
                {
                    "version": "3.0.0",
                    "os": [
                        {
                            "name": "alinux2",
                            "description": "Amazon Linux 2"
                        },
                        {
                            "name": "ubuntu1804",
                            "description": "Ubuntu 18.04 LTS"
                        },
                        {
                            "name": "ubuntu2004",
                            "description": "Ubuntu 20.04 LTS"
                        },
                        {
                            "name": "centos7",
                            "description": "CentOS 7"
                        }
                    ]
                }
            ]
        }, None),
        (["os_3.0.0.json", "os_3.1.1.json"], {
            "versions": [
                {
                    "version": "3.0.0",
                    "os": [
                        {
                            "name": "alinux2",
                            "description": "Amazon Linux 2"
                        },
                        {
                            "name": "ubuntu1804",
                            "description": "Ubuntu 18.04 LTS"
                        },
                        {
                            "name": "ubuntu2004",
                            "description": "Ubuntu 20.04 LTS"
                        },
                        {
                            "name": "centos7",
                            "description": "CentOS 7"
                        }
                    ]
                },
                {
                    "version": "3.1.1",
                    "os": [
                        {
                            "name": "alinux2",
                            "description": "Amazon Linux 2"
                        },
                        {
                            "name": "ubuntu1804",
                            "description": "Ubuntu 18.04 LTS"
                        },
                        {
                            "name": "ubuntu2004",
                            "description": "Ubuntu 20.04 LTS"
                        },
                        {
                            "name": "centos7",
                            "description": "CentOS 7"
                        }
                    ]
                }
            ]
        }, None),
        (["os_3.0.0.json", "test_json_files/non_regex_matching.json"], None,
         "All files should respect the 'os_(.*).json' regex"),
    ],
)
def test_create_merged_dict(files, expected_result, expected_error):
    if expected_error is not None:
        with pytest.raises(Exception) as exc:
            merge_version_files.create_merged_dict(files)
        assert_that(str(exc.value)).matches(str(expected_error))
    else:
        assert_that(merge_version_files.create_merged_dict(files)).is_equal_to(expected_result)
