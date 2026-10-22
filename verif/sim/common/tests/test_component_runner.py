"""Tooling checks for component independence and regression failure reporting."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from component_runner import (ROOT, bender_include_dirs, bender_source_options,
                              check_results, load_component, order_control_files,
                              simulator_build_key)
from hw_config import load_configuration, parameters_for_component


class ComponentRunnerTests(unittest.TestCase):
    def test_hart_id_is_explicit_and_supports_the_full_unsigned_word(self):
        catalog=json.loads((ROOT/'config/selectors.json').read_text())
        config=load_configuration(ROOT/'config/rv32i.yml',catalog)
        self.assertEqual(config['HART_ID'],0)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'hart.yml'
            for value in (0,5,0xa5a50005,0xffffffff):
                path.write_text(yaml.safe_dump(dict(config,HART_ID=value)))
                validated=load_configuration(path,catalog)
                self.assertEqual(parameters_for_component(validated,['HART_ID'],catalog),{'HART_ID':value})
            for value in (-1,True,1.5,'5',0x100000000):
                path.write_text(yaml.safe_dump(dict(config,HART_ID=value)))
                with self.assertRaisesRegex(ValueError,'HART_ID'):
                    load_configuration(path,catalog)
            path.write_text(yaml.safe_dump({k:v for k,v in config.items() if k!='HART_ID'}))
            with self.assertRaisesRegex(ValueError,'missing=.*HART_ID'):
                load_configuration(path,catalog)

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

    def test_imported_sources_require_manifest_opt_in(self):
        manifest = load_component('ex')
        manifest.pop('bender_dependencies_if')
        manifest.pop('bender_targets')
        expected = ['-t', manifest['bender_target'], '-t', 'verilator']
        self.assertEqual(bender_source_options(manifest), expected + ['--no-deps'])
        for enabled in (False, True):
            manifest['bender_dependencies'] = enabled
            (self.directory / 'imported.yml').write_text(yaml.safe_dump(manifest))
            checked = load_component('imported', self.directory)
            self.assertEqual(bender_source_options(checked),
                             expected + ([] if enabled else ['--no-deps']))
        for invalid in (0, 1, 'true'):
            manifest['bender_dependencies'] = invalid
            (self.directory / 'imported.yml').write_text(yaml.safe_dump(manifest))
            with self.assertRaisesRegex(ValueError, 'bender_dependencies.*boolean'):
                load_component('imported', self.directory)
        manifest['bender_dependencies'] = True
        manifest['bender_targets'] = ['tech_cells_generic_exclude_deprecated']
        (self.directory / 'imported.yml').write_text(yaml.safe_dump(manifest))
        checked = load_component('imported', self.directory)
        self.assertEqual(bender_source_options(checked),
                         expected + ['-t', 'tech_cells_generic_exclude_deprecated'])
        for invalid in ('target', ['two', 'two'], [None], [1], ['bad target']):
            manifest['bender_targets'] = invalid
            (self.directory / 'imported.yml').write_text(yaml.safe_dump(manifest))
            with self.assertRaisesRegex(ValueError, 'bender_targets'):
                load_component('imported', self.directory)

    def test_imports_follow_declared_boolean_hardware_parameter(self):
        manifest = load_component('ex')
        self.assertIn('--no-deps', bender_source_options(manifest, parameters={'ISA_ZFINX':0}))
        self.assertNotIn('--no-deps', bender_source_options(manifest, parameters={'ISA_ZFINX':1}))
        with self.assertRaisesRegex(ValueError, 'missing dependency selector'):
            bender_source_options(manifest)
        for invalid in (True, 1, [], 'unknown', 'MUA_FPU_PIPE_REGS_FMA', 'ISA_E'):
            manifest['bender_dependencies_if'] = invalid
            (self.directory / 'bad.yml').write_text(yaml.safe_dump(manifest))
            with self.assertRaisesRegex(ValueError, 'declared boolean'):
                load_component('bad', self.directory)

    def test_file_controls_precede_imports_without_reordering_hdl(self):
        paths = list(map(Path, ['fpnew_pkg.sv', 'fpnew_top.sv', 'cvfpu.vlt', 'uqu_fpu.v']))
        self.assertEqual(order_control_files(paths), [paths[2], paths[0], paths[1], paths[3]])
        self.assertEqual(order_control_files(paths[:2]), paths[:2])

    def test_fpu_configuration_is_explicit_and_validated_when_inactive(self):
        from hw_config import FPU_PIPE_PARAMS

        catalog = json.loads((ROOT / 'config/selectors.json').read_text())
        config = load_configuration(ROOT / 'config/rv32i.yml', catalog)
        self.assertEqual(config['ISA_ZFINX'], 0)
        path = self.directory / 'fpu.yml'
        for name in FPU_PIPE_PARAMS:
            for value in (0, 1, 4):
                path.write_text(yaml.safe_dump(dict(config, **{name:value})))
                self.assertEqual(load_configuration(path, catalog)[name], value)
            for value in (-1, True, 1.5, '2', 0x80000000):
                path.write_text(yaml.safe_dump(dict(config, **{name:value})))
                with self.assertRaisesRegex(ValueError, name):
                    load_configuration(path, catalog)
        names = FPU_PIPE_PARAMS | {'MUA_FPU_PIPE_CONFIG', 'MUA_FPU_DIVSQRT'}
        for name in names:
            path.write_text(yaml.safe_dump({k:v for k,v in config.items() if k != name}))
            with self.assertRaisesRegex(ValueError, 'missing=.*'+name):
                load_configuration(path, catalog)
        for name in ('MUA_FPU_PIPE_CONFIG', 'MUA_FPU_DIVSQRT'):
            for label, entry in catalog[name].items():
                checked = dict(config, **{name:label})
                path.write_text(yaml.safe_dump(checked))
                self.assertEqual(parameters_for_component(load_configuration(path, catalog),
                    [name], catalog), {name:entry['value']})
            path.write_text(yaml.safe_dump(dict(config, **{name:'unknown'})))
            with self.assertRaisesRegex(ValueError, 'unsupported '+name):
                load_configuration(path, catalog)

    def test_zfinx_backends_have_explicit_qualification_guards(self):
        catalog = json.loads((ROOT / 'config/selectors.json').read_text())
        config = load_configuration(ROOT / 'config/rv32i_zfinx.yml', catalog)
        self.assertEqual(config['MUA_FPU_DIVSQRT'], 'th32')
        path = self.directory / 'zfinx.yml'
        for backend in ('th32', 'thmulti'):
            for placement in ('before', 'after', 'inside', 'distributed'):
                path.write_text(yaml.safe_dump(dict(config, MUA_FPU_DIVSQRT=backend,
                                                    MUA_FPU_PIPE_CONFIG=placement)))
                self.assertEqual(load_configuration(path, catalog)['MUA_FPU_DIVSQRT'], backend)
        for count in (0, 2):
            path.write_text(yaml.safe_dump(dict(config, MUA_FPU_DIVSQRT='pulp',
                                                MUA_FPU_PIPE_REGS_DIVSQRT=count)))
            with self.assertRaisesRegex(ValueError, 'pulp.*not qualified'):
                load_configuration(path, catalog)
        path.write_text(yaml.safe_dump(dict(config, ISA_ZFINX=0, MUA_FPU_DIVSQRT='pulp')))
        self.assertEqual(load_configuration(path, catalog)['MUA_FPU_DIVSQRT'], 'pulp')

    def test_selector_mapping_and_generated_header_share_catalog(self):
        from hw_config import write_header

        catalog = {"SELECTOR": {"chosen": {"value": 7, "macro": "UQU_TEST_SELECTOR"}}}
        parameters = parameters_for_component({"SELECTOR": "chosen"}, ["SELECTOR"], catalog)
        write_header(catalog, self.directory)
        header = (self.directory / "uqu_config.vh").read_text()
        self.assertIn(f"`define UQU_TEST_SELECTOR {parameters['SELECTOR']}", header)
        with self.assertRaisesRegex(ValueError, "unknown hardware parameters"):
            parameters_for_component({}, ["UNKNOWN"], catalog)

    def test_elf_requirement_is_an_explicit_manifest_capability(self):
        manifest = load_component('core_elf')
        self.assertTrue(manifest['requires_elf'])
        self.assertEqual(manifest['parameters'], load_component('core')['parameters'])
        self.assertEqual(manifest['tests'], ['execute'])
        manifest['requires_elf'] = 'yes'
        (self.directory / 'bad.yml').write_text(yaml.safe_dump(manifest))
        with self.assertRaisesRegex(ValueError, 'boolean'):
            load_component('bad', self.directory)

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

    def test_branch_predictor_is_explicit_and_encoded(self):
        from hw_config import write_header

        catalog = json.loads((ROOT / "config/selectors.json").read_text())
        config = load_configuration(ROOT / "config/rv32i.yml", catalog)
        name = "MUA_BRANCH_PREDICTOR"
        path = self.directory / "predictor.yml"
        for setting,value in (("none",0),("static_not_taken",1),("bimodal",2)):
            path.write_text(yaml.safe_dump(dict(config, **{name:setting})))
            checked = load_configuration(path,catalog)
            self.assertEqual(parameters_for_component(checked,[name],catalog),{name:value})
        for invalid in (0,True,"dynamic","NONE"):
            path.write_text(yaml.safe_dump(dict(config, **{name:invalid})))
            with self.assertRaisesRegex(ValueError,name):
                load_configuration(path,catalog)
        del config[name]
        path.write_text(yaml.safe_dump(config))
        with self.assertRaisesRegex(ValueError,"missing=.*"+name):
            load_configuration(path,catalog)
        write_header(catalog,self.directory)
        header = (self.directory / "uqu_config.vh").read_text()
        self.assertIn("`define UQU_BP_NONE 0",header)
        self.assertIn("`define UQU_BP_STATIC_NOT_TAKEN 1",header)
        self.assertIn("`define UQU_BP_BIMODAL 2",header)

    def test_predictor_capacity_is_explicit_and_power_of_two(self):
        catalog = json.loads((ROOT / "config/selectors.json").read_text())
        config = load_configuration(ROOT / "config/rv32i.yml", catalog)
        path = self.directory / 'predictor-capacity.yml'
        for value in (2, 4, 16, 32, 1024):
            path.write_text(yaml.safe_dump(dict(config, MUA_BP_ENTRIES=value)))
            self.assertEqual(load_configuration(path, catalog)['MUA_BP_ENTRIES'], value)
        for value in (0, 1, 3, 12, 2048, True, '16', 16.0):
            path.write_text(yaml.safe_dump(dict(config, MUA_BP_ENTRIES=value)))
            with self.assertRaisesRegex(ValueError, 'MUA_BP_ENTRIES'):
                load_configuration(path, catalog)
        del config['MUA_BP_ENTRIES']
        path.write_text(yaml.safe_dump(config))
        with self.assertRaisesRegex(ValueError, 'missing=.*MUA_BP_ENTRIES'):
            load_configuration(path, catalog)

    def test_btb_selection_and_capacity_are_independent(self):
        catalog = json.loads((ROOT / 'config/selectors.json').read_text())
        config = load_configuration(ROOT / 'config/rv32i.yml', catalog)
        path = self.directory / 'btb.yml'
        for predictor in ('none', 'static_not_taken', 'bimodal'):
            for btb, encoded in (('none', 0), ('direct_mapped', 1)):
                for bp, targets in ((2, 32), (32, 2), (16, 16)):
                    path.write_text(yaml.safe_dump(dict(config, MUA_BRANCH_PREDICTOR=predictor,
                        MUA_BTB=btb, MUA_BP_ENTRIES=bp, MUA_BTB_ENTRIES=targets)))
                    checked = load_configuration(path, catalog)
                    self.assertEqual(parameters_for_component(checked, ['MUA_BTB'], catalog), {'MUA_BTB':encoded})
        for value in (0, 1, 3, 2048, True, '16', 16.0):
            path.write_text(yaml.safe_dump(dict(config, MUA_BTB_ENTRIES=value)))
            with self.assertRaisesRegex(ValueError, 'MUA_BTB_ENTRIES'):
                load_configuration(path, catalog)
        for key in ('MUA_BTB', 'MUA_BTB_ENTRIES'):
            path.write_text(yaml.safe_dump({k:v for k,v in config.items() if k != key}))
            with self.assertRaisesRegex(ValueError, 'missing=.*'+key):
                load_configuration(path, catalog)
        path.write_text(yaml.safe_dump(dict(config, MUA_BTB='associative')))
        with self.assertRaisesRegex(ValueError, 'MUA_BTB'):
            load_configuration(path, catalog)

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

    def test_simulator_reuse_requires_matching_inputs_order_parameters_and_tools(self):
        a, b = self.directory / 'a.v', self.directory / 'b.v'
        a.write_text('module a; endmodule')
        b.write_text('module b; endmodule')
        first, second = self.directory / 'first', self.directory / 'second'
        first.mkdir()
        second.mkdir()
        for directory in (first, second):
            (directory / 'config.vh').write_text('`define SETTING 0')

        def key(directory=first, sources=None, parameters=None, simulator='Verilator 5'):
            return simulator_build_key(sources or [a, b], [directory / 'config.vh'],
                [directory], parameters or {'ISA_M': 0}, 'top', simulator, 0, directory)

        self.assertEqual(key(), key(second))  # Output directory alone is irrelevant.
        self.assertNotEqual(key(), key(sources=[b, a]))
        self.assertNotEqual(key(), key(parameters={'ISA_M': 1}))
        self.assertNotEqual(key(), key(simulator='Verilator 6'))
        (second / 'config.vh').write_text('`define SETTING 1')
        self.assertNotEqual(key(), key(second))
    def test_failed_and_skipped_tests_cannot_pass(self):
        path = self.directory / "results.xml"
        for tag in ("failure", "error", "skipped"):
            with self.subTest(tag=tag):
                path.write_text('<testsuites><testsuite><testcase name="smoke">'
                                f'<{tag}/></testcase></testsuite></testsuites>')
                with self.assertRaisesRegex(RuntimeError, "failed or skipped"):
                    check_results(path, ["smoke"])



    def test_instruction_data_depth_is_explicit_and_bounded(self):
        catalog = json.loads((ROOT / 'config/selectors.json').read_text())
        config = load_configuration(ROOT / 'config/rv32i.yml', catalog)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'idata.yml'
            for value in (0, 1, 3, 1024):
                path.write_text(yaml.safe_dump(dict(config, MUA_BTB_IDATA_DEPTH=value)))
                self.assertEqual(load_configuration(path, catalog)['MUA_BTB_IDATA_DEPTH'], value)
            for value in (-1, 1025, True, 1.5, '4'):
                path.write_text(yaml.safe_dump(dict(config, MUA_BTB_IDATA_DEPTH=value)))
                with self.assertRaisesRegex(ValueError, 'MUA_BTB_IDATA_DEPTH'):
                    load_configuration(path, catalog)
            del config['MUA_BTB_IDATA_DEPTH']
            path.write_text(yaml.safe_dump(config))
            with self.assertRaisesRegex(ValueError, 'MUA_BTB_IDATA_DEPTH'):
                load_configuration(path, catalog)

if __name__ == "__main__":
    unittest.main()
