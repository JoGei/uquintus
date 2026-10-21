"""Direct compressed controls versus independently assembled base semantics."""
import json
import os
from pathlib import Path
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from compressed_model import compressed
from decode_model import decode


class ExhaustiveTest(uvm_test):
    async def run_phase(self):
        self.raise_objection()
        params = dict(ISA_M=0, ISA_ZFINX=0, ISA_ZIFENCEI=0, ISA_F=0, ISA_A=0, DEBUG=0)
        params.update(json.loads(os.environ['UQU_COMPONENT_PARAMS']))
        for half in range(65536):
            entry = compressed(half)
            expected, _ = decode(entry[1] if entry else 0, params)
            cocotb.top.instr_i.value = half
            await Timer(1, units='ns')
            for name, value in expected.items():
                actual = int(getattr(cocotb.top, name+'_o').value)
                assert actual == value, (hex(half), entry, name, actual, value, params)
        self.logger.info('All 65,536 encodings checked, ISA_E=%d', params['ISA_E'])
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def exhaustive(_dut):
    await uvm_root().run_test(ExhaustiveTest)
