import datetime
import os
import Queue
import re
import signal
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
efs_path = "/efs"

#
# global variables (sigh)
#


results_lock = threading.Lock()
failure = 0
success = 0

# PID of the actual test process
_child = 0
# True if parent process has been asked to terminate
_termination_caught = False

_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"
_timestamp = datetime.datetime.now().strftime(_TIMESTAMP_FORMAT)


def prepare_testfiles(distro, vpc_id, subnets, key_name, region, extra_args):
    rfile = open("./config_efs", "r").read().split("\n")
    template_url = extra_args["templateURL"]
    cookbook_url = extra_args["cookbookURL"]
    batch_url = extra_args["batchTemplateURL"]
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
        v = re.search("vpc_id", line)
        if v:
            rfile[index] = "vpc_id = %s" % vpc_id
        s = re.search("master_subnet_id", line)
        if s:
            rfile[index] = "master_subnet_id = %s" % subnets["a1"]
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
        b = re.search("custom_awsbatch_template_url", line)
        if b:
            if batch_url:
                rfile[index] = "custom_awsbatch_template_url = %s" % batch_url
            else:
                rfile[index] = "#custom_awsbatch_template_url ="
    wfile = open("./config-%s-%s" % (region, distro), "w")
    wfile.write("\n".join(rfile))
    wfile.close()


def prepare_vpc(region):
    vpcrelated = {}
    ec2 = boto3.client("ec2", region_name=region)
    response_vpc = ec2.create_vpc(CidrBlock="177.31.0.0/16")
    vpcrelated["vpc_id"] = response_vpc["Vpc"]["VpcId"]

    time.sleep(5)
    ec2.modify_vpc_attribute(EnableDnsHostnames={"Value": True}, VpcId=vpcrelated["vpc_id"])

    response_gateway = ec2.create_internet_gateway()
    vpcrelated["gatewayId"] = response_gateway["InternetGateway"]["InternetGatewayId"]

    ec2.attach_internet_gateway(InternetGatewayId=vpcrelated["gatewayId"], VpcId=vpcrelated["vpc_id"])

    response_rt = ec2.create_route_table(VpcId=vpcrelated["vpc_id"])
    vpcrelated["routetableId"] = response_rt["RouteTable"]["RouteTableId"]

    ec2.create_route(
        DestinationCidrBlock="0.0.0.0/0", RouteTableId=vpcrelated["routetableId"], GatewayId=vpcrelated["gatewayId"]
    )

    return vpcrelated


def prepare_subnets(vpcrelated, region):
    subnets = {}

    ec2 = boto3.client("ec2", region_name=region)
    response_a1 = ec2.create_subnet(
        AvailabilityZone=region + "a", CidrBlock="177.31.0.0/25", VpcId=vpcrelated["vpc_id"]
    )
    subnets["a1"] = response_a1["Subnet"]["SubnetId"]

    response_a2 = ec2.create_subnet(
        AvailabilityZone=region + "a", CidrBlock="177.31.0.128/25", VpcId=vpcrelated["vpc_id"]
    )
    subnets["a2"] = response_a2["Subnet"]["SubnetId"]

    response_c = ec2.create_subnet(
        AvailabilityZone=region + "c", CidrBlock="177.31.16.0/20", VpcId=vpcrelated["vpc_id"]
    )
    subnets["c"] = response_c["Subnet"]["SubnetId"]

    for key in subnets:
        ec2.associate_route_table(RouteTableId=vpcrelated["routetableId"], SubnetId=subnets[key])
        ec2.modify_subnet_attribute(MapPublicIpOnLaunch={"Value": True}, SubnetId=subnets[key])
    return subnets


