import datetime
import os
import Queue
import random
import re
import signal
import string
import subprocess as sub
import sys
import threading
import time
from builtins import exit

import argparse
import boto3

import process_helper as prochelp

UNSUPPORTED_REGIONS = set(["ap-northeast-3", "eu-west-3"])


class ReleaseCheckException(Exception):
    pass


#
# configuration
#
username_map = {
    "alinux": "ec2-user",
    "centos6": "centos",
    "centos7": "centos",
    "ubuntu1404": "ubuntu",
    "ubuntu1604": "ubuntu",
}

testargs_map = {
    "default": "/shared",
    "custom1Vol": "/v1",
    "custom3Vol": "/v1,/v2,/v3",
    "custom5Vol": "/v1,/v2,/v3,/v4,/v5",
}

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


def prepare_testfiles(distro, key_name, extra_args, region):
    rfile = open("./config_ebs", "r").read().split("\n")
    template_url = extra_args["templateURL"]
    cookbook_url = extra_args["cookbookURL"]
    vpc = extra_args["vpc"]
    master_subnet = extra_args["master_subnet"]
    region = extra_args["region"]
    for index, line in enumerate(rfile):
        r = re.search("aws_region_name", line)
        if r:
            rfile[index] = "aws_region_name = %s" % region

        o = re.search("base_os", line)
        if o:
            rfile[index] = "base_os = %s" % distro
        k = re.search("key_name", line)
        if k:
            rfile[index] = "key_name = %s" % key_name
        t = re.search("template_url", line)
        if t:
            if template_url:
                rfile[index] = "template_url = %s" % template_url
            else:
                rfile[index] = "#template_url ="
        c = re.search("custom_chef_cookbook", line)
        if c:
            if cookbook_url:
                rfile[index] = "custom_chef_cookbook = %s" % cookbook_url
            else:
                rfile[index] = "#custom_chef_cookbook ="
        if vpc:
            v = re.search("vpc_id", line)
            if v:
                rfile[index] = "vpc_id = %s" % vpc
        m = re.search("master_subnet_id = (.+)", line)
        if m:
            if master_subnet:
                rfile[index] = "master_subnet_id = %s" % master_subnet
            else:
                extra_args["master_subnet"] = m.group(1)

    wfile = open("./config-%s-%s" % (region, distro), "w")
    wfile.write("\n".join(rfile))
    wfile.close()


def clean_up_testfiles(distro, region):
    os.remove("./config-%s-%s" % (region, distro))


def _dirname():
    return os.path.dirname(os.path.realpath(sys.argv[0]))


def _time():
    return datetime.datetime.now()


def _double_writeln(fileo, message):
    print(message)
    fileo.write(message + "\n")


def _get_az(subnet_id, region):
    ec2 = boto3.resource("ec2", region_name=region)
    subnet = ec2.Subnet(subnet_id)

    az = subnet.availability_zone
    print(subnet_id)
    print(az)

    return az


