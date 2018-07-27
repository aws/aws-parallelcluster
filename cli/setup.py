# Copyright 2013-2016 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import os, sys
from setuptools import setup, find_packages

# Utility function to read the README file.
# Used for the long_description.  It's nice, because now 1) we have a top level
# README file and 2) it's easier to type in the README file than to put a raw
# string in below ...
def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

console_scripts = ['cfncluster = cfncluster.cli:main']
version = "1.5.3rc1"
requires = ['boto3>=1.7.33', 'awscli>=1.11.175', 'future>=0.16.0']

if sys.version_info[:2] == (2, 6):
    # For python2.6 we have to require argparse since it
    # was not in stdlib until 2.7.
    requires.append('argparse>=1.4.0')

if sys.version_info[0] == 2:
    requires.append('configparser>=3.5.0')

setup(
    name = "cfncluster",
    version = version,
    author = "Dougal Ballantyne",
    author_email = "dougalb@amazon.com",
    description = ("A simple tool to launch and manage HPC clusters as CloudFormation stacks."),
    url = ("https://github.com/awslabs/cfncluster"),
    license = "Apache License 2.0",
    packages = find_packages(),
    install_requires = requires,
    entry_points=dict(console_scripts=console_scripts),
    include_package_data = True,
    zip_safe = False,
    package_data = {
        '' : ['examples/config'],
    },
    long_description=read('README'),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Programming Language :: Python",
        "Topic :: Scientific/Engineering",
        "License :: OSI Approved :: Apache Software License",
    ],
)
