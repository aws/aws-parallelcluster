#!/usr/bin/python
#
# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not
# use this file except in compliance with the License. A copy of the License
# is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, express or implied. See the License for the specific language
# governing permissions and limitations under the License.
#
#
# Print a list of AMIs sorted by base distro and release tag
#
# usage: ./get-ami-list.py <tag1> <tag2> <tag3>

import os
import re
import shutil
import tempfile

import argparse

from git import Repo
from packaging import version

repo_url = "https://github.com/aws/aws-parallelcluster.git"


def parse_amis_txt_x86_only(repo_dir):
    """Parse amis.txt files where all AMIs contained supported only the x86_64 architecture."""
    amis = {}

    supported_architecture = "x86_64"
    file = open(os.path.join(repo_dir, "amis.txt"), "r")
    for line in file:
        os_match = re.match(r"^#\s*(.*)", line)
        if os_match is not None:
            active_distro = os_match.groups()[0]
            amis[active_distro] = {}
            amis[active_distro][supported_architecture] = []
        else:
            m = re.match(r".*:?\s*(ami-[a-zA-Z0-9]*)", line)
            if active_distro is not None:
                amis[active_distro][supported_architecture].append(m.groups()[0])
            else:
                # In old tags, the amis.txt file doesn't contain the distro comment on top
                # because centos6 only was supported
                active_distro = "centos6"
                amis[active_distro][supported_architecture] = []
                amis[active_distro][supported_architecture].append(m.groups()[0])
    return amis


def parse_amis_txt_multiple_architectures(repo_dir):
    """Parse amis.txt files where the AMIs contained may support one of multiple architectures."""
    active_distro = None
    active_architecture = None
    amis = {}

    file = open(os.path.join(repo_dir, "amis.txt"), "r")
    for line in file:
        os_match = re.match(r"^#\s*(.*)", line)
        architecture_match = re.match(r"^##\s*(.*)", line)
        if os_match is not None:
            active_distro = os_match.groups()[0]
            amis[active_distro] = {}
        elif architecture_match is not None:
            active_architecture = architecture_match.group(1)
            amis[active_distro][active_architecture] = []
        else:
            ami_id_match = re.match(r".*:?\s*(ami-[a-zA-Z0-9]*)", line)
            amis[active_distro][active_architecture].append(ami_id_match.group(1))
    return amis


def read_version_for_tag_from_setup(repo_dir, tag):
    setup_path = os.path.join(repo_dir, "cli", "setup.py")
    with open(setup_path) as setup_file:
        for line in setup_file:
            version_match = re.match(r"VERSION\s+=\s+\"(\d+\.\d+\.\d+)\"", line)
            if version_match:
                return version.parse(version_match.group(1))
    raise RuntimeError("Unable to get version associated with tag {tag} from its setup file".format(tag=tag))


def build_release_ami_list(scratch_dir, tag):
    repo_dir = os.path.join(scratch_dir, "aws-parallelcluster")

    if os.path.isdir(repo_dir):
        repo = Repo(repo_dir)
    else:
        repo = Repo.clone_from(repo_url, repo_dir)
    repo.git.checkout(tag)

    # format of amis.txt changed in version 2.8.0 to express the production of AMIs for multiple architectures
    tag_version = read_version_for_tag_from_setup(repo_dir, tag)
    first_architectureful_version = version.parse("2.8.0")
    if tag_version < first_architectureful_version:
        return parse_amis_txt_x86_only(repo_dir)
    else:
        return parse_amis_txt_multiple_architectures(repo_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate list of AMIs for audit")
    parser.add_argument("tags", type=str, nargs="*", help="List of tags for which to pull amis")
    args = parser.parse_args()

    scratch_dir = tempfile.mkdtemp()

    try:
        for tag in sorted(args.tags):
            amis = build_release_ami_list(scratch_dir=scratch_dir, tag=tag)
            for distro in sorted(amis):
                for architecture in sorted(amis[distro]):
                    print("%s %s %s: %s" % (tag, distro, architecture, " ".join(amis[distro][architecture])))
    finally:
        shutil.rmtree(scratch_dir)
