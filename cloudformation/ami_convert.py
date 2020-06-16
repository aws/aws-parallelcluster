#!/usr/bin/python
#
# Convert the AMI list in amis.txt to output suitable for copying into
# the json version of the CloudFormation template.
#
# usage: ami_convert.py <path to amis.txt>
#

import json
import re
import sys

if len(sys.argv) != 2:
    sys.stderr.write("usage: %s <amis.txt file>" % (sys.argv[0]))
    sys.exit(1)

amis = sys.argv[1]

ARCHITECTURES_TO_MAPPING_NAME = {
    "x86_64": "AWSRegionOS2AMIx86",
    "arm64": "AWSRegionOS2AMIarm64",
}
mappings_to_regions = {}
current_os = ""
current_architecture = ""
current_mapping = ""

with open(amis, "r") as f:
    for line in f:
        line = line.rstrip()
        if not line:
            continue

        if re.match("# ", line):
            # new OS block
            current_os = re.sub(r"#\s*(\w+).*", r"\1", line)
            continue
        elif re.match("## ", line):
            # new architecture block
            current_architecture = re.sub(r"##\s*(\w+).*", r"\1", line)
            current_mapping = ARCHITECTURES_TO_MAPPING_NAME.get(current_architecture)
            continue

        pair = re.split(":", line)
        if len(pair) != 2:
            sys.stderr.write("Unexpected pair length %d for line %s" % (len(pair), line))
            sys.exit(2)
        region = pair[0].strip()
        ami = pair[1].strip()

        if current_mapping not in mappings_to_regions:
            mappings_to_regions[current_mapping] = {}
        if region not in mappings_to_regions[current_mapping]:
            mappings_to_regions[current_mapping][region] = {}

        mappings_to_regions[current_mapping][region][current_os] = ami

print(json.dumps(mappings_to_regions, indent=2))
