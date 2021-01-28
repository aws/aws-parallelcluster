# Copyright 2013-2016 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import sys

from setuptools import find_packages, setup


def readme():
    """Read the README file and use it as long description."""
    with open(os.path.join(os.path.dirname(__file__), "README")) as f:
        return f.read()


VERSION = "2.10.1"
REQUIRES = [
    "setuptools",
    "boto3>=1.16.14",
    "future>=0.16.0,<=0.18.2",
    "tabulate==0.8.5" if sys.version_info.major == 3 and sys.version_info.minor <= 4 else "tabulate>=0.8.2,<=0.8.7",
    "ipaddress>=1.0.22",
    "PyYAML==5.2" if sys.version_info.major == 3 and sys.version_info.minor <= 4 else "PyYAML>=5.3.1",
    "jinja2==2.10.1" if sys.version_info.major == 3 and sys.version_info.minor <= 4 else "jinja2>=2.11.0",
]

if sys.version_info < (3, 4):
    REQUIRES.append("enum34>=1.1.6")

if sys.version_info[0] == 2:
    REQUIRES.append("configparser>=3.5.0,<=3.8.1")

setup(
    name="aws-parallelcluster",
    version=VERSION,
    author="Amazon Web Services",
    description="AWS ParallelCluster is an AWS supported Open Source cluster management tool to deploy "
    "and manage HPC clusters in the AWS cloud.",
    url="https://github.com/aws/aws-parallelcluster",
    license="Apache License 2.0",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*",
    install_requires=REQUIRES,
    entry_points={
        "console_scripts": [
            "pcluster = pcluster.cli:main",
            "pcluster-config = pcluster_config.cli:main",
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
    package_data={"": ["src/examples/config"]},
    long_description=readme(),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Scientific/Engineering",
        "License :: OSI Approved :: Apache Software License",
    ],
    project_urls={
        "Changelog": "https://github.com/aws/aws-parallelcluster/blob/develop/CHANGELOG.md",
        "Issue Tracker": "https://github.com/aws/aws-parallelcluster/issues",
        "Documentation": "https://docs.aws.amazon.com/parallelcluster/",
    },
)
