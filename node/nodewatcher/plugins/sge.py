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

__author__ = 'dougalb'

import subprocess
import os

def getJobs(hostname):
    # Checking for running jobs on the node
    command = ['/opt/sge/bin/lx-amd64/qstat', '-l', 'hostname=%s' % hostname, '-u', '*']
    try:
       output = subprocess.Popen(command, stdout=subprocess.PIPE, 
                                 env=dict(os.environ, SGE_ROOT='/opt/sge')).communicate()[0]
    except subprocess.CalledProcessError:
        print ("Failed to run %s\n" % _command)

    if output == "":
        _jobs = False
    else:
        _jobs = True

    return _jobs
