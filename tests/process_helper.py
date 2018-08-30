#!/usr/bin/python
#
# Copyright 2018      Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy
# of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, express or implied. See the License for the specific
# language governing permissions and limitations under the License.
#
#
# This helper class copes with the termination of multiple processes forked by a simple multi-threaded application.
# All processes are registered internally and if the term_handler() function is registered
# to handle TERM or INT signals it will kill all the active processes submitted through the exec_command() function.
# Killed processes would make the exec_command() function to raise an Exception, either AbortedProcessError or
# KilledProcessError, that can be managed by the client application.
#

import os
import signal
import subprocess as sub
import threading


_procs = {}
_procs_lock = threading.Lock()

_termination_caught = False

class ProcessHelperError(Exception):
    def __init__(self, cmd, msg=None):
        if msg is None:
            msg = "Error executing command '%s' was killed" % cmd
        super(ProcessHelperError, self).__init__(msg)
        self.cmd = cmd

class AbortedProcessError(ProcessHelperError):
    def __init__(self, cmd):
        super(AbortedProcessError, self).__init__(cmd, "Command '%s' was aborted" % cmd)

class KilledProcessError(ProcessHelperError):
    def __init__(self, cmd):
        super(KilledProcessError, self).__init__(cmd, "Process for command '%s' was killed" % cmd)

def termination_caught():
    return _termination_caught

#
# This function is supposed to be used as handler for system signals:
#    signal.signal(signal.SIGTERM, ph.term_handler)
# It manages to kill all the active processes submitted through this module.
# Killed processes would make the exec_command() function to raise a KilledProcessError
# or an AbortedProcessError exception.
#
def term_handler(_signo, _stack_frame):
    global _procs_lock, _procs, _termination_caught

    _procs_lock.acquire()
    if not _termination_caught:
        _termination_caught = True
        for proc in _procs.values():
            _kill_process(proc)

    _procs_lock.release()

def _kill_process(process):
    try:
        process.kill()
    except:
        pass

def _add_process(process):
    global _procs_lock, _procs, _termination_caught

    if process != None and process.pid != None and process.pid != 0:
        _procs_lock.acquire()

        if _termination_caught:
            _kill_process(process)
        else:
            _procs[process.pid] = process

        _procs_lock.release()

def _remove_process(process):
    global _procs_lock, _procs

    if process != None and _procs.has_key(process.pid):
        _procs_lock.acquire()

        del _procs[process.pid]

        _procs_lock.release()

def exec_command(*cmdargs, **kwargs):
    global _termination_caught

    if _termination_caught:
        raise AbortedProcessError(" ".join(*cmdargs))

    DEV_NULL = open(os.devnull, "rb")
    params = {
        'env' : dict(os.environ),
        'stdin' : DEV_NULL,
        'stdout' : sub.PIPE,
        'stderr' : sub.STDOUT
        }
    params.update(kwargs)

    process = None
    try:
        process = sub.Popen(*cmdargs, **params)
        _add_process(process)
        stdout = process.communicate()[0]
        exitcode = process.poll()
        if exitcode != 0:
            if _termination_caught:
                raise KilledProcessError(" ".join(*cmdargs))
            else:
                raise sub.CalledProcessError(exitcode, " ".join(*cmdargs), stdout)
        return stdout
    finally:
        DEV_NULL.close()
        _remove_process(process)
