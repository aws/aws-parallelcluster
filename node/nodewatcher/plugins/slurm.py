# Copyright 2013-2015 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Amazon Software License (the "License"). You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/asl/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import subprocess
import logging

log = logging.getLogger(__name__)


def getJobs(hostname):
    # Slurm won't use FQDN
    short_name = hostname.split('.')[0]
    # Checking for running jobs on the node
    _command = ['/opt/slurm/bin/squeue', '-w', short_name, '-h']
    try:
        output = subprocess.Popen(_command, stdout=subprocess.PIPE).communicate()[0]
    except subprocess.CalledProcessError:
        log.error("Failed to run %s\n" % _command)

    if output == "":
        _jobs = False
    else:
        _jobs = True

    return _jobs

def lockHost(hostname, unlock=False):
    pass
