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

__author__ = 'dougalb'

import subprocess
import os
import logging

log = logging.getLogger(__name__)

def getJobs(hostname):
    # Checking for running jobs on the node
    command = ['/opt/sge/bin/idle-nodes']
    try:
       _output = subprocess.Popen(command, stdout=subprocess.PIPE,
                                 env=dict(os.environ, SGE_ROOT='/opt/sge',
                                         PATH='/opt/sge/bin:/opt/sge/bin/lx-amd64:/bin:/usr/bin')).communicate()[0]
    except subprocess.CalledProcessError:
        log.error("Failed to run %s\n" % command)

    _jobs = True
    for host in _output.split('\n'):
        if hostname.split('.')[0] in host:
            _jobs = False
            break

    return _jobs

def lockHost(hostname, unlock=False):
    _mod = unlock and '-e' or '-d'
    command = ['/opt/sge/bin/lx-amd64/qmod', _mod, 'all.q@%s' % hostname]
    try:
        subprocess.check_call(
            command,
            env=dict(os.environ, SGE_ROOT='/opt/sge',
                     PATH='/opt/sge/bin:/opt/sge/bin/lx-amd64:/bin:/usr/bin'))
    except subprocess.CalledProcessError:
        log.error("Failed to run %s\n" % command)

