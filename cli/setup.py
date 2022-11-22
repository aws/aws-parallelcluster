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

from setuptools import find_namespace_packages, setup


def readme():
    """Read the README file and use it as long description."""
    with open(os.path.join(os.path.dirname(__file__), "README"), encoding="utf-8") as f:
        return f.read()


VERSION = "3.3.1"
CDK_VERSION = "1.137,!=1.153.0"
REQUIRES = [
    "setuptools",
    "boto3>=1.16.14",
    "tabulate~=0.8",
    "PyYAML~=5.3",
    "jinja2~=3.0",
    "marshmallow~=3.10",
    "aws-cdk.core~=" + CDK_VERSION,
    "aws-cdk.aws-batch~=" + CDK_VERSION,
    "aws_cdk.aws-cloudwatch~=" + CDK_VERSION,
    "aws-cdk.aws-codebuild~=" + CDK_VERSION,
    "aws-cdk.aws-dynamodb~=" + CDK_VERSION,
    "aws-cdk.aws-ec2~=" + CDK_VERSION,
    "aws-cdk.aws-efs~=" + CDK_VERSION,
    "aws-cdk.aws-events~=" + CDK_VERSION,
    "aws-cdk.aws-fsx~=" + CDK_VERSION,
    "aws-cdk.aws-imagebuilder~=" + CDK_VERSION,
    "aws-cdk.aws-iam~=" + CDK_VERSION,
    "aws_cdk.aws-lambda~=" + CDK_VERSION,
    "aws-cdk.aws-logs~=" + CDK_VERSION,
    "aws-cdk.aws-route53~=" + CDK_VERSION,
    "aws-cdk.aws-ssm~=" + CDK_VERSION,
    "aws-cdk.aws-sqs~=" + CDK_VERSION,
    "aws-cdk.aws-cloudformation~=" + CDK_VERSION,
    "werkzeug~=2.0",
    "connexion~=2.13.0",
    "flask~=2.0",
    "jmespath~=0.10",
]

LAMBDA_REQUIRES = [
    "aws-lambda-powertools~=1.14",
]

setup(
    name="aws-parallelcluster",
    version=VERSION,
    author="Amazon Web Services",
    description="AWS ParallelCluster is an AWS supported Open Source cluster management tool to deploy "
    "and manage HPC clusters in the AWS cloud.",
    url="https://github.com/aws/aws-parallelcluster",
    license="Apache License 2.0",
    package_dir={"": "src"},
    packages=find_namespace_packages("src"),
    python_requires=">=3.7",
    install_requires=REQUIRES,
    extras_require={
        "awslambda": LAMBDA_REQUIRES,
    },
    entry_points={
        "console_scripts": [
            "pcluster = pcluster.cli.entrypoint:main",
            "pcluster3-config-converter = pcluster3_config_converter.pcluster3_config_converter:main",
        ]
    },
    include_package_data=True,
    zip_safe=False,
    long_description=readme(),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
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
