import json
import os


def test_valid_json():
    """Verify cfn templates are correctly formatted."""
    invalid_json = False
    for filename in os.listdir(".."):
        if filename.endswith(".cfn.json"):
            print("Validating json file: %s" % filename)
            with open(f"../{filename}") as f:
                try:
                    json.load(f)
                    print("SUCCESS: Valid json.")
                except ValueError as e:
                    print("ERROR: Invalid json: %s" % e)
                    invalid_json = True

    assert not invalid_json
