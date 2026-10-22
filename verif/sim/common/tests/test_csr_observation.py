"""Sparse CSR observations retain the independent clock and retirement model."""
from pathlib import Path
import sys
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from csregfile_model import INPUTS
from rvfi_csrs import CSRObservation


class CSRObservationTests(unittest.TestCase):
    def test_idle_and_normal_retirement_advance_counters_without_channels(self):
        config = yaml.safe_load((Path(__file__).resolve().parents[4] / 'config/rv32i.yml').read_text())
        observation = CSRObservation(config)
        inputs = dict(INPUTS, rst_n=0)
        self.assertEqual(observation.step(inputs, False), {})
        for retired in (0, 1, 0, 1):
            inputs.update(rst_n=1, retire=retired)
            self.assertEqual(observation.step(inputs, bool(retired)), {})
        self.assertEqual(observation.model.cycle, 4)
        self.assertEqual(observation.model.instret, 2)
        inputs.update(csr_valid=1, csr_addr=0xb00, csr_op=2, csr_src_zero=1, csr_rd_zero=0, retire=1)
        channels = observation.step(inputs, True)
        self.assertEqual(channels['mcycle']['rdata'], 4)
        self.assertEqual(channels['mcycle']['rmask'], 0xffffffff)
        self.assertEqual(observation.model.cycle, 5)
        self.assertEqual(observation.model.instret, 3)