def run_test(distro, clustername, mastersubnet, region):
    testname = ("%s-%s" % (distro, clustername)) + "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(8)
    )
    print(testname)
    out_f = open("%s-out.txt" % testname, "w")
    username = username_map[distro]
    create_done = False
    create_interrupted = False
    volume_id = ""
    az = _get_az(mastersubnet, region)
    region = az[:-1]

    try:
        ec2 = boto3.client("ec2", region_name=region)
        response_vol = ec2.create_volume(AvailabilityZone=az, Size=10)
        volume_id = response_vol["VolumeId"]
        print("Volume created: %s" % volume_id)

        if volume_id == "":
            _double_writeln(out_f, "!! %s: Volume ID not found; exiting !!" % testname)
            raise ReleaseCheckException("--> %s: Volume ID not found!" % testname)
        _double_writeln(out_f, "--> %s Volume ID: %s" % (testname, volume_id))
        print("Preparing volume...")
        while True:
            response_vol = ec2.describe_volumes(VolumeIds=[volume_id])
            vol_state = response_vol["Volumes"][0]["State"]
            if vol_state == "available":
                print("Volume is good to go!")
                break
            time.sleep(5)

        response_snapshot = ec2.create_snapshot(VolumeId=volume_id)
        snap_id = response_snapshot["SnapshotId"]
        print("Snapshot created: %s" % snap_id)

        if snap_id == "":
            _double_writeln(out_f, "!! %s: Snapshot ID not found; exiting !!" % testname)
            raise ReleaseCheckException("--> %s: Snapshot ID not found!" % testname)
        _double_writeln(out_f, "--> %s Snapshot ID: %s" % (testname, snap_id))
        print("Preparing snapshot...")
        while True:
            response_snap = ec2.describe_snapshots(SnapshotIds=[snap_id])
            snap_state = response_snap["Snapshots"][0]["State"]
            if snap_state == "completed":
                print("Snapshot is good to go!")
                break
            time.sleep(5)

        rfile = open("./config-%s-%s" % (region, distro), "r").read().split("\n")
        for index, line in enumerate(rfile):
            m = re.search("ebs_volume_id", line)
            if m:
                rfile[index] = "ebs_volume_id = %s" % volume_id
            n = re.search("ebs_snapshot_id", line)
            if n:
                rfile[index] = "ebs_snapshot_id = %s" % snap_id

        wfile = open("./config-%s-%s" % (region, distro), "w")
        wfile.write("\n".join(rfile))
        wfile.close()

        print("Creating cluster...")
        prochelp.exec_command(
            [
                "pcluster",
                "create",
                "autoTest-%s" % testname,
                "--config",
                "./config-%s-%s" % (region, distro),
                "--cluster-template",
                "%s" % clustername,
            ],
            stdout=out_f,
            stderr=sub.STDOUT,
            universal_newlines=True,
        )
        create_done = True
        dump = prochelp.exec_command(
            ["pcluster", "status", "autoTest-%s" % testname, "--config", "./config-%s-%s" % (region, distro)],
            stderr=sub.STDOUT,
            universal_newlines=True,
        )
        master_ip = ""
        dump_array = dump.splitlines()
        for line in dump_array:
            m = re.search("MasterPublicIP: (.+)$", line)
            if m:
                master_ip = m.group(1)
                break
        if master_ip == "":
            _double_writeln(out_f, "!! %s: Master IP not found; exiting !!" % testname)
            raise ReleaseCheckException("--> %s: Master IP not found!" % testname)
        _double_writeln(out_f, "--> %s Master IP: %s" % (testname, master_ip))

        time.sleep(10)

        # run test on the cluster...
        ssh_params = ["-o", "StrictHostKeyChecking=no"]
        ssh_params += ["-o", "BatchMode=yes"]
        # ssh_params += ['-o', 'ConnectionAttempts=30']
        ssh_params += ["-o", "ConnectTimeout=60"]
        ssh_params += ["-o", "ServerAliveCountMax=5"]
        ssh_params += ["-o", "ServerAliveInterval=30"]

        print("Running tests...")
        prochelp.exec_command(
            ["scp"] + ssh_params + [os.path.join(_dirname(), "ebs-check.sh"), "%s@%s:." % (username, master_ip)],
            stdout=out_f,
            stderr=sub.STDOUT,
            universal_newlines=True,
        )

        time.sleep(5)

        if clustername == "custom3Vol" or clustername == "custom5Vol":
            prochelp.exec_command(
                ["ssh", "-n"]
                + ssh_params
                + [
                    "%s@%s" % (username, master_ip),
                    "/bin/bash --login ebs-check.sh %s %s %s %s"
                    % (testargs_map[clustername], region, volume_id, snap_id),
                ],
                stdout=out_f,
                stderr=sub.STDOUT,
                universal_newlines=True,
            )
        else:
            prochelp.exec_command(
                ["ssh", "-n"]
                + ssh_params
                + [
                    "%s@%s" % (username, master_ip),
                    "/bin/bash --login ebs-check.sh %s %s" % (testargs_map[clustername], region),
                ],
                stdout=out_f,
                stderr=sub.STDOUT,
                universal_newlines=True,
            )

    except prochelp.ProcessHelperError as exc:
        if not create_done and isinstance(exc, prochelp.KilledProcessError):
            create_interrupted = True
            _double_writeln(out_f, "--> %s: Interrupting AWS ParallelCluster create!" % testname)
        _double_writeln(out_f, "!! ABORTED: %s!!" % testname)
        open("%s.aborted" % testname, "w").close()
        raise exc
    except Exception as exc:
        if not create_done:
            create_interrupted = True
        _double_writeln(out_f, "Unexpected exception %s: %s" % (str(type(exc)), str(exc)))
        _double_writeln(out_f, "!! FAILURE: %s!!" % testname)
        open("%s.failed" % testname, "w").close()
        raise exc

    finally:
        print("Cleaning up!")
        if create_interrupted or create_done:
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
                        [
                            "pcluster",
                            "delete",
                            "autoTest-%s" % testname,
                            "--config",
                            "./config-%s-%s" % (region, distro),
                        ],
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
                    ["pcluster", "status", "autoTest-%s" % testname, "--config", "./config-%s-%s" % (region, distro)],
                    stdout=out_f,
                    stderr=sub.STDOUT,
                    universal_newlines=True,
                )
            except (prochelp.ProcessHelperError, sub.CalledProcessError):
                # Usually it terminates with exit status 1 since at the end of the delete operation
                # the stack is not found.
                pass
            except Exception as exc:
                out_f.write("Unexpected exception launching 'pcluster status' %s: %s\n" % (str(type(exc)), str(exc)))
        ec2.delete_snapshot(SnapshotId=snap_id)
        ec2.delete_volume(VolumeId=volume_id)
        out_f.close()
    print("--> %s: Finished" % testname)


