"""Scoreboard native RV32 M results, exact latency, and execution ownership."""

import json
import os
import random
from pathlib import Path
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from rv32_arithmetic import MASK, muldiv_result as reference


class MuldivTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.enabled = self.params['ISA_M']
        self.factor = self.params['MUA_MULDIV_ITERUNROLL']
        self.mul_mode = self.params['MUA_MUL']
        self.operations = range(4,8) if self.mul_mode in (13,) else range(8)
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.checks = 0

    def latency(self, op):
        if op >= 4:
            return (2 + self.factor - 1) // self.factor + 32 // self.factor + 1
        return {2: 32 // self.factor, 3: 1}[self.mul_mode]

    async def settle(self):
        await Timer(1, units='ns')

    async def edge(self):
        self.dut.clk_i.value = 1
        await Timer(1, units='ns')
        self.dut.clk_i.value = 0

    def outputs(self):
        return tuple(int(signal.value) for signal in (
            self.dut.req_ready_o, self.dut.res_valid_o, self.dut.arith_use_o))

    async def initialize(self):
        d = self.dut
        d.clk_i.value = 0
        d.rst_ni.value = 0
        d.flush_i.value = 0
        d.req_valid_i.value = 0
        d.res_ready_i.value = 0
        d.req_op_i.value = 4 if self.mul_mode in (13,) else 0
        d.req_a_i.value = 0
        d.req_b_i.value = 0
        await self.settle()
        assert self.outputs() == (0, 0, 0)
        await self.edge()
        d.rst_ni.value = 1
        await self.settle()
        assert self.outputs() == (self.enabled, 0, 0)

    async def disabled(self):
        # Disabled profiles are verified explicitly, never silently enabled.
        for _ in range(64):
            self.dut.req_valid_i.value = self.rng.randrange(2)
            self.dut.res_ready_i.value = self.rng.randrange(2)
            self.dut.flush_i.value = self.rng.randrange(2)
            self.dut.req_op_i.value = self.rng.randrange(8)
            self.dut.req_a_i.value = self.rng.getrandbits(32)
            self.dut.req_b_i.value = self.rng.getrandbits(32)
            await self.settle()
            assert self.outputs() == (0, 0, 0)
            assert int(self.dut.res_data_o.value) == 0
            await self.edge()
        self.logger.info('Disabled ISA_M profile: 64 inactive-interface checks')

    def request(self, op, a, b):
        self.dut.req_valid_i.value = 1
        self.dut.req_op_i.value = op
        self.dut.req_a_i.value = a
        self.dut.req_b_i.value = b

    async def operation(self, op, a, b, hold=0):
        expected = reference(op, a, b)
        latency = self.latency(op)
        self.request(op, a, b)
        for cycle in range(1, latency + 1):
            # Backpressure before completion must not delay arithmetic progress.
            self.dut.res_ready_i.value = 0 if hold else self.rng.randrange(2)
            if cycle == latency and not hold:
                self.dut.res_ready_i.value = 1
            await self.settle()
            ready, valid, arith = self.outputs()
            context = f'op={op}, a={a:#x}, b={b:#x}, cycle={cycle}/{latency}'
            assert ready == int(cycle == 1), context
            assert valid == int(cycle == latency), context
            assert arith == int(op >= 4 or self.mul_mode == 2), context
            if valid:
                assert int(self.dut.res_data_o.value) == expected, context
            await self.edge()
            # Invalid request payload may change while computation is busy.
            # The accepted instruction must retain its original operands.
            self.request(7 - op, a ^ MASK, b ^ MASK)
            self.dut.req_valid_i.value = 0
        self.dut.req_valid_i.value = 0
        for _ in range(hold):
            self.dut.res_ready_i.value = 0
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
        await self.settle()
        assert self.outputs() == self.idle_outputs(), 'unit did not drain exactly once'
        self.checks += 1

    def idle_outputs(self):
        ready = self.mul_mode not in (13,) or int(self.dut.req_op_i.value) >= 4
        return int(ready), 0, 0

    async def consecutive_multiplies(self):
        if self.mul_mode in (13,):
            # EX owns compression; the local MDU must reject MUL encodings.
            for op in range(4):
                self.request(op, MASK, MASK)
                for _ in range(4):
                    await self.settle()
                    assert self.outputs() == (0, 0, 0)
                    await self.edge()
            self.dut.req_valid_i.value = 0
            return
        if self.latency(0) != 1:
            return
        # Keep valid asserted: every cycle must accept and complete a different
        # operation, with no hidden recovery bubble between single-cycle MULs.
        self.dut.res_ready_i.value = 1
        for index in range(128):
            op = index % 4
            a, b = self.rng.getrandbits(32), self.rng.getrandbits(32)
            self.request(op, a, b)
            await self.settle()
            assert self.outputs() == (1, 1, int(self.mul_mode == 2))
            assert int(self.dut.res_data_o.value) == reference(op, a, b)
            await self.edge()
            self.checks += 1
        self.dut.req_valid_i.value = 0
        await self.settle()
        assert self.outputs() == (1, 0, 0)

    async def pending_request(self):
        # A second, stable request waits through computation and held-result
        # backpressure, then starts only after the first result has drained.
        self.request(5, MASK, 7)
        self.dut.res_ready_i.value = 0
        await self.settle()
        assert self.outputs() == (1, 0, 1)
        await self.edge()
        self.request(6 if self.mul_mode in (13,) else 1, 0x80000000, 0xFFFFFFFF)
        expected = reference(5, MASK, 7)
        for cycle in range(2, self.latency(5) + 1):
            await self.settle()
            assert self.outputs() == (0, int(cycle == self.latency(5)), 1)
            if cycle == self.latency(5):
                assert int(self.dut.res_data_o.value) == expected
            await self.edge()
        for _ in range(3):
            await self.settle()
            assert self.outputs() == (0, 1, 0)
            assert int(self.dut.res_data_o.value) == expected
            await self.edge()
        self.dut.res_ready_i.value = 1
        await self.settle()
        assert self.outputs() == (0, 1, 0)
        await self.edge()
        await self.operation(6 if self.mul_mode in (13,) else 1, 0x80000000, 0xFFFFFFFF)

    async def cancel(self, op, cut, reset=False, held=False):
        self.request(op, 0x81234567, 0xFFFFFFFD)
        self.dut.res_ready_i.value = 0
        count = self.latency(op) if held else cut - 1
        for cycle in range(1, count + 1):
            await self.settle()
            assert self.outputs()[0] == int(cycle == 1)
            assert self.outputs()[1] == int(cycle == self.latency(op))
            await self.edge()
            self.request(op ^ 3, 0xDEADBEEF, 0)
            self.dut.req_valid_i.value = 0
        if reset:
            self.dut.rst_ni.value = 0
        else:
            self.dut.flush_i.value = 1
        self.dut.res_ready_i.value = 1
        await self.settle()
        assert self.outputs() == (0, 0, 0), 'cancellation allowed a transfer'
        await self.edge()
        self.dut.req_valid_i.value = 0
        self.dut.rst_ni.value = 1
        self.dut.flush_i.value = 0
        # Wait longer than the original latency: canceled work must never return.
        for _ in range(self.latency(op) + 1):
            await self.settle()
            assert self.outputs() == self.idle_outputs(), 'stale result after cancellation'
            await self.edge()
        await self.operation((4+(op+1)%4) if self.mul_mode in (13,) else (op+1)%8, 0x80000000, 0xFFFFFFFF)


class DirectedTest(MuldivTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        if not self.enabled:
            await self.disabled()
        else:
            values = [0, 1, 2, 0x7FFFFFFF, 0x80000000, 0x80000001,
                      0xFFFFFFFE, MASK, 0xAAAAAAAA, 0x55555555]
            for op in self.operations:
                for a in values:
                    for b in values:
                        await self.operation(op, a, b)
                for bit in range(32):
                    for a, b in ((1 << bit, 3), (MASK, 1 << bit)):
                        await self.operation(op, a, b)
        self.logger.info('Directed M-extension results/latencies: %d', self.checks)
        self.drop_objection()


class RandomizedTest(MuldivTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        if not self.enabled:
            await self.disabled()
        else:
            for _ in range(256):
                a, b = self.rng.getrandbits(32), self.rng.getrandbits(32)
                for op in self.operations:
                    await self.operation(op, a, b, hold=self.rng.randrange(5))
        self.logger.info('Randomized M-extension results/latencies: %d', self.checks)
        self.drop_objection()


class ControlTest(MuldivTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        if not self.enabled:
            await self.disabled()
        else:
            await self.consecutive_multiplies()
            await self.pending_request()
            for op in self.operations:
                # Every computation phase, result cycle, and held-result state.
                for reset in (False, True):
                    for cut in range(1, self.latency(op) + 1):
                        await self.cancel(op, cut, reset=reset)
                    await self.cancel(op, 0, reset=reset, held=True)
                await self.operation(op, 0, 0, hold=8)
                # Immediate consecutive operations exercise single-cycle units'
                # same-edge request/result transfers and independent execution.
                await self.operation(op, 0xFFFFFFFF, 2)
                await self.operation(op, 0xFFFFFFFF, 2)
        self.logger.info('Control recovery/result checks: %d', self.checks)
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
