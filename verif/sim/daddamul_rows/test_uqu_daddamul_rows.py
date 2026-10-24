"""Independent full-product and partial-product pattern tests across the two phases."""
from pathlib import Path
import sys

import cocotb
from pyuvm import uvm_root

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from multiplier_test import DirectedTest, RandomizedTest


@cocotb.test()
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test()
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)
