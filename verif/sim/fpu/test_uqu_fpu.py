"""Compare the real FPnew adapter with exact arithmetic, including its lifecycle."""
import itertools
import json
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from fpu_model import NAMES, result

VALUES = (0, 0x80000000, 1, 0x007fffff, 0x00800000, 0x3f000000,
          0x3f800000, 0xbf800000, 0x40000000, 0x7f7fffff, 0xff7fffff,
          0x7f800000, 0xff800000, 0x7fc12345, 0x7f812345, 0xff812345)


class FpuTest(uvm_test):
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

    def outputs(self):
        return (int(self.dut.res_data_o.value), int(self.dut.res_fflags_o.value))

    async def initialize(self):
        d = self.dut
        for key in ('clk_i', 'rst_ni', 'flush_i', 'req_valid_i', 'res_ready_i',
                    'req_op_i', 'req_a_i', 'req_b_i', 'req_c_i', 'req_rm_i'):
            getattr(d, key).value = 0
        for _ in range(2):
            await self.settle()
            assert not int(d.res_valid_o.value) and not int(d.req_ready_o.value)
            await self.edge()
        d.rst_ni.value = 1
        await self.settle()
        await self.edge()  # Release the clock-sampled imported reset.
        await self.settle()

    def drive(self, op, a, b=0, c=0, rm=0):
        for key, val in zip(('op', 'a', 'b', 'c', 'rm'), (op, a, b, c, rm)):
            getattr(self.dut, 'req_' + key + '_i').value = val

    async def idle(self, cycles=2):
        self.dut.req_valid_i.value = 0
        self.dut.res_ready_i.value = 1
        for _ in range(cycles):
            await self.settle()
            assert not int(self.dut.res_valid_o.value), 'stale or duplicate result'
            assert self.outputs() == (0, 0)
            await self.edge()

    async def operation(self, op, a, b=0, c=0, rm=0, hold=0):
        d = self.dut
        self.drive(op, a, b, c, rm)
        d.req_valid_i.value = 1
        d.res_ready_i.value = 0
        expected = result(op, a, b, c, rm)
        accepted = 0
        description = (NAMES[op], hex(a), hex(b), hex(c), rm)
        for cycle in range(256):
            await self.settle()
            if int(d.res_valid_o.value):
                break
            fire = int(d.req_ready_o.value) and int(d.req_valid_i.value)
            assert not accepted or not int(d.req_ready_o.value), 'multiple in-flight requests'
            await self.edge()
            if fire:
                accepted += 1
                d.req_valid_i.value = 0
                # A registered backend must no longer depend on live operands.
                self.drive(0, 0x7f800000, 0xff800000, 0x7f812345, 4)
        else:
            assert False, ('result watchdog', description)
        assert self.outputs() == expected, (description, self.outputs(), expected)
        for _ in range(hold):
            assert int(d.res_valid_o.value) and self.outputs() == expected
            fire = int(d.req_ready_o.value) and int(d.req_valid_i.value)
            await self.edge()
            if fire:
                accepted += 1
                d.req_valid_i.value = 0
                self.drive(0, 0x7f800000, 0xff800000, 0x7f812345, 4)
            await self.settle()
        d.res_ready_i.value = 1
        await self.settle()
        assert int(d.res_valid_o.value) and self.outputs() == expected
        accepted += int(d.req_ready_o.value) and int(d.req_valid_i.value)
        await self.edge()
        assert accepted == 1, ('request count', description, accepted)
        await self.idle(1)
        self.checks += 1

    async def disabled(self):
        for op in range(22):
            self.drive(op, 0x3f800000, 0x40000000, 0x3f000000)
            self.dut.req_valid_i.value = 1
            self.dut.res_ready_i.value = 1
            await self.settle()
            assert not int(self.dut.req_ready_o.value) and not int(self.dut.res_valid_o.value)
            assert self.outputs() == (0, 0)
            await self.edge()


