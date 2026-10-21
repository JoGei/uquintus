"""Tooling checks for component independence and regression failure reporting."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from component_runner import ROOT, bender_include_dirs, check_results, load_component
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

    def test_retention_parameter_is_explicit_and_boolean(self):
        catalog = json.loads((ROOT / "config/selectors.json").read_text())
        config = load_configuration(ROOT / "config/rv32i.yml", catalog)
        path = self.directory / "retention.yml"
        for setting in (0, 1):
            path.write_text(yaml.safe_dump(dict(config, MUA_DE_OPERAND_RETENTION=setting)))
            self.assertEqual(load_configuration(path, catalog)["MUA_DE_OPERAND_RETENTION"], setting)
        for setting in (2, -1, True, "continuous"):
            path.write_text(yaml.safe_dump(dict(config, MUA_DE_OPERAND_RETENTION=setting)))
            with self.assertRaisesRegex(ValueError, "MUA_DE_OPERAND_RETENTION"):
                load_configuration(path, catalog)
        del config["MUA_DE_OPERAND_RETENTION"]
        path.write_text(yaml.safe_dump(config))
        with self.assertRaisesRegex(ValueError, "missing=.*MUA_DE_OPERAND_RETENTION"):
            load_configuration(path, catalog)

    def test_compressed_decode_selectors_are_explicit_and_encoded(self):
        from hw_config import write_header

        catalog = json.loads((ROOT / "config/selectors.json").read_text())
        config = load_configuration(ROOT / "config/rv32i.yml", catalog)
        names = ["MUA_C_IMPL", "MUA_C_DECOMPRESS_STAGE"]
        path = self.directory / "compressed.yml"
        # Placement stays explicit and valid even when inactive (C=0 or direct).
        for enabled in (0, 1):
            for impl, impl_value in (("decompress", 0), ("decode_compressed", 1)):
                for stage, stage_value in (("if", 0), ("de", 1)):
                    path.write_text(yaml.safe_dump(dict(config, ISA_C=enabled,
                        MUA_C_IMPL=impl, MUA_C_DECOMPRESS_STAGE=stage)))
                    checked = load_configuration(path, catalog)
                    self.assertEqual(parameters_for_component(checked, names, catalog),
                        dict(MUA_C_IMPL=impl_value, MUA_C_DECOMPRESS_STAGE=stage_value))
        for name in names:
            incomplete = {key:value for key,value in config.items() if key != name}
            path.write_text(yaml.safe_dump(incomplete))
            with self.assertRaisesRegex(ValueError, "missing=.*"+name):
                load_configuration(path, catalog)
            for invalid in (0, True, "unknown", "IF", "decoder_c"):
                path.write_text(yaml.safe_dump(dict(config, **{name:invalid})))
                with self.assertRaisesRegex(ValueError, "unsupported "+name):
                    load_configuration(path, catalog)
        write_header(catalog, self.directory)
        header = (self.directory / "uqu_config.vh").read_text()
        for name in names:
            for entry in catalog[name].values():
                self.assertIn(f"`define {entry['macro']} {entry['value']}", header)

    def test_bender_nested_include_dirs_preserve_order_and_paths(self):
        first = self.directory / "first headers"
        second = self.directory / "nested"
        first.mkdir()
        second.mkdir()
        tree = {"include_dirs": [first.name], "files": ["unit.v", {
            "include_dirs": [str(second), first.name], "files": []}]}
        self.assertEqual(bender_include_dirs(tree, self.directory), [first, second])
        self.assertEqual(bender_include_dirs({"files": []}, self.directory), [])
        with self.assertRaisesRegex(ValueError, "does not exist"):
            bender_include_dirs({"include_dirs": ["missing"]}, self.directory)

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
