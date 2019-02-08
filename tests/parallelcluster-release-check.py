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
# Build a cluster for each combination of region, base_os, and
# scheduler, and run a test script on each cluster.  To avoid bouncing
# against limits in each region, the number of simultaneously built
# clusters in each region is a configuration parameter.
#
# NOTE:
# - This script requires python2
# - To simplify this script, at least one subnet in every region
#   to be tested must have a resource tag named "ParallelClusterTestSubnet"
#   (value does not matter). That subnet will be used as the launch
#   target for the cluster.

import datetime
import errno
import os
import Queue
import re
import signal
import subprocess as sub
import sys
import threading
import time
from builtins import exit
from collections import namedtuple

import argparse
import boto3

import process_helper as prochelp
from hamcrest import *


class ReleaseCheckException(Exception):
    pass


#
# configuration
#
ClusterConfig = namedtuple(
    "ClusterConfig",
    [
        "config_file",
        "stack_name",
        "region",
        "distro",
        "instance_type",
        "scheduler",
        "username",
        "key_path",
        "key_name",
        "master_node",
        "scaledown_idletime",
    ],
)

username_map = {
    "alinux": "ec2-user",
    "centos6": "centos",
    "centos7": "centos",
    "ubuntu1404": "ubuntu",
    "ubuntu1604": "ubuntu",
}

# commands used to retrieve the number of compute nodes in each scheduler
get_compute_nodes_command_map = {
    "sge": '/bin/bash --login -c "qhost | grep -o ip- | wc -l"',
    "slurm": '/bin/bash --login -c "sinfo --Node --noheader | grep compute | wc -l"',
    "torque": '/bin/bash --login -c "echo $(( $(/opt/torque/bin/pbsnodes -l all | wc -l) - 1))"',
}

# default ssh options
ssh_config_options = [
    "-o {0}".format(option)
    for option in [
        "StrictHostKeyChecking=no",
        "BatchMode=yes",
        "ConnectTimeout=60",
        "ServerAliveCountMax=5",
        "ServerAliveInterval=30",
    ]
]

#
# global variables (sigh)
#
setup = {}

results_lock = threading.Lock()
failure = 0
success = 0

# PID of the actual test process
_child = 0
# True if parent process has been asked to terminate
_termination_caught = False

_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"
_timestamp = datetime.datetime.now().strftime(_TIMESTAMP_FORMAT)


def _dirname():
    return os.path.dirname(os.path.realpath(sys.argv[0]))


def _time():
    return datetime.datetime.now()


# Write both on stdout and the specified file object
def _double_writeln(fileo, message):
    print(message)
    fileo.write(message + "\n")


def _get_attached_compute_nodes(cluster_config):
    """
    Returns the number of compute nodes attached to the scheduler.
    Args:
        cluster_config: named tuple of type ClusterConfig containing the configuration of the cluster.

    Returns:
        number_of_nodes: number of available compute nodes.
    """
    output = _exec_ssh_command(
        command=get_compute_nodes_command_map[cluster_config.scheduler],
        username=cluster_config.username,
        host=cluster_config.master_node,
        key_path=cluster_config.key_path,
    )
    # get last line of the output containing the number of compute nodes
    return int(output.split()[-1])


def _get_desired_asg_capacity(cluster_config):
    """
    Retrieves the desired capacity of the autoscaling group for a specific cluster.
    Args:
        cluster_config: named tuple of type ClusterConfig containing the configuration of the cluster.

    Returns:
        asg_capacity: the desired capacity of the autoscaling group.
    """
    asg_conn = boto3.client("autoscaling", region_name=cluster_config.region)
    tags = asg_conn.describe_tags(Filters=[{"Name": "value", "Values": [cluster_config.stack_name]}])
    asg_name = tags.get("Tags")[0].get("ResourceId")
    response = asg_conn.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    return response["AutoScalingGroups"][0]["DesiredCapacity"]


