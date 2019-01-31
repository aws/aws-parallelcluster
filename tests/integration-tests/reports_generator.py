import json
import os
from xml.etree import ElementTree

from junitparser import JUnitXml


def generate_junitxml_merged_report(test_results_dir):
    """
    Merge all junitxml generated reports in a single one.
    :param test_results_dir: output dir containing the junitxml reports to merge.
    """
    merged_xml = None
    for dir, _, files in os.walk(test_results_dir):
        for file in files:
            if file.endswith("results.xml"):
                if not merged_xml:
                    merged_xml = JUnitXml.fromfile(os.path.join(dir, file))
                else:
                    merged_xml += JUnitXml.fromfile(os.path.join(dir, file))

    merged_xml.write("{0}/test_report.xml".format(test_results_dir), pretty=True)


def generate_json_report(test_results_dir):
    """
    Generate a json report containing a summary of the tests results with details
    for each dimension.
    :param test_results_dir: dir containing the tests outputs.
    :return: a dictionary containing the computed report.
    """
    test_report_file = os.path.join(test_results_dir, "test_report.xml")
    if not os.path.isfile(test_report_file):
        generate_junitxml_merged_report(test_results_dir)

    root = ElementTree.parse(test_report_file).getroot()
    results = {
        "all": {
            "total": int(root.get("tests")),
            "skipped": int(root.get("skipped")),
            "failures": int(root.get("failures")),
            "errors": int(root.get("errors")),
        }
    }
    _record_results(results, root, "./testcase[skipped]/properties/property", "skipped")
    _record_results(results, root, "./testcase[failure]/properties/property", "failures")
    _record_results(results, root, "./testcase[error]/properties/property", "errors")
    _record_results(results, root, "./testcase/properties/property", "total")

    with open("{0}/test_report.json".format(test_results_dir), "w") as out_f:
        out_f.write(json.dumps(results, indent=4))

    return results


def _record_results(results_dict, results_xml_root, xpath_exp, label):
    for skipped in results_xml_root.findall(xpath_exp):
        if not skipped.get("name") in results_dict:
            results_dict[skipped.get("name")] = {}
        if not skipped.get("value") in results_dict[skipped.get("name")]:
            results_dict[skipped.get("name")].update({skipped.get("value"): _empty_results_dict()})
        results_dict[skipped.get("name")][skipped.get("value")][label] += 1


def _empty_results_dict():
    return {"total": 0, "skipped": 0, "failures": 0, "errors": 0}


# generate_tabular_report("1549489575.329696.out", None, None, None, None)
