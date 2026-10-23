"""Check one-cycle ALU execution and retained results with real shared arithmetic."""

import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from rv32_arithmetic import ALU_OPS, MASK, alu_result


class AluTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.checks = 0

    async def settle(self):
        await Timer(1, units='ns')

    async def edge(self):
        self.dut.clk_i.value = 1
        await Timer(1, units='ns')
        self.dut.clk_i.value = 0

    def outputs(self):
        return tuple(int(s.value) for s in (self.dut.req_ready_o,
                     self.dut.res_valid_o, self.dut.arith_use_o))

    def request(self, op, a, b):
        self.dut.req_valid_i.value = 1
        self.dut.req_op_i.value = op
        self.dut.req_a_i.value = a
        self.dut.req_b_i.value = b

    async def initialize(self):
        d = self.dut
        d.clk_i.value = 0
        d.rst_ni.value = 0
        d.flush_i.value = 0
        d.req_valid_i.value = 0
        d.req_op_i.value = 0
        d.req_a_i.value = 0
        d.req_b_i.value = 0
        d.res_ready_i.value = 0
        await self.settle()
        assert self.outputs() == (0, 0, 0)
        await self.edge()
        d.rst_ni.value = 1
        await self.settle()
        assert self.outputs() == (1, 0, 0)

    async def operation(self, op, a, b, hold=0):
        expected = alu_result(op, a, b)
        self.request(op, a, b)
        self.dut.res_ready_i.value = int(not hold)
        await self.settle()
        assert self.outputs() == (1, 1, int(op in (0, 2, 3, 8)))
        assert int(self.dut.res_data_o.value) == expected, (op, hex(a), hex(b))
        await self.edge()
        self.dut.req_valid_i.value = 0
        # Invalid inputs and arithmetic responses may change after acceptance.
        self.dut.req_op_i.value = op ^ 15
        self.dut.req_a_i.value = a ^ MASK
        self.dut.req_b_i.value = b ^ MASK
        for _ in range(hold):
            await self.settle()
            assert self.outputs() == (0, 1, 0)
            assert int(self.dut.res_data_o.value) == expected
            await self.edge()
        if hold:
            self.dut.res_ready_i.value = 1
            await self.settle()
            assert self.outputs() == (0, 1, 0)
            assert int(self.dut.res_data_o.value) == expected
            await self.edge()
        self.checks += 1


class DirectedTest(AluTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        values = [0, 1, 2, 0x7FFFFFFF, 0x80000000, 0x80000001,
                  MASK - 1, MASK, 0xAAAAAAAA, 0x55555555]
        for op in ALU_OPS.values():
            for a in values:
                for b in values:
                    await self.operation(op, a, b)
        # Every source-bit/shift-amount combination, with high amount bits set.
        for op in (1, 5, 13):
            for bit in range(32):
                for amount in range(32):
                    await self.operation(op, 1 << bit, amount | 0xFFFFFE00)
        for bit in range(32):
            for op in (0, 8, 2, 3):
                await self.operation(op, (1 << bit) - 1, 1)
                await self.operation(op, 1 << bit, MASK)
        # Reserved internal operation encodings have a deterministic zero fallback;
        # illegal architectural instructions must be rejected by decode.
        for op in set(range(16)) - set(ALU_OPS.values()):
            await self.operation(op, MASK, 31)
        self.logger.info('Directed ALU results: %d', self.checks)
        self.drop_objection()


class RandomizedTest(AluTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        for _ in range(512):
            a, b = self.rng.getrandbits(32), self.rng.getrandbits(32)
            for op in ALU_OPS.values():
                await self.operation(op, a, b, self.rng.randrange(5))
        self.logger.info('Randomized ALU results: %d', self.checks)
        self.drop_objection()


class ControlTest(AluTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        for op in ALU_OPS.values():
            for reset in (False, True):
                for held in (False, True):
                    self.request(op, 0x80000000, MASK)
                    self.dut.res_ready_i.value = 0
                    if held:
                        await self.settle()
                        assert self.outputs()[1] == 1
                        await self.edge()
                        # A second request waits stably through cancellation.
                        self.request(0, 5, 7)
                    if reset:
                        self.dut.rst_ni.value = 0
                    else:
                        self.dut.flush_i.value = 1
                    self.dut.res_ready_i.value = 1
                    await self.settle()
                    assert self.outputs() == (0, 0, 0)
                    await self.edge()
                    self.dut.req_valid_i.value = 0
                    self.dut.rst_ni.value = 1
                    self.dut.flush_i.value = 0
                    await self.settle()
                    assert self.outputs() == (1, 0, 0)
                    await self.operation(op, MASK, 1, hold=3)
            # A pending request must not be accepted on the held result's drain edge.
            self.request(op, 0x80000000, 3)
            self.dut.res_ready_i.value = 0
            await self.settle()
            expected = alu_result(op, 0x80000000, 3)
            await self.edge()
            self.request(0, 5, 7)
            for _ in range(4):
                await self.settle()
                assert self.outputs() == (0, 1, 0)
                assert int(self.dut.res_data_o.value) == expected
                await self.edge()
            self.dut.res_ready_i.value = 1
            await self.settle()
            assert self.outputs() == (0, 1, 0)
            await self.edge()
            await self.operation(0, 5, 7)
        # No bubble between consecutive requests whose results are accepted immediately.
        for _ in range(128):
            await self.operation(self.rng.choice(list(ALU_OPS.values())),
                                 self.rng.getrandbits(32), self.rng.getrandbits(32))
        self.dut.req_valid_i.value = 0
        await self.settle()
        assert self.outputs() == (1, 0, 0)
        self.logger.info('ALU recovery/results: %d', self.checks)
        self.drop_objection()


@cocotb.test(timeout_time=2, timeout_unit='ms')
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test(timeout_time=2, timeout_unit='ms')
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)


@cocotb.test(timeout_time=2, timeout_unit='ms')
async def control(_dut):
    await uvm_root().run_test(ControlTest)