def _exec_ssh_command(command, host, username, key_path, stdout=sub.PIPE, stderr=sub.STDOUT):
    """
    Executes an ssh command on a remote host.
    Args:
        command: command to execute.
        host: host where the command is executed.
        username: username used to ssh into the host.
        key_path: key used to ssh into the host.
        stdout: stdout redirection. Defaults to sub.PIPE.
        stderr: stderr redirection. Defaults to sub.STDOUT.

    Returns:
        the stdout for the executed command.
    """
    ssh_params = list(ssh_config_options)
    if key_path:
        ssh_params.extend(["-i", key_path])

    return prochelp.exec_command(
        ["ssh", "-n"] + ssh_params + ["%s@%s" % (username, host), command],
        stdout=stdout,
        stderr=stderr,
        universal_newlines=True,
    )


def _watch_compute_nodes_allocation(duration, frequency, cluster_config):
    """
    Periodically watches the number of compute nodes in the cluster.
    The function returns after duration or when the compute nodes scaled down to 0.
    Args:
        duration: duration in seconds of the periodical check.
        frequency: polling interval in seconds.
        cluster_config: named tuple of type ClusterConfig containing the configuration of the cluster.

    Returns:
        (asg_capacity_time_series, compute_nodes_time_series, timestamps): three lists describing
        the variation over time in the number of compute nodes and the timestamp when these fluctuations occurred.
        asg_capacity_time_series describes the variation in the desired asg capacity. compute_nodes_time_series
        describes the variation in the number of compute nodes seen by the scheduler. timestamps describes the
        time since epoch when the variations occurred.
    """
    asg_capacity_time_series = []
    compute_nodes_time_series = []
    timestamps = []

    timeout = time.time() + duration
    while time.time() < timeout:
        compute_nodes = _get_attached_compute_nodes(cluster_config)
        asg_capacity = _get_desired_asg_capacity(cluster_config)
        timestamp = time.time()

        # add values only if there is a transition.
        if (
            len(asg_capacity_time_series) == 0
            or asg_capacity_time_series[-1] != asg_capacity
            or compute_nodes_time_series[-1] != compute_nodes
        ):
            asg_capacity_time_series.append(asg_capacity)
            compute_nodes_time_series.append(compute_nodes)
            timestamps.append(timestamp)

        # break loop before timeout only when compute nodes are scaled down to 0.
        if asg_capacity_time_series[-1] == 0 and compute_nodes_time_series[-1] == 0:
            if max(asg_capacity_time_series) > 0 and max(compute_nodes_time_series) > 0:
                break
        time.sleep(frequency)

    return asg_capacity_time_series, compute_nodes_time_series, timestamps


def _execute_test_jobs_on_cluster(cluster_config, log_file):
    """
    Executes test jobs defined in cluster-check.sh on a given cluster.
    Args:
        cluster_config: named tuple of type ClusterConfig containing the configuration of the cluster.
        log_file: file where to write logs.
    """
    ssh_params = list(ssh_config_options)
    if cluster_config.key_path:
        ssh_params.extend(["-i", cluster_config.key_path])

    prochelp.exec_command(
        ["scp"]
        + ssh_params
        + [
            os.path.join(_dirname(), "cluster-check.sh"),
            "%s@%s:." % (cluster_config.username, cluster_config.master_node),
        ],
        stdout=log_file,
        stderr=sub.STDOUT,
        universal_newlines=True,
    )
    _exec_ssh_command(
        command="/bin/bash --login cluster-check.sh submit %s" % cluster_config.scheduler,
        username=cluster_config.username,
        host=cluster_config.master_node,
        key_path=cluster_config.key_path,
        stdout=log_file,
    )


