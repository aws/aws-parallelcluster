import json
from collections import OrderedDict
from glob import glob

import argparse


def _parse_args():
    parser = argparse.ArgumentParser(description="Formats a json document.")
    parser.add_argument("-c", "--check", help="Only checks if file is formatted", action="store_true")
    parser.add_argument("files", help="A space separated list of json files to format", nargs="+")
    return parser.parse_args()


def _format_json(filename):
    with open(filename, "r") as f:
        try:
            unformatted_json = json.load(f, object_pairs_hook=OrderedDict)
        except json.decoder.JSONDecodeError as e:
            print("ERROR: Invalid json document: {error}".format(error=e))
            exit(1)

    return json.dumps(unformatted_json, indent=2, separators=(",", ": ")) + "\n"


def format_files(filenames):
    """
    Format JSON docs provided as input.

    :param filenames: list of JSON docs to format.
    """
    for unexpanded_file in filenames:
        for file in glob(unexpanded_file):
            print("Formatting file: {filename}".format(filename=file))
            formatted_json = _format_json(file)
            with open(file, "w") as f:
                f.write(formatted_json)


def check_formatting(filenames):
    """
    Check that provided JSON docs are correctly formatted.

    :param filenames: list of JSON docs to check.
    :return True if formatting is correct, False otherwise.
    """
    has_failures = False
    for unexpanded_file in filenames:
        for file in glob(unexpanded_file):
            print("Checking file: {filename}".format(filename=file))
            with open(file, "r") as f:
                data = f.read()
            formatted_json = _format_json(file)
            if formatted_json != data:
                has_failures = True
                print("FAILED: fix formatting for file {filename}".format(filename=file))
            else:
                print("SUCCEEDED: {filename} looks good".format(filename=file))

    return not has_failures


args = _parse_args()
if args.check:
    has_failures = check_formatting(args.files)
    exit(not has_failures)
else:
    format_files(args.files)