class ArithmeticTest(FpuTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        if not self.params['ISA_ZFINX']:
            await self.disabled()
        else:
            for op in range(22):
                modes = range(5) if op < 9 or op >= 18 else (0,)
                # Cartesian special cases also cover signaling NaNs in each
                # meaningful operand, signed zeros, subnormals and infinities.
                for index, (a, b) in enumerate(itertools.product(VALUES, repeat=2)):
                    c = VALUES[(index // len(VALUES) + index) % len(VALUES)]
                    for rm in modes:
                        await self.operation(op, a, b, c, rm, hold=int(index % 31 == 0))
            # Rounding boundaries, fused cancellation and signed conversions.
            directed = ((0, 0x3f800000, 0x33800000, 0),
                        (5, 0x3f800001, 0x3f7ffffe, 0xbf800000),
                        (5, 0x7f800000, 0, 0x7fc00000),
                        (2, 0x00800000, 0x3f7fffff, 0),
                        (18, 0xcf000001, 0, 0), (19, 0xbe800000, 0, 0))
            for op, a, b, c in directed:
                for rm in range(5):
                    await self.operation(op, a, b, c, rm, hold=3)
            for _ in range(2048):
                op = self.rng.randrange(22)
                a, b, c = (self.rng.getrandbits(32) for _ in range(3))
                await self.operation(op, a, b, c, self.rng.randrange(5),
                                     hold=self.rng.randrange(4))
        self.logger.info('Exact arithmetic/flags comparisons: %d', self.checks)
        self.drop_objection()


class ControlTest(FpuTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        if not self.params['ISA_ZFINX']:
            await self.disabled()
        else:
            d = self.dut
            # Direct malformed FU controls cannot issue. DE normally converts
            # these to illegal-instruction exceptions before reaching EX.
            for op, rm in [(op, 0) for op in range(22, 32)] + [(0, rm) for rm in (5, 6, 7)]:
                self.drive(op, 0x3f800000, 0x40000000, 0, rm)
                d.req_valid_i.value = 1
                for _ in range(3):
                    await self.settle()
                    assert not int(d.req_ready_o.value) and not int(d.res_valid_o.value)
                    await self.edge()
            await self.idle()
            # Cancel each group during execution and while its output is held.
            # Recovery with another group detects stale arbiter or unit state.
            for op in (0, 3, 4, 12, 18, 20):
                for delay in (0, 1, 4, 80):
                    self.drive(op, 0x3f800001, 0x40400000, 0x3f000000)
                    d.req_valid_i.value = 1
                    d.res_ready_i.value = 0
                    for _ in range(256):
                        await self.settle()
                        if int(d.req_ready_o.value):
                            await self.edge()
                            break
                        # Zero-stage units only accept when their result drains.
                        if int(d.res_valid_o.value):
                            break
                        await self.edge()
                    else:
                        assert False, 'request watchdog'
                    d.req_valid_i.value = 0
                    for _ in range(delay):
                        await self.settle()
                        await self.edge()
                    d.flush_i.value = 1
                    d.req_valid_i.value = 1
                    d.res_ready_i.value = 1
                    await self.settle()
                    assert not int(d.res_valid_o.value) and not int(d.req_ready_o.value)
                    assert self.outputs() == (0, 0)
                    await self.edge()
                    d.flush_i.value = 0
                    await self.idle(100)
                    await self.operation(5, 0x3fc00000, 0x40000000, 0x3f800000, hold=4)
            # A second request must stay unaccepted until the first result
            # drains, including when it targets a different backend group.
            self.drive(3,0x3f800000,0x40400000)
            d.req_valid_i.value=1
            d.res_ready_i.value=0
            for _ in range(256):
                await self.settle()
                if int(d.req_ready_o.value):
                    await self.edge()
                    break
                await self.edge()
            else:
                assert False, 'divider admission watchdog'
            self.drive(0,0x3f800000,0x40000000)
            for _ in range(256):
                await self.settle()
                assert not int(d.req_ready_o.value), 'accepted overlapping request'
                if int(d.res_valid_o.value):
                    break
                await self.edge()
            else:
                assert False, 'divider completion watchdog'
            expected=result(3,0x3f800000,0x40400000)
            for _ in range(4):
                assert self.outputs()==expected and int(d.res_valid_o.value)
                assert not int(d.req_ready_o.value)
                await self.edge()
                await self.settle()
            d.res_ready_i.value=1
            await self.settle()
            assert not int(d.req_ready_o.value) and self.outputs()==expected
            await self.edge()
            # Keep the unaccepted next payload stable through its own handshake.
            await self.operation(0,0x3f800000,0x40000000,hold=2)
            # Reset an active divider and immediately recover after release.
            self.drive(3, 0x3f800001, 0x40400000)
            d.req_valid_i.value = 1
            await self.settle()
            await self.edge()
            await self.initialize()
            await self.idle(100)
            await self.operation(0, 0x3f800000, 0x40000000)
        self.logger.info('Lifecycle checks passed')
        self.drop_objection()


@cocotb.test(timeout_time=5, timeout_unit='ms')
async def arithmetic(_dut):
    await uvm_root().run_test(ArithmeticTest)


@cocotb.test(timeout_time=1, timeout_unit='ms')
async def control(_dut):
    await uvm_root().run_test(ControlTest)