def _get_master_ip(cluster_config_file, cluster_name, log_file):
    """
    Retrieves the ip of the master node for a given cluster.
    Args:
        cluster_config_file: file containing the config of the cluster.
        cluster_name: name of the cluster.
        log_file: file where to write logs.

    Returns:
        master_ip: the ip of the master node.
    """
    master_ip = ""
    # get the master ip, which means grepping through pcluster status output
    dump = prochelp.exec_command(
        ["pcluster", "status", "--config", cluster_config_file, cluster_name],
        stderr=sub.STDOUT,
        universal_newlines=True,
    )
    dump_array = dump.splitlines()
    for line in dump_array:
        m = re.search("MasterPublicIP: (.+)$", line)
        if m:
            master_ip = m.group(1)
            break

    # Check master ip was correctly retrieved
    if master_ip == "":
        _double_writeln(
            log_file, "!! %s: Master IP not found. This usually occurs when cluster creation failed." % cluster_name
        )
        raise ReleaseCheckException("--> %s: Master IP not found!" % cluster_name)
    _double_writeln(log_file, "--> %s Master IP: %s" % (cluster_name, master_ip))

    return master_ip


def _write_pcluster_config(cluster_config, extra_args):
    """
    Creates a file containing the config needed by pcluster to spin up the cluster.
    Args:
        cluster_config: named tuple of type ClusterConfig containing the configuration of the cluster.
        extra_args: extra arguments passed to the test function.
    """
    custom_cookbook = extra_args["custom_cookbook_url"]
    custom_node = extra_args["custom_node_url"]
    custom_template = extra_args["custom_template_url"]

    with open(cluster_config.config_file, "w") as file:
        file.write("[aws]\n")
        file.write("aws_region_name = %s\n" % cluster_config.region)
        file.write("[cluster default]\n")
        file.write("vpc_settings = public\n")
        file.write("key_name = %s\n" % cluster_config.key_name)
        file.write("base_os = %s\n" % cluster_config.distro)
        file.write("master_instance_type = %s\n" % cluster_config.instance_type)
        file.write("compute_instance_type = %s\n" % cluster_config.instance_type)
        file.write("initial_queue_size = 1\n")
        file.write("maintain_initial_size = false\n")
        file.write("scheduler = %s\n" % cluster_config.scheduler)
        file.write("scaling_settings = custom\n")
        if custom_template:
            file.write("template_url = %s\n" % custom_template)
        if custom_cookbook:
            file.write("custom_chef_cookbook = %s\n" % custom_cookbook)
        if custom_node:
            file.write('extra_json = { "cluster" : { "custom_node_package" : "%s" } }\n' % custom_node)
        file.write("[vpc public]\n")
        file.write("master_subnet_id = %s\n" % (setup[cluster_config.region]["subnet"]))
        file.write("vpc_id = %s\n" % (setup[cluster_config.region]["vpc"]))
        file.write("[global]\n")
        file.write("cluster_template = default\n")
        file.write("[scaling custom]\n")
        file.write("scaledown_idletime = %s\n" % cluster_config.scaledown_idletime)


def _assert_scaling_works(
    asg_capacity_time_series, compute_nodes_time_series, expected_asg_capacity, expected_compute_nodes
):
    """
    Verifies that cluster scaling-up and scaling-down features work correctly.
    Args:
        asg_capacity_time_series: list describing the fluctuations over time in the asg capacity
        compute_nodes_time_series: list describing the fluctuations over time in the compute nodes
        expected_asg_capacity: pair containing the expected asg capacity (min_asg_capacity, max_asg_capacity)
        expected_compute_nodes: pair containing the expected compute nodes (min_compute_nodes, max_compute_nodes)
    """
    assert_that(asg_capacity_time_series, is_not(empty()), "asg_capacity_time_series cannot be empty")
    assert_that(compute_nodes_time_series, is_not(empty()), "compute_nodes_time_series cannot be empty")

    expected_asg_capacity_min, expected_asg_capacity_max = expected_asg_capacity
    expected_compute_nodes_min, expected_compute_nodes_max = expected_compute_nodes
    actual_asg_capacity_max = max(asg_capacity_time_series)
    actual_asg_capacity_min = min(asg_capacity_time_series[asg_capacity_time_series.index(actual_asg_capacity_max) :])
    actual_compute_nodes_max = max(compute_nodes_time_series)
    actual_compute_nodes_min = min(
        compute_nodes_time_series[compute_nodes_time_series.index(actual_compute_nodes_max) :]
    )
    assert_that(
        actual_asg_capacity_min,
        is_(equal_to(expected_asg_capacity_min)),
        "actual asg min capacity does not match the expected one",
    )
    assert_that(
        actual_asg_capacity_max,
        is_(equal_to(expected_asg_capacity_max)),
        "actual asg max capacity does not match the expected one",
    )
    assert_that(
        actual_compute_nodes_min,
        is_(equal_to(expected_compute_nodes_min)),
        "actual number of min compute nodes does not match the expected one",
    )
    assert_that(
        actual_compute_nodes_max,
        is_(equal_to(expected_compute_nodes_max)),
        "actual number of max compute nodes does not match the expected one",
    )


