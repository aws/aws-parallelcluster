# Copyright 2013-2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Amazon Software License (the "License"). You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/asl/
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
version = "0.0.10"
requires = ['boto', 'botocore'] 

if sys.version_info[:2] == (2, 6):
    # For python2.6 we have to require argparse since it
    # was not in stdlib until 2.7.
    requires.append('argparse>=1.1')

setup(
    name = "cfncluster",
    version = version,
    author = "Dougal Ballantyne",
    author_email = "dougalb@amazon.com",
    description = ("A simple tool to launch and manage HPC clusters as CloudFormation stacks."),
    url = ("https://github.com/awslabs/cfncluster"),
    license = "Amazon Software License",
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
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Programming Language :: Python",
        "Topic :: Scientific/Engineering",
        "License :: Other/Proprietary License",
    ],
)