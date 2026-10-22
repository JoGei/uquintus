"""Check configuration labels against the documented grammar and CLI contract."""

import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

COMMON = Path(__file__).resolve().parents[1]
ROOT = COMMON.parents[2]
sys.path.insert(0, str(COMMON))

from hw_config import configuration_label, load_configuration


BASE_LABEL = (
    "uqu_rv32i_zicsr_umode_mua-gpr:ff_"
    "mua-fw:ex2de+mem2de+mem2ex+wb2ex+wb2de_mua-bp:none_mua-btb:none_mua-ifbuf:2"
)
FORWARD_PARAMS = (
    "MUA_FORWARD_EX_TO_DE", "MUA_FORWARD_MEM_TO_DE",
    "MUA_FORWARD_MEM_TO_EX", "MUA_FORWARD_WB_TO_EX",
)


class ConfigurationLabelTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / "config/selectors.json").read_text())
        self.base = load_configuration(ROOT / "config/rv32i.yml", self.catalog)

    def test_baseline_matches_specification_and_ignores_mapping_order(self):
        self.assertEqual(configuration_label(self.base), BASE_LABEL)
        self.assertEqual(configuration_label(dict(reversed(list(self.base.items())))), BASE_LABEL)

    def test_isa_and_optional_features_have_fixed_order(self):
        config = dict(self.base, ISA_E=1, ISA_M=1, ISA_C=1, ISA_ZIFENCEI=1,
                      ISA_ZFINX=1, XIF=1, XIF_NUM_RS=3, XIF_DUALWRITE=1,
                      ISA_PMP=1, DEBUG=1, MUA_DE_OPERAND_RETENTION=1)
        label = configuration_label(config)
        self.assertTrue(label.startswith(
            "uqu_rv32emc_zicsr_zifencei_zfinx_xif-3rs-dw_umode_pmp_dbg_mua-gpr:ff_"))
        self.assertIn("_mua-opret_mua-c:decompr-if_mua-bp:none_", label)
        self.assertIn("_mua-mul:iter_mua-div:iter_mua-mdu:unroll8_mua-fpu:", label)
        self.assertNotIn("_umode", configuration_label(dict(config, ISA_UMODE=0)))

    def test_xif_source_count_and_dual_write(self):
        for count, dual in itertools.product((2, 3), (0, 1)):
            with self.subTest(count=count, dual=dual):
                token = f"_xif-{count}rs" + ("-dw" if dual else "")
                self.assertIn(token + "_umode", configuration_label(
                    dict(self.base, XIF=1, XIF_NUM_RS=count, XIF_DUALWRITE=dual)))

    def test_every_forwarding_combination_and_master_switch(self):
        tokens = ("ex2de", "mem2de", "mem2ex", "wb2ex")
        for values in itertools.product((0, 1), repeat=4):
            config = dict(self.base, **dict(zip(FORWARD_PARAMS, values)))
            expected = "+".join([token for token, enabled in zip(tokens, values) if enabled]
                                + ["wb2de"])
            with self.subTest(values=values):
                self.assertIn(f"_mua-fw:{expected}_", configuration_label(config))
                disabled = configuration_label(dict(config, MUA_FORWARDING=0))
                self.assertEqual(disabled, BASE_LABEL.replace(
                    "mua-fw:ex2de+mem2de+mem2ex+wb2ex+wb2de", "mua-fw:none"))

    def test_all_compressed_strategies_and_inactive_placement(self):
        for stage in ("if", "de"):
            config = dict(self.base, ISA_C=1, MUA_C_DECOMPRESS_STAGE=stage)
            self.assertIn(f"_mua-c:decompr-{stage}_", configuration_label(config))
            config["MUA_C_IMPL"] = "decode_compressed"
            self.assertEqual(configuration_label(config), BASE_LABEL.replace(
                "rv32i_", "rv32ic_").replace("_mua-bp:", "_mua-c:decode_mua-bp:"))

    def test_mul_implementations_share_one_unroll_field_with_div(self):
        for implementation, token in (("iterative", "iter"), ("parallel", "para"),
                                      ("parallel+stages+2", "para+stages2")):
            for factor in (1, 2, 4, 8, 16, 32):
                config = dict(self.base, ISA_M=1, MUA_MUL=implementation,
                              MUA_MULDIV_ITERUNROLL=factor)
                with self.subTest(implementation=implementation, factor=factor):
                    label = configuration_label(config)
                    self.assertTrue(label.endswith(
                        f"_mua-mul:{token}_mua-div:iter_mua-mdu:unroll{factor}"))
                    self.assertEqual(label.count("unroll"), 1)

    def test_fpu_pipeline_counts_placement_and_backend_are_visible(self):
        for backend in ("th32", "thmulti"):
            for placement in ("before", "after", "inside", "distributed"):
                config = dict(self.base, ISA_ZFINX=1, MUA_FPU_DIVSQRT=backend,
                              MUA_FPU_PIPE_CONFIG=placement, MUA_FPU_PIPE_REGS_FMA=3,
                              MUA_FPU_PIPE_REGS_DIVSQRT=2, MUA_FPU_PIPE_REGS_NONCOMP=0,
                              MUA_FPU_PIPE_REGS_CONV=1)
                with self.subTest(backend=backend, placement=placement):
                    self.assertTrue(configuration_label(config).endswith(
                        f"_mua-fpu:{backend}+pipe-{placement}+fma3+divsqrt2+noncomp0+conv1"))

    def test_register_file_predictor_and_buffer_size(self):
        label = configuration_label(dict(self.base, MUA_REGFILE_IMPL="latch",
                                         MUA_BRANCH_PREDICTOR="static_not_taken",
                                         MUA_IF_BUFFER_WORDS=4))
        self.assertEqual(label, BASE_LABEL.replace("gpr:ff", "gpr:latch")
                         .replace("bp:none", "bp:stnt").replace("ifbuf:2", "ifbuf:4"))
        for capacity in (2, 16, 1024):
            config = dict(self.base, MUA_BRANCH_PREDICTOR="bimodal", MUA_BP_ENTRIES=capacity)
            self.assertIn(f"_mua-bp:bimodal+entries{capacity}_", configuration_label(config))
        self.assertEqual(configuration_label(dict(self.base, MUA_BP_ENTRIES=1024)), BASE_LABEL)

    def test_btb_label_is_independent_and_omits_inactive_capacity(self):
        for predictor in ('static_not_taken', 'bimodal'):
            config = dict(self.base, MUA_BRANCH_PREDICTOR=predictor, MUA_BTB='direct_mapped',
                          MUA_BP_ENTRIES=8, MUA_BTB_ENTRIES=32)
            label = configuration_label(config)
            self.assertIn('_mua-btb:direct+entries32_', label)
            self.assertIn('_mua-bp:bimodal+entries8_' if predictor == 'bimodal' else '_mua-bp:stnt_', label)
        self.assertEqual(configuration_label(dict(self.base, MUA_BTB='direct_mapped', MUA_BTB_ENTRIES=64)), BASE_LABEL)
        self.assertEqual(configuration_label(dict(self.base, MUA_BTB_ENTRIES=64)), BASE_LABEL)

    def test_inactive_settings_and_hart_identity_are_omitted(self):
        config = dict(self.base, HART_ID=42, XIF_NUM_RS=2, XIF_DUALWRITE=1,
                      MUA_C_IMPL="decode_compressed", MUA_C_DECOMPRESS_STAGE="de",
                      MUA_MUL="parallel+stages+2", MUA_MULDIV_ITERUNROLL=32,
                      MUA_FPU_DIVSQRT="pulp", MUA_FPU_PIPE_CONFIG="after",
                      MUA_FPU_PIPE_REGS_FMA=8, MUA_FPU_PIPE_REGS_DIVSQRT=7,
                      MUA_FPU_PIPE_REGS_NONCOMP=6, MUA_FPU_PIPE_REGS_CONV=5)
        self.assertNotEqual(config, self.base)
        self.assertEqual(configuration_label(config), BASE_LABEL)

    def test_all_shipped_presets_produce_lowercase_labels(self):
        for path in sorted((ROOT / "config").glob("*.yml")):
            with self.subTest(preset=path.stem):
                config = load_configuration(path, self.catalog)
                label = configuration_label(config)
                self.assertTrue(label.startswith("uqu_rv32"))
                self.assertEqual(label, label.lower())
                self.assertNotIn(" ", label)

    def run_cli(self, config, cwd):
        return subprocess.run([sys.executable, str(COMMON / "hw_config.py"),
                               "--config", str(config)], cwd=cwd,
                              text=True, capture_output=True)

    def test_cli_accepts_preset_and_external_yaml_without_simulator(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("rv32i", Path(tmp) / "custom.yaml", Path("relative config.yml")):
                if isinstance(name, Path):
                    path = name if name.is_absolute() else Path(tmp) / name
                    path.write_text(yaml.safe_dump(self.base))
                result = self.run_cli(name, tmp)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, BASE_LABEL + "\n")
                self.assertEqual(result.stderr, "")

    def test_cli_rejects_invalid_or_missing_yaml_with_no_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.yml"
            for content, message in (("ISA_E: 0\n", "missing="),
                                     ("[broken", "error:"),
                                     (yaml.safe_dump(dict(self.base, ISA_A=1)), "reserved"),
                                     (yaml.safe_dump(dict(self.base, MUA_MUL="other")), "MUA_MUL")):
                path.write_text(content)
                result = self.run_cli(path, tmp)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn(message, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
            result = self.run_cli(Path(tmp) / "missing.yml", tmp)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertNotIn("Traceback", result.stderr)
            self.assertIn(str(Path(tmp) / "missing.yml"), result.stderr)

    def test_btb_instruction_data_label(self):
        active = dict(self.base, MUA_BRANCH_PREDICTOR='bimodal', MUA_BTB='direct_mapped')
        self.assertIn('mua-btb:direct+entries16+idata-hw8_',
                      configuration_label(dict(active, MUA_BTB_IDATA_HWORDS=8)))
        self.assertNotIn('+idata', configuration_label(active))
        self.assertEqual(configuration_label(dict(self.base, MUA_BTB_IDATA_HWORDS=4)), BASE_LABEL)


if __name__ == "__main__":
    unittest.main()