def _assert_test_jobs_completed(cluster_config, max_jobs_exec_time, log_file):
    """
    Verifies that test jobs started by cluster-check.sh script were successfully executed
    and in a timely manner.
    In order to do this the function checks that some files (jobN.done), which denote the fact
    that a job has been correctly executed, are present in the shared cluster file-system.
    Additionally, the function uses the timestamp contained in those files, that indicates
    the end time of each job, to verify that all jobs were executed within the max expected time.
    Args:
        cluster_config: named tuple of type ClusterConfig containing the configuration of the cluster.
        max_jobs_exec_time: max execution time given to the jobs to complete
        log_file: file where to write logs.

    """
    try:
        _exec_ssh_command(
            command="test -f job1.done -a -f job2.done -a -f job3.done",
            username=cluster_config.username,
            host=cluster_config.master_node,
            key_path=cluster_config.key_path,
            stdout=log_file,
        )
        output = _exec_ssh_command(
            command="cat jobs_start_time",
            username=cluster_config.username,
            host=cluster_config.master_node,
            key_path=cluster_config.key_path,
        )
        jobs_start_time = int(output.split()[-1])
        output = _exec_ssh_command(
            command="cat job1.done job2.done job3.done | sort -n | tail -1",
            username=cluster_config.username,
            host=cluster_config.master_node,
            key_path=cluster_config.key_path,
        )
        jobs_completion_time = int(output.split()[-1])
        jobs_execution_time = jobs_completion_time - jobs_start_time
        _double_writeln(log_file, "jobs execution time in seconds: %d" % jobs_execution_time)
        assert_that(
            jobs_execution_time,
            is_(less_than(max_jobs_exec_time)),
            "jobs did not complete the execution in the expected time",
        )
    except sub.CalledProcessError:
        raise AssertionError("Test jobs did not complete in time")