def create_invalid_rules(group_id, sourceg, ec2):
    # create invalid ingress rules
    ec2.authorize_security_group_ingress(
        GroupId=group_id, IpPermissions=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "111.111.0.0/20"}]}]
    )
    ec2.authorize_security_group_ingress(
        GroupId=group_id, IpPermissions=[{"IpProtocol": "-1", "UserIdGroupPairs": [{"GroupId": sourceg}]}]
    )
    # create invalid egress rules
    ec2.authorize_security_group_egress(
        GroupId=group_id,
        IpPermissions=[
            {"FromPort": 2049, "IpProtocol": "tcp", "IpRanges": [{"CidrIp": "111.111.0.0/20"}], "ToPort": 2049}
        ],
    )
    ec2.authorize_security_group_egress(
        GroupId=group_id, IpPermissions=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "111.111.0.0/20"}]}]
    )
    ec2.authorize_security_group_egress(
        GroupId=group_id, IpPermissions=[{"IpProtocol": "-1", "UserIdGroupPairs": [{"GroupId": sourceg}]}]
    )


def prepare_test_sg(vpc_id, region):
    sg = {}
    ec2 = boto3.client("ec2", region_name=region)
    response_source = ec2.create_security_group(GroupName="sourceGroup", VpcId=vpc_id, Description="SourceGroup")
    sg["sourceGroup"] = response_source["GroupId"]

    response_bad = ec2.create_security_group(GroupName="badSG", VpcId=vpc_id, Description="No public NFS access")
    sg["badSG"] = response_bad["GroupId"]

    response_good = ec2.create_security_group(GroupName="goodSG", VpcId=vpc_id, Description="Public NFS access")
    sg["goodSG"] = response_good["GroupId"]

    ec2.authorize_security_group_ingress(
        GroupId=sg["badSG"],
        IpPermissions=[
            {"FromPort": 2049, "IpProtocol": "tcp", "IpRanges": [{"CidrIp": "111.111.0.0/20"}], "ToPort": 2049}
        ],
    )
    create_invalid_rules(sg["badSG"], sg["sourceGroup"], ec2)

    create_invalid_rules(sg["goodSG"], sg["sourceGroup"], ec2)
    # create Valid ingress rules
    ec2.authorize_security_group_ingress(
        GroupId=sg["goodSG"],
        IpPermissions=[{"FromPort": 2049, "IpProtocol": "tcp", "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "ToPort": 2049}],
    )
    # create Valid egress rules
    ec2.authorize_security_group_egress(
        GroupId=sg["goodSG"],
        IpPermissions=[{"FromPort": 2049, "IpProtocol": "tcp", "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "ToPort": 2049}],
    )
    return sg


def prepare_test_fs(case, subnets, sg, distro, region):
    fsrelated = {}
    efs = boto3.client("efs", region_name=region)
    response_fs = efs.create_file_system(CreationToken="OnlyEFS_%s_%s_%s" % (region, distro, case))
    fsrelated["fsid"] = response_fs["FileSystemId"]
    while True:
        response_fs_state = efs.describe_file_systems(FileSystemId=fsrelated["fsid"])
        life_cycle = response_fs_state["FileSystems"][0]["LifeCycleState"]
        if life_cycle == "available":
            print("FS is good to go!")
            break
        time.sleep(5)
    if case == "createMT":
        response_mt = efs.create_mount_target(
            FileSystemId=fsrelated["fsid"], SubnetId=subnets["c"], SecurityGroups=[sg["badSG"]]
        )

    elif case == "useGoodMT":
        response_mt = efs.create_mount_target(
            FileSystemId=fsrelated["fsid"], SubnetId=subnets["a2"], SecurityGroups=[sg["badSG"], sg["goodSG"]]
        )
    else:
        response_mt = efs.create_mount_target(
            FileSystemId=fsrelated["fsid"], SubnetId=subnets["a2"], SecurityGroups=[sg["badSG"]]
        )
    fsrelated["mtid"] = response_mt["MountTargetId"]
    while True:
        response_mt_state = efs.describe_mount_targets(MountTargetId=fsrelated["mtid"])
        life_cycle = response_mt_state["MountTargets"][0]["LifeCycleState"]
        if life_cycle == "available":
            print("MT is good to go!")
            break
        time.sleep(5)
    time.sleep(5)
    return fsrelated


def clean_up_fs(fsrelated, region):
    try:
        efs = boto3.client("efs", region_name=region)
        efs.delete_mount_target(MountTargetId=fsrelated["mtid"])
        while True:
            # This should return an exception because the mount target id should be not found at this point
            response_mt_state = efs.describe_mount_targets(MountTargetId=fsrelated["mtid"])
            life_cycle = response_mt_state["MountTargets"][0]["LifeCycleState"]
            time.sleep(5)
    except Exception as e:
        print("MT successfully deleted!")
        pass
    try:
        efs.delete_file_system(FileSystemId=fsrelated["fsid"])
        while True:
            # This should return an exception because the file system id should be not found at this point
            response_fs_state = efs.describe_file_systems(FileSystemId=fsrelated["fsid"])
            life_cycle = response_fs_state["FileSystems"][0]["LifeCycleState"]
            time.sleep(5)
    except Exception as e:
        print("FS successfully deleted!")
        pass


def clean_up_testfiles(distro, region):
    os.remove("./config-%s-%s" % (region, distro))


def _dirname():
    return os.path.dirname(os.path.realpath(sys.argv[0]))


def _time():
    return datetime.datetime.now()


def _double_writeln(fileo, message):
    print(message)
    fileo.write(message + "\n")


def run_test(distro, case, subnets, sg, region):
    testname = "%s-%s-%s" % (region, distro, case)
    out_f = open("%s-out.txt" % testname, "w")
    username = username_map[distro]
    _create_done = False
    _create_interrupted = False

    fsrelated = {}
    try:
        if case == "createAll":
            rfile = open("./config-%s-%s" % (region, distro), "r").read().split("\n")
            for index, line in enumerate(rfile):
                m = re.search("efs_fs_id", line)
                if m:
                    rfile[index] = "#efs_fs_id = "

            wfile = open("./config-%s-%s" % (region, distro), "w")
            wfile.write("\n".join(rfile))
            wfile.close()
        else:
            fsrelated = prepare_test_fs(case, subnets, sg, distro, region)
            rfile = open("./config-%s-%s" % (region, distro), "r").read().split("\n")
            for index, line in enumerate(rfile):
                m = re.search("efs_fs_id", line)
                if m:
                    rfile[index] = "efs_fs_id = %s" % fsrelated["fsid"]

            wfile = open("./config-%s-%s" % (region, distro), "w")
            wfile.write("\n".join(rfile))
            wfile.close()

        print("Creating cluster...")
        prochelp.exec_command(
            ["pcluster", "create", "autoTest-%s" % testname, "--config", "./config-%s-%s" % (region, distro)],
            stdout=out_f,
            stderr=sub.STDOUT,
            universal_newlines=True,
        )
        _create_done = True
        dump = prochelp.exec_command(
            ["pcluster", "status", "autoTest-%s" % testname, "--config", "./config-%s-%s" % (region, distro)],
            stderr=sub.STDOUT,
            universal_newlines=True,
        )
        dump_array = dump.splitlines()
        master_ip = ""
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
        ssh_params += ["-o", "ConnectTimeout=60"]
        ssh_params += ["-o", "ServerAliveCountMax=5"]
        ssh_params += ["-o", "ServerAliveInterval=30"]

        prochelp.exec_command(
            ["scp"] + ssh_params + [os.path.join(_dirname(), "efs-check.sh"), "%s@%s:." % (username, master_ip)],
            stdout=out_f,
            stderr=sub.STDOUT,
            universal_newlines=True,
        )

        time.sleep(5)

        if case == "createAll":
            prochelp.exec_command(
                ["ssh", "-n"]
                + ssh_params
                + ["%s@%s" % (username, master_ip), "/bin/bash --login efs-check.sh %s" % efs_path],
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
                    "/bin/bash --login efs-check.sh %s %s" % (efs_path, fsrelated["fsid"]),
                ],
                stdout=out_f,
                stderr=sub.STDOUT,
                universal_newlines=True,
            )
        print("Test passed!!")
    except prochelp.ProcessHelperError as exc:
        if not _create_done and isinstance(exc, prochelp.KilledProcessError):
            _create_interrupted = True
            _double_writeln(out_f, "--> %s: Interrupting pcluster create!" % testname)
        _double_writeln(out_f, "!! ABORTED: %s!!" % testname)
        open("%s.aborted" % testname, "w").close()
        raise exc
    except Exception as exc:
        if not _create_done:
            _create_interrupted = True
        _double_writeln(out_f, "Unexpected exception %s: %s" % (str(type(exc)), str(exc)))
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
                # Should terminates with exit status 1 since at the end of the delete operation the stack is not found.
                pass
            except Exception as exc:
                out_f.write("Unexpected exception launching 'pcluster status' %s: %s\n" % (str(type(exc)), str(exc)))
        if fsrelated:
            clean_up_fs(fsrelated, region)
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
        pass
    except Exception as exc:
        print("Unexpected exception checking process %s, %s: %s" % (pid, str(type(exc)), str(exc)))

    return alive


def test_runner(q, subnets, sgs, region):
    global failure
    global success
    global results_lock

    while True:
        item = q.get()

        retval = 1
        try:
            if not prochelp.termination_caught():
                run_test(distro=item["distro"], case=item["case"], subnets=subnets, sg=sgs, region=region)
                retval = 0
        except (prochelp.ProcessHelperError, sub.CalledProcessError):
            pass
        except Exception as exc:
            print("[test_runner] Unexpected exception %s: %s\n" % (str(type(exc)), str(exc)))
            retval = 1
            pass

        results_lock.acquire(True)
        if retval == 0:
            success += 1
        else:
            failure += 1
        results_lock.release()
        q.task_done()


def clean_up_resources(vpcrelated, subnets, sg, region):
    ec2 = boto3.client("ec2", region_name=region)
    try:
        for key in sg:
            ec2.delete_security_group(GroupId=sg[key])
        for key in subnets:
            ec2.delete_subnet(SubnetId=subnets[key])
        ec2.delete_route_table(RouteTableId=vpcrelated["routetableId"])
        ec2.detach_internet_gateway(InternetGatewayId=vpcrelated["gatewayId"], VpcId=vpcrelated["vpc_id"])
        ec2.delete_internet_gateway(InternetGatewayId=vpcrelated["gatewayId"])
        ec2.delete_vpc(VpcId=vpcrelated["vpc_id"])
    except Exception as exc:
        pass


def get_all_aws_regions():
    ec2 = boto3.client("ec2")
    return set(sorted(r.get("RegionName") for r in ec2.describe_regions().get("Regions"))) - UNSUPPORTED_REGIONS


def main(args):
    global failure
    global success

    for region in args.regions:
        print("Starting work for region %s" % region)
        vpcrelated = prepare_vpc(region)
        subnets = prepare_subnets(vpcrelated, region)
        sgs = prepare_test_sg(vpcrelated["vpc_id"], region)
        parent = os.getppid()
        num_parallel = args.numparallel if args.numparallel else 1
        extra_args = {
            "templateURL": args.templateURL,
            "cookbookURL": args.cookbookURL,
            "batchTemplateURL": args.batchTemplateURL,
        }

        case_list = ["useBadMT", "createAll", "createMT", "useGoodMT"]
        distro_list = args.distros if args.distros else ["alinux", "centos6", "centos7", "ubuntu1404", "ubuntu1604"]

        work_queues = {}
        for distro in distro_list:
            if args.keyname:
                prepare_testfiles(distro, vpcrelated["vpc_id"], subnets, args.keyname, region, extra_args)
            else:
                prepare_testfiles(distro, vpcrelated["vpc_id"], subnets, "id_rsa", region, extra_args)
            work_queues[distro] = Queue.Queue()
            for case in case_list:
                work_item = {"distro": distro, "case": case}
                work_queues[distro].put(work_item)

        for distro in distro_list:
            for i in range(num_parallel):
                t = threading.Thread(target=test_runner, args=(work_queues[distro], subnets, sgs, region))
                t.daemon = True
                t.start()

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
        print("Currently %s success and %s failure" % (success, failure))

        for distro in distro_list:
            clean_up_testfiles(distro, region)
        # print status...
        clean_up_resources(vpcrelated, subnets, sgs, region)

    print(
        "%s success %s failure, expected %s success and %s failure"
        % (success, failure, 3 * len(args.distros) * len(args.regions), len(args.distros) * len(args.regions))
    )
    if failure != len(args.distros) * len(args.regions) or success != 3 * len(args.distros) * len(args.regions):
        exit(1)


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
    parser.add_argument("--batchTemplateURL", type=str, help="Custom batch substack template URL", required=False)
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
