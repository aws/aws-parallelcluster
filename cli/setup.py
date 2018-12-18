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


VERSION = "2.1.0"
REQUIRES = ["boto3>=1.9.48", "awscli>=1.11.175", "future>=0.16.0", "tabulate>=0.8.2"]

if sys.version_info[:2] == (2, 6):
    # For python2.6 we have to require argparse since it
    # was not in stdlib until 2.7.
    REQUIRES.append("argparse>=1.4.0")

if sys.version_info[0] == 2:
    REQUIRES.append("configparser>=3.5.0")

setup(
    name="aws-parallelcluster",
    version=VERSION,
    author="Amazon Web Services",
    description="AWS ParallelCluster is an AWS supported Open Source cluster management tool to deploy "
    "and manage HPC clusters in the AWS cloud.",
    url="https://github.com/aws/aws-parallelcluster",
    license="Apache License 2.0",
    packages=find_packages(),
    install_requires=REQUIRES,
    entry_points={
        "console_scripts": [
            "pcluster = pcluster.cli:main",
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
    package_data={"": ["examples/config"]},
    long_description=readme(),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Programming Language :: Python",
        "Topic :: Scientific/Engineering",
        "License :: OSI Approved :: Apache Software License",
    ],
)