#
# run a single test, possibly in parallel
#
def run_test(
    region, distro, scheduler, instance_type, key_name, expected_asg_capacity, expected_compute_nodes, extra_args
):
    _create_interrupted = False
    _create_done = False
    testname = "%s-%s-%s-%s-%s" % (region, distro, scheduler, instance_type.replace(".", ""), _timestamp)
    test_filename = "%s-config.cfg" % testname
    out_f = open("%s-out.txt" % testname, "w", 0)
    # Test jobs should take at most 9 minutes to be executed.
    # These guarantees that the jobs are executed in parallel.
    max_jobs_exec_time = 9 * 60

    try:
        _double_writeln(out_f, "--> %s: Starting" % testname)

        cluster_config = ClusterConfig(
            config_file=test_filename,
            stack_name="parallelcluster-" + testname,
            region=region,
            distro=distro,
            instance_type=instance_type,
            scheduler=scheduler,
            username=username_map[distro],
            key_path=extra_args["key_path"],
            key_name=key_name,
            master_node="",
            scaledown_idletime=4,
        )

        _write_pcluster_config(cluster_config=cluster_config, extra_args=extra_args)
        _double_writeln(out_f, "--> %s: Created pcluster config file %s" % (testname, test_filename))

        # build the cluster
        _double_writeln(out_f, "--> %s: Creating the cluster" % testname)
        prochelp.exec_command(
            ["pcluster", "create", "--config", test_filename, testname],
            stdout=out_f,
            stderr=sub.STDOUT,
            universal_newlines=True,
        )
        _create_done = True
        _double_writeln(out_f, "--> %s: Cluster created successfully" % testname)

        cluster_config = cluster_config._replace(
            master_node=_get_master_ip(cluster_config_file=test_filename, cluster_name=testname, log_file=out_f)
        )

        _double_writeln(out_f, "--> %s: Executing test jobs on cluster." % testname)
        _execute_test_jobs_on_cluster(cluster_config=cluster_config, log_file=out_f)
        _double_writeln(out_f, "--> %s: Test jobs successfully started" % testname)

        _double_writeln(out_f, "--> %s: Monitoring asg capacity and compute nodes" % testname)
        additional_watching_time = 5 * 60
        asg_capacity_time_series, compute_nodes_time_series, timestamps = _watch_compute_nodes_allocation(
            duration=max_jobs_exec_time + cluster_config.scaledown_idletime * 60 + additional_watching_time,
            frequency=20,
            cluster_config=cluster_config,
        )
        _double_writeln(
            out_f,
            "--> %s: Monitoring completed: %s, %s, %s"
            % (
                testname,
                "asg_capacity_time_series [" + " ".join(map(str, asg_capacity_time_series)) + "]",
                "compute_nodes_time_series [" + " ".join(map(str, compute_nodes_time_series)) + "]",
                "timestamps [" + " ".join(map(str, timestamps)) + "]",
            ),
        )

        _double_writeln(out_f, "--> %s: Verifying test jobs completed successfully" % testname)
        # jobs need to complete in 9 mins in order to verify parallelism
        _assert_test_jobs_completed(
            cluster_config=cluster_config, max_jobs_exec_time=max_jobs_exec_time, log_file=out_f
        )
        _double_writeln(out_f, "--> %s: Test jobs completed successfully" % testname)

        _double_writeln(out_f, "--> %s: Verifying auto-scaling worked correctly" % testname)
        _assert_scaling_works(
            asg_capacity_time_series=asg_capacity_time_series,
            compute_nodes_time_series=compute_nodes_time_series,
            expected_asg_capacity=expected_asg_capacity,
            expected_compute_nodes=expected_compute_nodes,
        )
        _double_writeln(out_f, "--> %s: Autoscaling worked as expected" % testname)

        _double_writeln(out_f, "SUCCESS:  %s!!" % testname)
        open("%s.success" % testname, "w").close()
    except prochelp.ProcessHelperError as exc:
        if not _create_done and isinstance(exc, prochelp.KilledProcessError):
            _create_interrupted = True
            _double_writeln(out_f, "--> %s: Interrupting pcluster create!" % testname)
        _double_writeln(out_f, "!! ABORTED: %s!!" % (testname))
        open("%s.aborted" % testname, "w").close()
        raise exc
    except AssertionError as err:
        _double_writeln(out_f, "--> %s: Test assertion failed: %s" % (testname, err.message))
        _double_writeln(out_f, "!! FAILURE: %s!!" % testname)
        open("%s.failed" % testname, "w").close()
        raise err
    except Exception as exc:
        if not _create_done:
            _create_interrupted = True
        _double_writeln(out_f, "--> %s: Unexpected exception %s: %s" % (testname, str(type(exc)), str(exc)))
        _double_writeln(out_f, "!! FAILURE: %s!!" % testname)
        open("%s.failed" % testname, "w").close()
        raise exc
    finally:
        if _create_interrupted or _create_done:
            # if the create process was interrupted it may take few seconds for the stack id to be actually registered
            _max_del_iters = _del_iters = 10
        else:
            # No delete is necessary if cluster creation wasn't started (process_helper.AbortedProcessError)
            _del_iters = 0
        if _del_iters > 0:
            _del_done = False
            _double_writeln(out_f, "--> %s: Deleting - max iterations: %s" % (testname, _del_iters))
            while not _del_done and _del_iters > 0:
                try:
                    time.sleep(2)
                    # clean up the cluster
                    _del_output = sub.check_output(
                        ["pcluster", "delete", "--config", test_filename, "-nw", testname],
                        stderr=sub.STDOUT,
                        universal_newlines=True,
                    )
                    _del_done = "DELETE_IN_PROGRESS" in _del_output or "DELETE_COMPLETE" in _del_output
                    out_f.write(_del_output + "\n")
                except sub.CalledProcessError as exc:
                    out_f.write(
                        "CalledProcessError exception launching 'pcluster delete': %s - Output:\n%s\n"
                        % (str(exc), exc.output)
                    )
                except Exception as exc:
                    out_f.write(
                        "Unexpected exception launching 'pcluster delete' %s: %s\n" % (str(type(exc)), str(exc))
                    )
                finally:
                    _double_writeln(
                        out_f,
                        "--> %s: Deleting - iteration: %s - successfully submitted: %s"
                        % (testname, (_max_del_iters - _del_iters + 1), _del_done),
                    )
                    _del_iters -= 1

            try:
                prochelp.exec_command(
                    ["pcluster", "status", "--config", test_filename, testname],
                    stdout=out_f,
                    stderr=sub.STDOUT,
                    universal_newlines=True,
                )
            except (prochelp.ProcessHelperError, sub.CalledProcessError):
                # Usually it terminates with exit status 1 since at the end of the delete operation the stack is not found.
                pass
            except Exception as exc:
                out_f.write("Unexpected exception launching 'pcluster status' %s: %s\n" % (str(type(exc)), str(exc)))
        _double_writeln(out_f, "--> %s: Finished" % testname)
        out_f.close()


