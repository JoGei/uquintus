"""Tooling checks for component independence and regression failure reporting."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from component_runner import ROOT, check_results, load_component
from hw_config import load_configuration, parameters_for_component


class ComponentRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_add_component_without_runner_changes(self):
        manifest = {
            "top_module": "uqu_other_unit", "bender_target": "other_unit",
            "test_module": "test_other_unit", "parameters": ["ISA_E"],
            "tests": ["smoke", "corners"],
        }
        (self.directory / "other_unit.yml").write_text(yaml.safe_dump(manifest))
        self.assertEqual(load_component("other_unit", self.directory), manifest)
        catalog = json.loads((ROOT / "config/selectors.json").read_text())
        config = load_configuration(ROOT / "config/rv32i.yml", catalog)
        self.assertEqual(parameters_for_component(config, manifest["parameters"], catalog),
                         {"ISA_E": 0})
        manifest["parameters"] = []
        (self.directory / "other_unit.yml").write_text(yaml.safe_dump(manifest))
        self.assertEqual(load_component("other_unit", self.directory)["parameters"], [])

    def test_selector_mapping_and_generated_header_share_catalog(self):
        from hw_config import write_header

        catalog = {"SELECTOR": {"chosen": {"value": 7, "macro": "UQU_TEST_SELECTOR"}}}
        parameters = parameters_for_component({"SELECTOR": "chosen"}, ["SELECTOR"], catalog)
        write_header(catalog, self.directory)
        header = (self.directory / "uqu_config.vh").read_text()
        self.assertIn(f"`define UQU_TEST_SELECTOR {parameters['SELECTOR']}", header)
        with self.assertRaisesRegex(ValueError, "unknown hardware parameters"):
            parameters_for_component({}, ["UNKNOWN"], catalog)

    def test_results_require_exact_selected_tests(self):
        path = self.directory / "results.xml"
        path.write_text('<testsuites><testsuite><testcase name="smoke"/>'
                        '<testcase name="corners"/></testsuite></testsuites>')
        self.assertEqual(check_results(path, ["smoke", "corners"]), 2)
        with self.assertRaisesRegex(RuntimeError, "do not match selection"):
            check_results(path, ["smoke"])
        path.write_text('<testsuites><testsuite/></testsuites>')
        with self.assertRaises(RuntimeError):
            check_results(path, ["smoke"])

    def test_failed_and_skipped_tests_cannot_pass(self):
        path = self.directory / "results.xml"
        for tag in ("failure", "error", "skipped"):
            with self.subTest(tag=tag):
                path.write_text('<testsuites><testsuite><testcase name="smoke">'
                                f'<{tag}/></testcase></testsuite></testsuites>')
                with self.assertRaisesRegex(RuntimeError, "failed or skipped"):
                    check_results(path, ["smoke"])


if __name__ == "__main__":
    unittest.main()
