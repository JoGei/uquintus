"""Treat EX inputs as a parent-owned live slot, not a request queue."""

import json
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from ex_model import FU_ALU, FU_MULDIV, FU_FPU, FU_PASS, assert_outcome, cycles, outcome, random_token, token
from rv32_arithmetic import ALU_OPS, MASK

FIELDS = ('fu', 'op', 'a', 'b', 'c', 'rm', 'pass_data', 'store_data', 'instr',
          'exception_valid', 'exception_cause', 'exception_tval')


class ExTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.checks = 0

    async def settle(self):
        await Timer(1, units='ns')

    async def edge(self):
        self.dut.clk_i.value = 1
        await Timer(1, units='ns')
        self.dut.clk_i.value = 0

    def drive(self, payload):
        for field in FIELDS:
            getattr(self.dut, field + '_i').value = payload[field]

    def outputs(self):
        return tuple(int(getattr(self.dut, field + '_o').value) for field in (
            'result', 'store_data', 'fflags_valid', 'fflags',
            'exception_valid', 'exception_cause', 'exception_tval'))

    def requests(self):
        # Observe actual unit handshakes: a held stage must issue exactly once.
        return tuple(int(unit.req_valid_i.value) & int(unit.req_ready_o.value)
                     for unit in (self.dut.u_alu, self.dut.u_muldiv, self.dut.u_fpu))

    async def initialize(self):
        d = self.dut
        d.clk_i.value = 0
        d.rst_ni.value = 0
        d.flush_i.value = 0
        d.valid_i.value = 0
        d.ready_i.value = 0
        d.operands_ready_i.value = 0
        self.drive(token())
        await self.settle()
        assert not int(d.valid_o.value) and not int(d.ready_o.value)
        assert self.requests() == (0, 0, 0)
        await self.edge()
        d.rst_ni.value = 1
        await self.settle()
        assert int(d.ready_o.value) and not int(d.valid_o.value)

    async def operation(self, payload, wait=0, hold=0):
        self.drive(payload)
        self.dut.valid_i.value = 1
        self.dut.ready_i.value = 0
        expected = outcome(payload, self.params)
        # Known exceptions do not wait for register operands.
        if expected[4]:
            wait = 0
        for _ in range(wait):
            self.dut.operands_ready_i.value = 0
            await self.settle()
            assert not int(self.dut.valid_o.value) and not int(self.dut.ready_o.value)
            assert self.requests() == (0, 0, 0)
            await self.edge()
        self.dut.operands_ready_i.value = int(not expected[4])
        latency = cycles(payload, self.params)
        starts = [0, 0, 0]
        for cycle in range(1, (latency or 256) + 1):
            self.dut.ready_i.value = int((latency is None or cycle == latency) and not hold)
            await self.settle()
            valid = int(self.dut.valid_o.value)
            if latency is not None:
                assert valid == int(cycle == latency), (payload, cycle, latency)
            assert int(self.dut.ready_o.value) == int(valid and not hold)
            requests = self.requests()
            starts = [old + new for old, new in zip(starts, requests)]
            if valid:
                assert_outcome(self.outputs(), expected)
            await self.edge()
            # A native computation must continue even if an external operand
            # producer disappears after acceptance. Its payload stays retained.
            if any(requests) or payload['fu'] == FU_PASS:
                self.dut.operands_ready_i.value = 0 if payload['fu'] != FU_PASS else 1
            if valid:
                break
        else:
            assert False, ('execution watchdog', payload)
        for _ in range(hold):
            await self.settle()
            assert int(self.dut.valid_o.value) and not int(self.dut.ready_o.value)
            assert_outcome(self.outputs(), expected)
            requests = self.requests()
            starts = [old + new for old, new in zip(starts, requests)]
            await self.edge()
        if hold:
            self.dut.ready_i.value = 1
            await self.settle()
            assert int(self.dut.valid_o.value) and int(self.dut.ready_o.value)
            assert_outcome(self.outputs(), expected)
            starts = [old + new for old, new in zip(starts, self.requests())]
            await self.edge()
        expected_starts = [0, 0, 0]
        if not expected[4] and payload['fu'] != FU_PASS:
            expected_starts[payload['fu']] = 1
        assert starts == expected_starts, ('duplicate or missing unit request', payload, starts)
        self.dut.valid_i.value = 0
        await self.settle()
        assert int(self.dut.ready_o.value) and not int(self.dut.valid_o.value)
        assert self.outputs()[2:] == (0,) * 5
        self.checks += 1