#
# worker thread, there will be config['parallelism'] of these running
# per region, dispatching work from the work queue
#
def test_runner(region, q, key_name, extra_args):
    global success
    global failure
    global results_lock

    while True:
        item = q.get()

        retval = 1
        # just in case we miss an exception in run_test, don't abort everything...
        try:
            if not prochelp.termination_caught():
                run_test(
                    region=region,
                    distro=item["distro"],
                    scheduler=item["scheduler"],
                    instance_type=item["instance_type"],
                    key_name=key_name,
                    expected_asg_capacity=item["expected_asg_capacity"],
                    expected_compute_nodes=item["expected_compute_nodes"],
                    extra_args=extra_args,
                )
                retval = 0
        except (ReleaseCheckException, prochelp.ProcessHelperError, sub.CalledProcessError):
            pass
        except Exception as exc:
            print("[test_runner] Unexpected exception %s: %s\n" % (str(type(exc)), str(exc)))

        results_lock.acquire(True)
        if retval == 0:
            success += 1
        else:
            failure += 1
        results_lock.release()
        q.task_done()


def _term_handler_parent(_signo, _stack_frame):
    global _termination_caught

    if not _termination_caught:
        _termination_caught = True
        print("Termination handler setting _termination_caught = True")
        print("Sending TERM signal to child process %s" % _child)
        os.kill(_child, signal.SIGTERM)


def _bind_signals_parent():
    signal.signal(signal.SIGINT, _term_handler_parent)
    signal.signal(signal.SIGTERM, _term_handler_parent)
    signal.signal(signal.SIGHUP, _term_handler_parent)


def _main_parent():
    _bind_signals_parent()
    print("Child pid: %s" % _child)
    status = 0
    child_terminated = False
    max_num_exc = 10
    while not child_terminated and max_num_exc > 0:
        try:
            (pid, status) = os.wait()
            child_terminated = True
        except OSError as ose:
            # errno.ECHILD - No child processes
            child_terminated = ose.errno == errno.ECHILD
            if not child_terminated:
                print(
                    "OSError exception while waiting for child process %s, errno: %s - %s"
                    % (_child, errno.errorcode[ose.errno], str(ose))
                )
        except BaseException as exc:
            print(
                "Unexpected exception while waiting for child process %s, %s: %s" % (_child, str(type(exc)), str(exc))
            )
            max_num_exc -= 1
    print("Child pid: %s - Exit status: %s" % (pid, status))
    # status is a 16-bit number, whose low byte is the signal number that killed the process, and whose high byte is the exit status
    exit(status >> 8)


