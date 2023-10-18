# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import os

from setuptools import find_packages, setup


def readme():
    """Read the README file and use it as long description."""
    with open(os.path.join(os.path.dirname(__file__), "README"), encoding="utf-8") as f:
        return f.read()


VERSION = "1.2.0"
REQUIRES = [
    "setuptools",
    "boto3>=1.16.14",
    "tabulate>=0.8.8,<=0.8.10",
]

setup(
    name="aws-parallelcluster-awsbatch-cli",
    version=VERSION,
    author="Amazon Web Services",
    description=(
        "AWS ParallelCluster AWS Batch CLI provides a set of commands to manage "
        "AWS Batch resources created by ParallelCluster and AWS Batch jobs."
    ),
    url="https://github.com/aws/aws-parallelcluster",
    license="Apache License 2.0",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.7",
    install_requires=REQUIRES,
    entry_points={
        "console_scripts": [
            "awsbqueues = awsbatch.awsbqueues:main",
            "awsbhosts = awsbatch.awsbhosts:main",
            "awsbstat = awsbatch.awsbstat:main",
            "awsbkill = awsbatch.awsbkill:main",
            "awsbsub = awsbatch.awsbsub:main",
            "awsbout = awsbatch.awsbout:main",
        ]
    },
    include_package_data=True,
    zip_safe=False,
    long_description=(
        "aws-parallelcluster-awsbatch-cli is the python package installed on the Amazon EC2 instances launched "
        "as part of AWS ParallelCluster when using AWS Batch as a scheduler. It provides a set of commands "
        "to manage AWS Batch resources created within the cluster and AWS Batch jobs."
    ),
    long_description_content_type="text/plain",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Scientific/Engineering",
        "License :: OSI Approved :: Apache Software License",
    ],
    project_urls={
        "Changelog": "https://github.com/aws/aws-parallelcluster/blob/develop/awsbatch-cli/CHANGELOG.md",
        "Issue Tracker": "https://github.com/aws/aws-parallelcluster/issues",
        "Documentation": "https://docs.aws.amazon.com/parallelcluster/",
    },
)
