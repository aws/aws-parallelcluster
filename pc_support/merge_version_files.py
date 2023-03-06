import json
import os
import re
import jsonschema

path_to_json_files = os.path.realpath(os.path.dirname(__file__))
json_file_names = sorted([filename for filename in os.listdir(path_to_json_files)
                          if filename.endswith('.json') and filename.startswith('os')])
json_schema = {
    "$schema": "os_support_schema",
    "type": "object",
    "properties": {
        "versions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "version": {
                        "type": "string"
                    },
                    "os": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string"
                                },
                                "description": {
                                    "type": "string"
                                }
                            },
                            "required": [
                                "name",
                                "description"
                            ]
                        }
                    }
                },
                "required": [
                    "version",
                    "os"
                ]
            }
        }
    },
    "required": [
        "versions"
    ]
}


def create_merged_dict(files):
    prev_dir = os.getcwd()
    os.chdir(path_to_json_files)
    versions = list()
    for file in files:
        with open(file, 'r') as infile:
            try:
                version_dict = dict(
                    {
                        'version': re.match("os_(.*).json", file).groups()[0],
                        'os': json.load(infile)['os']
                    }
                )
                versions.append(version_dict)
            except AttributeError:
                raise Exception("All files should respect the 'os_(.*).json' regex")

    merged_dict = dict({'versions': versions})
    os.chdir(prev_dir)
    return merged_dict


def write_merged_json(merged_dict):
    with open(f"{path_to_json_files}/merged_os_support.json", 'w') as output_file:
        json.dump(merged_dict, output_file, indent=4)
        print(f"Written merged json in {path_to_json_files}/merged_os_support.json")


def validate_json(json_data):
    try:
        jsonschema.validate(instance=json_data, schema=json_schema)
    except jsonschema.exceptions.ValidationError as err:
        return False
    return True


if __name__ == "__main__":
    merged_dictionary = create_merged_dict(json_file_names)
    print("Merged JSON data respects the schema" if validate_json(merged_dictionary)
          else "Merged JSON data does not respect the schema")
    write_merged_json(merged_dictionary)
