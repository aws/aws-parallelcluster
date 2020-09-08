import difflib
import json
from collections import OrderedDict
from glob import glob

import argparse
from cfn_flip import dump_yaml, load_yaml


def _parse_args():
    parser = argparse.ArgumentParser(description="Formats a CloudFormation document.")
    parser.add_argument("-c", "--check", help="Only checks if file is formatted", action="store_true")
    parser.add_argument("--format", choices=["json", "yaml"], help="The format of the template", required=True)
    parser.add_argument("files", help="A space separated list of template files to format", nargs="+")
    return parser.parse_args()


def _format_yaml(filename):
    with open(filename, "r") as f:
        try:
            unformatted_yaml = load_yaml(f)
        except Exception as e:
            print("ERROR: Invalid yaml document: {error}".format(error=e))
            exit(1)

    return dump_yaml(unformatted_yaml, clean_up=True)


def _format_json(filename):
    with open(filename, "r") as f:
        try:
            unformatted_json = json.load(f, object_pairs_hook=OrderedDict)
        except json.decoder.JSONDecodeError as e:
            print("ERROR: Invalid json document: {error}".format(error=e))
            exit(1)

    return json.dumps(unformatted_json, indent=2, separators=(",", ": ")) + "\n"


FORMAT_TO_PARSING_FUNC = {"json": _format_json, "yaml": _format_yaml}


def format_files(filenames, format):
    """
    Format CFN docs provided as input.

    :param filenames: list of CFN docs to format.
    :param format: json or yaml
    """
    for unexpanded_file in filenames:
        for file in glob(unexpanded_file):
            print("Formatting file: {filename}".format(filename=file))
            formatted_doc = FORMAT_TO_PARSING_FUNC[format](file)
            with open(file, "w") as f:
                f.write(formatted_doc)


def check_formatting(filenames, format):
    """
    Check that provided CFN docs are correctly formatted.

    :param filenames: list of CFN docs to check.
    :return True if formatting is correct, False otherwise.
    """
    has_failures = False
    for unexpanded_file in filenames:
        for file in glob(unexpanded_file):
            print("Checking file: {filename}".format(filename=file))
            with open(file, "r") as f:
                data = f.read()
            formatted_doc = FORMAT_TO_PARSING_FUNC[format](file)
            if formatted_doc != data:
                has_failures = True
                print(
                    "FAILED: fix formatting for file {filename} and "
                    "double check newlines at the end of the file".format(filename=file)
                )
                for line in difflib.unified_diff(formatted_doc.splitlines(), data.splitlines()):
                    print(line)
            else:
                print("SUCCEEDED: {filename} looks good".format(filename=file))

    return not has_failures


if __name__ == "__main__":
    args = _parse_args()
    if args.check:
        is_successful = check_formatting(args.files, args.format)
        exit(not is_successful)
    else:
        format_files(args.files, args.format)