class DirectedTest(ExTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        values = [0, 1, MASK, 0x80000000, 0x7FFFFFFF, 31, 32]
        for op in ALU_OPS.values():
            for a in values:
                for b in values:
                    await self.operation(token(op=op, a=a, b=b, store_data=a ^ b))
        for op in range(8):
            for a in values[:5]:
                for b in values[:5]:
                    await self.operation(token(fu=FU_MULDIV, op=op, a=a, b=b), hold=2)
        if self.params['ISA_ZFINX']:
            for op in range(22):
                for rm in range(5):
                    await self.operation(token(fu=FU_FPU, op=op, rm=rm, a=0x3fc00000,
                        b=0x40400000, c=0xbf800000), wait=2, hold=3)
        for payload in (token(fu=FU_PASS, pass_data=0xDEADBEEF, store_data=0x12345678),
                        token(fu=FU_FPU, op=0, instr=0x53),
                        token(fu=FU_ALU, op=31, instr=0xBAD),
                        token(fu=FU_MULDIV, op=8, instr=0xBAD),
                        token(fu=FU_FPU, exception_valid=1, exception_cause=1,
                              exception_tval=0x80001000)):
            await self.operation(payload, hold=3)
        self.logger.info('Directed EX transfers: %d', self.checks)
        self.drop_objection()


class RandomizedTest(ExTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        for index in range(512):
            await self.operation(random_token(self.rng, index, self.params),
                                 wait=self.rng.randrange(4), hold=self.rng.randrange(6))
        self.logger.info('Random EX transfers: %d', self.checks)
        self.drop_objection()


class ControlTest(ExTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        self.dut.ready_i.value = 0
        # Candidate arithmetic is independent of launch/fault/flush controls.
        # None of these observations may start or transfer an operation.
        candidates = [token(op=0, a=0x12345678, b=0x87654321),
                      token(op=8, a=5, b=9),
                      token(fu=FU_PASS, pass_data=0xDEADBEEF)]
        multiply = token(fu=FU_MULDIV, op=1, a=0x80000000, b=0xFFFFFFFF)
        if self.params['ISA_M'] and cycles(multiply, self.params) == 1:
            candidates.append(multiply)
        for payload in candidates:
            self.drive(payload)
            self.dut.operands_ready_i.value = 0
            for valid, fault, flush in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (1, 0, 1)):
                self.dut.valid_i.value = valid
                self.dut.exception_valid_i.value = fault
                self.dut.flush_i.value = flush
                await self.settle()
                assert self.requests() == (0, 0, 0)
                assert int(self.dut.result_o.value) == outcome(payload, self.params)[0]
        self.dut.valid_i.value = 0
        self.dut.flush_i.value = 0
        self.drive(token())
        # An empty parent-owned slot can accept work even behind blocked MEM.
        await self.settle()
        assert int(self.dut.ready_o.value) and not int(self.dut.valid_o.value)
        payloads = [token(op=0, a=1, b=2), token(fu=FU_PASS, pass_data=99),
                    token(exception_valid=1, exception_cause=4, exception_tval=7)]
        if self.params['ISA_M']:
            payloads += [token(fu=FU_MULDIV, op=op, a=0x81234567, b=MASK)
                         for op in (0, 4, 6)]
        if self.params['ISA_ZFINX']:
            payloads += [token(fu=FU_FPU, op=op, a=0x3f800001, b=0x40400000) for op in (0, 3, 4, 18)]
        for payload in payloads:
            latency = cycles(payload, self.params) or 80
            for reset in (False, True):
                for cut in sorted({0, latency // 2, latency - 1, latency, latency + 2}):
                    self.drive(payload)
                    self.dut.valid_i.value = 1
                    self.dut.operands_ready_i.value = 1
                    self.dut.ready_i.value = 0
                    for _ in range(cut):
                        await self.settle()
                        await self.edge()
                    if reset:
                        self.dut.rst_ni.value = 0
                    else:
                        self.dut.flush_i.value = 1
                    self.dut.ready_i.value = 1
                    await self.settle()
                    assert not int(self.dut.valid_o.value) and not int(self.dut.ready_o.value)
                    assert self.requests() == (0, 0, 0)
                    assert self.outputs()[2:] == (0,) * 5
                    await self.edge()
                    self.dut.valid_i.value = 0
                    self.dut.rst_ni.value = 1
                    self.dut.flush_i.value = 0
                    await self.operation(token(op=8, a=0x98765432, b=0x12345678))
                    if self.params['ISA_M']:
                        await self.operation(token(fu=FU_MULDIV, op=5, a=MASK, b=7))
        # Consecutive transfers must not introduce a request/result bubble.
        for index in range(64):
            await self.operation(token(op=0, a=index, b=1))
        self.logger.info('EX control/recovery transfers: %d', self.checks)
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
