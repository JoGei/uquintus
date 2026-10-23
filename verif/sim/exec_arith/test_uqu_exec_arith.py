"""Check real ALU/MUL/DIV siblings sharing a single parent-owned arithmetic slice."""

import json
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from rv32_arithmetic import ALU_OPS, MASK, alu_result, muldiv_result


class ExecArithTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.enabled = self.params['ISA_M']
        self.factor = self.params['MUA_MULDIV_ITERUNROLL']
        self.mul_mode = self.params['MUA_MUL']
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
                     self.dut.res_valid_o, self.dut.alu_arith_use_o,
                     self.dut.muldiv_arith_use_o))

    def latency(self, muldiv, op):
        if not muldiv:
            return 1
        if op >= 4:
            return (2 + self.factor - 1) // self.factor + 32 // self.factor + 1
        return {0: 1, 1: 2, 2: 32 // self.factor, 3: 1}[self.mul_mode]

    def request(self, muldiv, op, a, b):
        self.dut.select_muldiv_i.value = muldiv
        self.dut.req_valid_i.value = 1
        self.dut.req_op_i.value = op
        self.dut.req_a_i.value = a
        self.dut.req_b_i.value = b

    async def initialize(self):
        d = self.dut
        d.clk_i.value = 0
        d.rst_ni.value = 0
        d.flush_i.value = 0
        self.request(0, 0, 0, 0)
        d.req_valid_i.value = 0
        d.res_ready_i.value = 0
        await self.settle()
        assert self.outputs() == (0, 0, 0, 0)
        await self.edge()
        d.rst_ni.value = 1

    async def operation(self, muldiv, op, a, b, hold=0):
        self.request(muldiv, op, a, b)
        expected = muldiv_result(op, a, b) if muldiv else alu_result(op, a, b)
        latency = self.latency(muldiv, op)
        for cycle in range(1, latency + 1):
            self.dut.res_ready_i.value = 0 if hold else int(cycle == latency)
            await self.settle()
            ready, valid, alu_use, muldiv_use = self.outputs()
            context = (muldiv, op, hex(a), hex(b), cycle, latency)
            assert (ready, valid) == (int(cycle == 1), int(cycle == latency)), context
            assert alu_use == int(not muldiv and op in (0, 2, 3, 8)), context
            assert muldiv_use == int(muldiv and (op >= 4 or self.mul_mode == 2)), context
            if valid:
                assert int(self.dut.res_data_o.value) == expected, context
            await self.edge()
            self.dut.req_valid_i.value = 0
            self.dut.req_op_i.value = op ^ 15
            self.dut.req_a_i.value = a ^ MASK
            self.dut.req_b_i.value = b ^ MASK
        for _ in range(hold):
            await self.settle()
            assert self.outputs() == (0, 1, 0, 0)
            assert int(self.dut.res_data_o.value) == expected
            await self.edge()
        if hold:
            self.dut.res_ready_i.value = 1
            await self.settle()
            assert int(self.dut.res_data_o.value) == expected
            await self.edge()
        self.checks += 1

    async def disabled_muldiv(self):
        for op in range(8):
            self.request(1, op, MASK, 0)
            self.dut.res_ready_i.value = 1
            for _ in range(3):
                await self.settle()
                assert self.outputs() == (0, 0, 0, 0)
                await self.edge()
            self.dut.req_valid_i.value = 0
            await self.operation(0, op, MASK, 0)
        self.logger.info('Disabled M: no requests accepted; ALU remains usable')


class MixedTest(ExecArithTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        if not self.enabled:
            await self.disabled_muldiv()
        else:
            values = [0, 1, MASK, 0x80000000, 0x7FFFFFFF]
            for a in values:
                for b in values:
                    for op in range(8):
                        # Switch owners only after the prior result transfers.
                        await self.operation(0, list(ALU_OPS.values())[op], a, b)
                        await self.operation(1, op, a, b, hold=self.rng.randrange(4))
                        await self.operation(0, 8, b, a, hold=self.rng.randrange(4))
            for _ in range(256):
                muldiv = self.rng.randrange(2)
                op = self.rng.randrange(8) if muldiv else self.rng.choice(list(ALU_OPS.values()))
                await self.operation(muldiv, op, self.rng.getrandbits(32),
                                     self.rng.getrandbits(32), hold=self.rng.randrange(5))
        self.logger.info('Shared-parent mixed results: %d', self.checks)
        self.drop_objection()


class ControlTest(ExecArithTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        if not self.enabled:
            await self.disabled_muldiv()
        else:
            for muldiv, op in ((0, 2), (0, 13), (1, 0), (1, 1), (1, 4), (1, 6)):
                latency = self.latency(muldiv, op)
                for reset in (False, True):
                    # Include cancellation before acceptance, mid-compute,
                    # on the result cycle, and while a result is retained.
                    for cut in sorted({0, latency // 2, latency - 1, latency}):
                        self.request(muldiv, op, 0x80000000, MASK)
                        self.dut.res_ready_i.value = 0
                        for _ in range(cut):
                            await self.settle()
                            await self.edge()
                            self.dut.req_valid_i.value = 0
                        if reset:
                            self.dut.rst_ni.value = 0
                        else:
                            self.dut.flush_i.value = 1
                        self.dut.res_ready_i.value = 1
                        await self.settle()
                        assert self.outputs() == (0, 0, 0, 0)
                        await self.edge()
                        self.dut.req_valid_i.value = 0
                        self.dut.rst_ni.value = 1
                        self.dut.flush_i.value = 0
                        # Recover by changing owner, then reuse the canceled unit.
                        await self.operation(0, 0, 0x12345678, 0x87654321)
                        await self.operation(1, 5, MASK, 7)
                        await self.operation(muldiv, op, 3, 2)
        self.logger.info('Shared-parent cancellation/recovery results: %d', self.checks)
        self.drop_objection()


@cocotb.test(timeout_time=2, timeout_unit='ms')
async def mixed(_dut):
    await uvm_root().run_test(MixedTest)


@cocotb.test(timeout_time=2, timeout_unit='ms')
async def control(_dut):
    await uvm_root().run_test(ControlTest)