def _bind_signals_child():
    # This is important - otherwise SIGINT propagates downstream to threads and child processes
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, prochelp.term_handler)
    signal.signal(signal.SIGHUP, prochelp.term_handler)


def _proc_alive(pid):
    if pid <= 1:
        return False
    alive = False
    try:
        # No real signal is sent but error checking is performed
        os.kill(pid, 0)
        alive = True
    except OSError as ose:
        # ose.errno == errno.EINVAL - Invalid signal number (this shouldn't happen)
        # ose.errno == errno.ESRCH - No such process
        # ose.errno == errno.EPERM - No permissions to check 'pid' process.
        pass
    except Exception as exc:
        print("Unexpected exception checking process %s, %s: %s" % (pid, str(type(exc)), str(exc)))

    return alive


def _killme_gently():
    os.kill(os.getpid(), signal.SIGTERM)


def _main_child():
    _bind_signals_child()
    parent = os.getppid()
    print("Parent pid: %s" % parent)
    config = {
        "parallelism": 3,
        "regions": "us-east-1,us-east-2,us-west-1,us-west-2,"
        + "ca-central-1,eu-west-1,eu-west-2,eu-central-1,"
        + "ap-southeast-1,ap-southeast-2,ap-northeast-1,"
        + "ap-south-1,sa-east-1,eu-west-3",
        "distros": "alinux,centos6,centos7,ubuntu1404,ubuntu1604",
        "schedulers": "sge,slurm,torque",
        "instance_types": "c4.xlarge",
        "key_path": "",
        "custom_node_url": None,
        "custom_cookbook_url": None,
        "custom_template_url": None,
        "expected_asg_capacity_min": 0,
        "expected_asg_capacity_max": 3,
        "expected_compute_nodes_min": 0,
        "expected_compute_nodes_max": 3,
    }

    parser = argparse.ArgumentParser(description="Test runner for AWS ParallelCluster")
    parser.add_argument("--parallelism", help="Number of tests per region to run in parallel", type=int)
    parser.add_argument("--regions", help="Comma separated list of regions to test", type=str)
    parser.add_argument("--distros", help="Comma separated list of distributions to test", type=str)
    parser.add_argument("--schedulers", help="Comma separated list of schedulers to test", type=str)
    parser.add_argument(
        "--instance-types",
        type=str,
        help="Comma separated list of instance types to use for both Master and Compute nodes",
    )
    parser.add_argument("--key-name", help="Key Pair to use for EC2 instances", type=str, required=True)
    parser.add_argument("--key-path", help="Key path to use for SSH connections", type=str)
    parser.add_argument("--custom-node-url", help="S3 URL to a custom aws-parallelcluster-node package", type=str)
    parser.add_argument(
        "--custom-cookbook-url", help="S3 URL to a custom aws-parallelcluster-cookbook package", type=str
    )
    parser.add_argument(
        "--custom-template-url", help="S3 URL to a custom aws-parallelcluster CloudFormation template", type=str
    )
    parser.add_argument(
        "--expected-asg-capacity-min", help="Expected number of nodes in the asg after scale-down", type=int
    )
    parser.add_argument(
        "--expected-asg-capacity-max", help="Expected number of nodes in the asg after scale-up", type=int
    )
    parser.add_argument(
        "--expected-compute-nodes-min", help="Expected number of nodes in the scheduler after scale-down", type=int
    )
    parser.add_argument(
        "--expected-compute-nodes-max", help="Expected number of nodes in the scheduler after scale-up", type=int
    )

    for key, value in vars(parser.parse_args()).iteritems():
        if value is not None:
            config[key] = value

    region_list = config["regions"].split(",")
    distro_list = config["distros"].split(",")
    scheduler_list = config["schedulers"].split(",")
    instance_type_list = config["instance_types"].split(",")
    expected_asg_capacity = (config["expected_asg_capacity_min"], config["expected_asg_capacity_max"])
    expected_compute_nodes = (config["expected_compute_nodes_min"], config["expected_compute_nodes_max"])

    print("==> Regions: %s" % (", ".join(region_list)))
    print("==> Instance Types: %s" % (", ".join(instance_type_list)))
    print("==> Distros: %s" % (", ".join(distro_list)))
    print("==> Schedulers: %s" % (", ".join(scheduler_list)))
    print("==> Parallelism: %d" % (config["parallelism"]))
    print("==> Key Pair: %s" % (config["key_name"]))
    print("==> Expected asg capacity: min=%d, max=%d " % expected_asg_capacity)
    print("==> Expected compute nodes: min=%d, max=%d " % expected_compute_nodes)

    # Optional params
    if config["key_path"]:
        print("==> Key Path: %s" % (config["key_path"]))
    if config["custom_cookbook_url"]:
        print("==> Custom aws-parallelcluster-cookbook URL: %s" % (config["custom_cookbook_url"]))
    if config["custom_node_url"]:
        print("==> Custom aws-parallelcluster-node URL: %s" % (config["custom_node_url"]))
    if config["custom_template_url"]:
        print("==> Custom aws-parallelcluster template URL: %s" % (config["custom_template_url"]))

    # Populate subnet / vpc data for all regions we're going to test.
    for region in region_list:
        client = boto3.client("ec2", region_name=region)
        response = client.describe_tags(
            Filters=[{"Name": "key", "Values": ["ParallelClusterTestSubnet"]}], MaxResults=16
        )
        if len(response["Tags"]) == 0:
            print("Could not find subnet in %s with ParallelClusterTestSubnet tag.  Aborting." % (region))
            exit(1)
        subnetid = response["Tags"][0]["ResourceId"]

        response = client.describe_subnets(SubnetIds=[subnetid])
        if len(response) == 0:
            print("Could not find subnet info for %s" % (subnetid))
            exit(1)
        vpcid = response["Subnets"][0]["VpcId"]

        setup[region] = {"vpc": vpcid, "subnet": subnetid}

    work_queues = {}
    # build up a per-region list of work to do
    for region in region_list:
        work_queues[region] = Queue.Queue()
        for distro in distro_list:
            for scheduler in scheduler_list:
                for instance in instance_type_list:
                    work_item = {
                        "distro": distro,
                        "scheduler": scheduler,
                        "instance_type": instance,
                        "expected_asg_capacity": expected_asg_capacity,
                        "expected_compute_nodes": expected_compute_nodes,
                    }
                    work_queues[region].put(work_item)

    # start all the workers
    for region in region_list:
        for i in range(0, config["parallelism"]):
            t = threading.Thread(target=test_runner, args=(region, work_queues[region], config["key_name"], config))
            t.daemon = True
            t.start()

    # Wait for all the work queues to be completed in each region
    # WARN: The work_queues[region].join() approach prevents the SIGINT signal to be caught from the main thread,
    #       that is actually blocked in the join.
    all_finished = False
    self_killed = False
    while not all_finished:
        time.sleep(1)
        all_finished = True
        for queue in work_queues.values():
            all_finished = all_finished and queue.unfinished_tasks == 0
        # In the case parent process was SIGKILL-ed
        if not _proc_alive(parent) and not self_killed:
            print("Parent process with pid %s died - terminating..." % parent)
            _killme_gently()
            self_killed = True

    print("%s - Regions workers queues all done: %s" % (_time(), all_finished))

    # print status...
    print("==> Success: %d" % (success))
    print("==> Failure: %d" % (failure))
    if failure != 0:
        exit(1)


if __name__ == "__main__":
    _child = os.fork()

    if _child == 0:
        _main_child()
    else:
        _main_parent()
