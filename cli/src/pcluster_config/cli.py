#!/usr/bin/env python
# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
#

import os
import sys

import argparse

from pcluster.config.hit_converter import HitConverter
from pcluster.config.pcluster_config import PclusterConfig, default_config_file_path


def _err_and_exit(message):
    """Log the given error message and exit nonzero."""
    print(message)
    sys.exit(1)


def _parse_args(argv=None):
    """Parse command line args."""
    default_config_file = default_config_file_path()

    parser = argparse.ArgumentParser(
        description=("Updates the AWS ParallelCluster configuration file."),
        epilog='For command specific flags, please run: "pcluster-config [command] --help"',
    )
    subparsers = parser.add_subparsers()
    subparsers.required = True
    subparsers.dest = "command"

    convert_parser = subparsers.add_parser(
        "convert",
        help=(
            "Convert a 'cluster' section from a ParallelCluster's configuration file "
            "into a format that supports multiple instance types."
        ),
    )
    convert_parser.add_argument(
        "-c",
        "--config-file",
        help="Configuration file to be used as input. Default: {0}".format(default_config_file),
        default=default_config_file,
    )
    convert_parser.add_argument(
        "-t",
        "--cluster-template",
        help=(
            "Indicates the 'cluster' section of the configuration file to convert. "
            "If not specified the script will look for the cluster_template parameter in the [global] section "
            "or will search for '[cluster default]'."
        ),
    )
    convert_parser.add_argument(
        "-o",
        "--output-file",
        help="Configuration file to be written as output. By default the output will be written to the stdout.",
    )
    convert_parser.set_defaults(func=convert)

    return parser.parse_args(argv)


def convert(args=None):
    """Command to convert SIT cluster section into HIT format."""
    try:
        # Build the config based on args
        pcluster_config = PclusterConfig(
            config_file=args.config_file, cluster_label=args.cluster_template, fail_on_file_absence=True
        )

        # Automatic SIT -> HIT conversion, if needed
        conversion_done, reason = HitConverter(pcluster_config).convert(prepare_to_file=True)
        if conversion_done:
            if args.output_file:
                if os.path.isfile(args.output_file):
                    print("ERROR: File {0} already exists, please select another output file.".format(args.output_file))
                    sys.exit(1)
                else:
                    pcluster_config.config_file = args.output_file
                    pcluster_config.to_file(exclude_unrelated_sections=True)
                    print(
                        "Section [cluster {label}] from file {input} has been converted and saved into {output}.\n"
                        "New [queue compute] and [compute_resource default] sections have been created.".format(
                            label=pcluster_config.get_section("cluster").label,
                            input=args.config_file,
                            output=args.output_file,
                        )
                    )
            else:
                print(
                    "Section [cluster {label}] from file {input} has been converted.\n"
                    "New [queue compute] and [compute_resource default] sections have been created.\n"
                    "Configuration file content:\n\n".format(
                        label=pcluster_config.get_section("cluster").label, input=args.config_file
                    )
                )
                pcluster_config.to_file(exclude_unrelated_sections=True, print_stdout=True)
        else:
            print(reason)
    except KeyboardInterrupt:
        print("Exiting...")
        sys.exit(1)
    except Exception as e:
        print("Unexpected error of type %s: %s", type(e).__name__, e)
        sys.exit(1)


def main(argv=None):
    """Run the cli."""
    args = _parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
