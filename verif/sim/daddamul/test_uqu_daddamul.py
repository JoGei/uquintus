"""Independent full-width integer oracle for combinational signed multiplication."""
import os
import random

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test


class MultiplyTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.checks = 0

    async def check(self, a, b, signed_a, signed_b):
        d = self.dut
        d.a_i.value, d.b_i.value = a, b
        d.signed_a_i.value, d.signed_b_i.value = signed_a, signed_b
        await Timer(1, units='ns')
        aa = a - (1 << 32) if signed_a and a & (1 << 31) else a
        bb = b - (1 << 32) if signed_b and b & (1 << 31) else b
        expected = (aa*bb) & ((1 << 64)-1)
        actual = int(d.product_o.value)
        assert actual == expected, (hex(a), hex(b), signed_a, signed_b, hex(actual), hex(expected))
        self.checks += 1


class DirectedTest(MultiplyTest):
    async def run_phase(self):
        self.raise_objection()
        values = [0, 1, 2, 3, 0x7fffffff, 0x80000000, 0x80000001,
                  0xffffffff, 0xfffffffe, 0xaaaaaaaa, 0x55555555]
        for a in values:
            for b in values:
                for sa, sb in ((0, 0), (0, 1), (1, 0), (1, 1)):
                    await self.check(a, b, sa, sb)
        # Every partial-product position, including sign-weight rows/columns.
        for i in range(32):
            for j in range(32):
                for sa, sb in ((0, 0), (0, 1), (1, 0), (1, 1)):
                    await self.check(1 << i, 1 << j, sa, sb)
        self.logger.info('Directed full-width products checked: %d', self.checks)
        self.drop_objection()


class RandomizedTest(MultiplyTest):
    async def run_phase(self):
        self.raise_objection()
        rng = random.Random(int(os.environ['RANDOM_SEED']))
        for _ in range(2048):
            a, b = rng.getrandbits(32), rng.getrandbits(32)
            # Change interpretation while leaving operands unchanged as well.
            for sa, sb in ((0, 0), (0, 1), (1, 0), (1, 1)):
                await self.check(a, b, sa, sb)
        self.logger.info('Randomized full-width products checked: %d', self.checks)
        self.drop_objection()


@cocotb.test()
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test()
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)
