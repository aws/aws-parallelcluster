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

repo_url = "https://github.com/aws/aws-parallelcluster.git"


def build_release_ami_list(scratch_dir, tag):
    repo_dir = os.path.join(scratch_dir, "aws-parallelcluster")

    if os.path.isdir(repo_dir):
        repo = Repo(repo_dir)
    else:
        repo = Repo.clone_from(repo_url, repo_dir)
    repo.git.checkout(tag)

    active_distro = None
    amis = {}

    file = open(os.path.join(repo_dir, "amis.txt"), "r")
    for line in file:
        m = re.match("^#\s*(.*)", line)
        if not m == None:
            active_distro = m.groups()[0]
            amis[active_distro] = []
        else:
            m = re.match(".*:?\s*(ami-[a-zA-Z0-9]*)", line)
            if active_distro != None:
                amis[active_distro].append(m.groups()[0])
            else:
                # In old tags, the amis.txt file doesn't contain the distro comment on top
                # because centos6 only was supported
                active_distro = "centos6"
                amis[active_distro] = []
                amis[active_distro].append(m.groups()[0])

    return amis


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate list of AMIs for audit")
    parser.add_argument("tags", type=str, nargs="*", help="List of tags for which to pull amis")
    args = parser.parse_args()

    scratch_dir = tempfile.mkdtemp()

    try:
        for tag in sorted(args.tags):
            amis = build_release_ami_list(scratch_dir=scratch_dir, tag=tag)
            for distro in sorted(amis):
                print("%s %s: %s" % (tag, distro, " ".join(amis[distro])))
    finally:
        shutil.rmtree(scratch_dir)
