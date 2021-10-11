#!/bin/bash

#
# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
#

set -e

# TODO: remove once this is provided out of the box
echo "Creating python virutualenv"
HOME=/home/pcluster-scheduler-plugin
export PYENV_ROOT="$HOME/.pyenv"
/opt/parallelcluster/pyenv/bin/pyenv install --skip-existing 3.9.7
/opt/parallelcluster/pyenv/bin/pyenv virtualenv --force 3.9.7 scheduler_plugin

# TODO: remove once this is provided out of the box
echo "Activating python virutualenv"
source /home/pcluster-scheduler-plugin/.pyenv/versions/3.9.7/envs/scheduler_plugin/bin/activate
pip install --upgrade supervisor awscli jinja2 requests PyYAML

bash artifacts/init_cookbook.sh