def _killme_gently():
    os.kill(os.getpid(), signal.SIGTERM)


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


def test_runner(q, extra_args):
    global failure
    global success
    global results_lock

    while True:
        item = q.get()

        retval = 1
        try:
            if not prochelp.termination_caught():
                run_test(
                    distro=item["distro"],
                    clustername=item["clustername"],
                    mastersubnet=extra_args["master_subnet"],
                    region=extra_args["region"],
                )
                retval = 0
        except (prochelp.ProcessHelperError, sub.CalledProcessError):
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


def get_all_aws_regions():
    ec2 = boto3.client("ec2")
    return set(sorted(r.get("RegionName") for r in ec2.describe_regions().get("Regions"))) - UNSUPPORTED_REGIONS


def main(args):
    global failure
    global success
    total_success = 0
    total_failure = 0

    for region in args.regions:
        print("Starting work for region %s" % region)
        failure = 0
        success = 0
        client = boto3.client("ec2", region_name=region)
        response = client.describe_tags(
            Filters=[{"Name": "key", "Values": ["ParallelClusterTestSubnet"]}], MaxResults=16
        )
        if not args.mastersubnet:
            if len(response["Tags"]) == 0:
                print("Could not find subnet in %s with ParallelClusterTestSubnet tag.  Aborting." % (region))
                exit(1)
            subnetid = response["Tags"][0]["ResourceId"]
            if subnetid is None:
                print("Error: Subnet ID is None")

            response = client.describe_subnets(SubnetIds=[subnetid])
            if len(response) == 0:
                print("Could not find subnet info for %s" % (subnetid))
                exit(1)
            vpcid = response["Subnets"][0]["VpcId"]

            if vpcid is None:
                print("Error: VPC ID is None")

            print("VPCId: %s; SubnetId %s" % (vpcid, subnetid))
            setup[region] = {"vpc": vpcid, "subnet": subnetid}

        key_name = args.keyname
        parent = os.getppid()
        num_parallel = args.numparallel if args.numparallel else 1
        extra_args = {
            "templateURL": args.templateURL,
            "cookbookURL": args.cookbookURL,
            "vpc": args.vpcid if args.vpcid else setup[region]["vpc"],
            "master_subnet": args.mastersubnet if args.mastersubnet else setup[region]["subnet"],
            "region": region,
        }
        success_cluster_list = ["custom3Vol", "custom5Vol", "default", "custom1Vol"]
        failure_cluster_list = ["custom6Vol"]
        distro_list = args.distros if args.distros else ["alinux", "centos6", "centos7", "ubuntu1404", "ubuntu1604"]
        success_work_queues = {}
        failure_work_queues = {}
        for distro in distro_list:
            if key_name:
                prepare_testfiles(distro, key_name, extra_args, region)
            else:
                prepare_testfiles(distro, "id_rsa", extra_args, region)
            success_work_queues[distro] = Queue.Queue()
            failure_work_queues[distro] = Queue.Queue()
            for clustername in success_cluster_list:
                work_item = {"distro": distro, "clustername": clustername}
                success_work_queues[distro].put(work_item)
            for clustername in failure_cluster_list:
                work_item = {"distro": distro, "clustername": clustername}
                failure_work_queues[distro].put(work_item)

        for distro in distro_list:
            for i in range(num_parallel):
                t = threading.Thread(target=test_runner, args=(success_work_queues[distro], extra_args))
                t.daemon = True
                t.start()

        all_finished = False
        self_killed = False
        while not all_finished:
            time.sleep(1)
            all_finished = True
            for queue in success_work_queues.values():
                all_finished = all_finished and queue.unfinished_tasks == 0
            # In the case parent process was SIGKILL-ed
            if not _proc_alive(parent) and not self_killed:
                print("Parent process with pid %s died - terminating..." % parent)
                _killme_gently()
                self_killed = True

        print("%s - Distributions workers queues all done: %s" % (_time(), all_finished))
        if success != 20 or failure != 0:
            print("ERROR: expected 20 success 0 failure, got %s success %s failure" % (success, failure))
            exit(1)

        for distro in distro_list:
            for i in range(num_parallel):
                t = threading.Thread(target=test_runner, args=(failure_work_queues[distro], extra_args))
                t.daemon = True
                t.start()

        all_finished = False
        self_killed = False
        while not all_finished:
            time.sleep(1)
            all_finished = True
            for queue in failure_work_queues.values():
                all_finished = all_finished and queue.unfinished_tasks == 0
            # In the case parent process was SIGKILL-ed
            if not _proc_alive(parent) and not self_killed:
                print("Parent process with pid %s died - terminating..." % parent)
                _killme_gently()
                self_killed = True

        print("%s - Distributions workers queues all done: %s" % (_time(), all_finished))
        if failure != 5:
            print("ERROR: expected 5 failure, %s failure" % failure)
            exit(1)

        for distro in distro_list:
            clean_up_testfiles(distro, region)
        # print status...

        print("Region %s test finished" % region)

        total_success += success
        total_failure += failure

    print(
        "Expected %s success and %s failure, got %s success and %s failure"
        % (20 * len(args.regions), 5 * len(args.regions), total_success, total_failure)
    )
    if total_success == 20 * len(args.regions) and total_failure == 5 * len(args.regions):
        print("Test finished")
    else:
        print("FAILURE!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Take in test related parameters")
    parser.add_argument("--keyname", type=str, help="Keyname, default is id_rsa", required=False)
    parser.add_argument(
        "--regions", type=str, help="Comma separated list of regions to test, defaults to all", required=False
    )
    parser.add_argument(
        "--distros", type=str, help="Comma separated list of distributions to test, defaults to all", required=False
    )
    parser.add_argument("--templateURL", type=str, help="Custom template URL", required=False)
    parser.add_argument("--cookbookURL", type=str, help="Custom cookbook URL", required=False)
    parser.add_argument("--vpcid", type=str, help="VPC ID for testing", required=False)
    parser.add_argument("--mastersubnet", type=str, help="Master Subnet ID for testing", required=False)
    parser.add_argument(
        "--numparallel",
        type=int,
        help="number of threads to run in parallel per distribution, " "total number of threads will be 5*numparallel",
        required=False,
    )
    args = parser.parse_args()
    if not args.regions:
        args.regions = get_all_aws_regions()
    else:
        args.regions = args.regions.split(",")

    if args.distros:
        args.distros = args.distros.split(",")

    main(args)
