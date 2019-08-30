#!/usr/bin/python
#
# Convert the AMI list in amis.yml to output suitable for copying into
# the json version of the CloudFormation template.
#
# usage: ami_convert.py <path to amis.yml>
#

import re
import sys
import yaml
import collections

if len(sys.argv) != 2:
    sys.stderr.write("usage: %s <amis.yml file>" % (sys.argv[0]))
    sys.exit(1)

amis = sys.argv[1]

regions = collections.defaultdict(dict)
current_os = ""

with open(amis, "r") as f:
    amis_yml = yaml.load(f.read(), Loader=yaml.FullLoader)

# -- Sort by (region, OS) instead of (OS, region)
for kos, vos in amis_yml.items():
    for kregion, vregions in vos.items():
        regions[kregion][kos] = amis_yml[kos][kregion]

first_region = 1
for region in sorted(regions):
    if first_region == 1:
        first_region = 0
    else:
        sys.stdout.write(",\n")
    sys.stdout.write('      "%s" : {\n' % region)
    first_os = 1
    for os in sorted(regions[region]):
        if first_os == 1:
            first_os = 0
        else:
            sys.stdout.write(",\n")
        sys.stdout.write('        "%s" : "%s"' % (os, regions[region][os]))
    sys.stdout.write("\n      }")
sys.stdout.write("\n")
