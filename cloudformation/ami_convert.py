#!/usr/bin/python
#
# Convert the AMI list in amis.txt to output suitable for copying into
# the json version of the CloudFormation template.
#
# usage: ami_convert.py <path to amis.txt>
#

import re
import sys

if len(sys.argv) != 2:
    sys.stderr.write("usage: %s <amis.txt file>" % (sys.argv[0]))
    sys.exit(1)

amis = sys.argv[1]

regions = {}
current_os = ""

with open(amis, "r") as f:
    for line in f:
        line = line.rstrip()
        if not line:
            continue

        if re.match("# ", line):
            # new OS block
            current_os = re.sub(r"#\s*(\w+).*", r"\1", line)
            continue

        pair = re.split(":", line)
        if len(pair) != 2:
            sys.stderr.write("Unexpected pair length %d for line %s" % (len(pair), line))
            sys.exit(2)
        region = pair[0].strip()
        ami = pair[1].strip()

        if region not in regions:
            regions[region] = {}

        regions[region][current_os] = ami

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
