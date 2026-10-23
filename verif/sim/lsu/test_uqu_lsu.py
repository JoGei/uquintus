"""Request/grant fast path and independent WB response ownership."""

import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from lsu_model import ByteMemory, access, local_exception


class LsuTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.memory = ByteMemory()
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))

    async def settle(self):
        await Timer(1, units='ns')

    async def edge(self):
        self.dut.clk_i.value = 1
        await Timer(1, units='ns')
        self.dut.clk_i.value = 0
        await self.settle()

    def drive(self, req):
        for name, value in req.items():
            getattr(self.dut, 'req_' + name + '_i').value = value

    def packet(self):
        return tuple(int(getattr(self.dut, 'dmem_' + name + '_o').value)
                     for name in ('we', 'addr', 'wdata', 'be'))

    def result(self):
        return tuple(int(getattr(self.dut, 'res_' + name + '_o').value)
                     for name in ('data', 'exception_valid', 'exception_cause', 'exception_tval'))

    async def initialize(self):
        d = self.dut
        d.clk_i.value = 0
        for name, value in dict(rst_n=0, flush=0, res_flush=0, req_valid=0,
                                request_permit=1, res_ready=0, dmem_gnt=0,
                                dmem_rvalid=0, dmem_rdata=0, dmem_err=0).items():
            getattr(d, 'rst_ni' if name == 'rst_n' else name + '_i').value = value
        self.drive(access())
        await self.edge()
        d.rst_ni.value = 1
        await self.settle()
        assert not int(d.busy_o.value)

    async def transaction(self, req, delay=0, response_delay=0, hold=0, error=False):
        d = self.dut
        self.drive(req)
        d.req_valid_i.value = 1
        d.res_ready_i.value = 0
        d.dmem_rvalid_i.value = 0
        d.dmem_gnt_i.value = 0
        await self.settle()
        fault = local_exception(req)
        if fault:
            assert int(d.req_exception_valid_o.value)
            assert (int(d.req_exception_cause_o.value), int(d.req_exception_tval_o.value)) == fault
            assert not int(d.dmem_req_o.value) and not int(d.busy_o.value)
            await self.edge()
            d.req_valid_i.value = 0
            return
        assert not int(d.req_exception_valid_o.value)
        for _ in range(delay):
            assert int(d.dmem_req_o.value) and not int(d.req_ready_o.value)
            self.memory.check_request(req, self.packet())
            await self.edge()
        d.dmem_gnt_i.value = 1
        await self.settle()
        assert int(d.dmem_req_o.value) and int(d.req_ready_o.value)
        raw = self.memory.grant(req, self.packet())
        await self.edge()
        d.req_valid_i.value = 0
        d.dmem_gnt_i.value = 0
        await self.settle()
        for _ in range(response_delay):
            assert int(d.busy_o.value) and not int(d.res_valid_o.value)
            await self.edge()
        d.dmem_rvalid_i.value = 1
        d.dmem_rdata_i.value = raw
        d.dmem_err_i.value = int(error)
        d.res_ready_i.value = int(not hold)
        await self.settle()
        assert int(d.res_valid_o.value) and not int(d.res_registered_o.value)
        expected = self.memory.result(req, error)
        assert self.result() == expected
        await self.edge()
        d.dmem_rvalid_i.value = 0
        d.dmem_rdata_i.value = raw ^ 0xFFFFFFFF
        d.dmem_err_i.value = int(not error)
        await self.settle()
        if hold:
            for _ in range(hold):
                assert int(d.res_valid_o.value) and int(d.res_registered_o.value)
                assert self.result() == expected
                if not error and not req['we']:
                    assert int(d.res_forward_data_o.value) == expected[0]
                await self.edge()
            d.res_ready_i.value = 1
            await self.edge()
        await self.settle()
        assert not int(d.busy_o.value) and not int(d.res_valid_o.value)


class DirectedTest(LsuTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        for denied in (0, 1):
            for we in (0, 1):
                for op in range(8):
                    for offset in range(4):
                        await self.transaction(access(we=we, op=op, addr=0x1000+offset,
                                                      wdata=0x89ABCDEF, access_fault=denied), hold=2)
        for we in (0, 1):
            await self.transaction(access(we=we), error=True)
            await self.transaction(access(we=we, access_fault=1))
        self.drop_objection()


class RandomizedTest(LsuTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        for _ in range(1024):
            await self.transaction(access(we=self.rng.randrange(2), op=self.rng.randrange(8),
                addr=0x1000+self.rng.randrange(64), wdata=self.rng.getrandbits(32),
                access_fault=int(self.rng.randrange(8) == 0)), delay=self.rng.randrange(4),
                response_delay=self.rng.randrange(5), hold=self.rng.randrange(4),
                error=self.rng.randrange(5) == 0)
        self.drop_objection()


class ControlTest(LsuTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        d = self.dut
        # One next-cycle response and one grant per cycle after initial fill.
        d.res_ready_i.value = 1
        d.dmem_gnt_i.value = 1
        expected = None
        for n in range(12):
            req = access(addr=0x1000+4*n, we=n % 2, wdata=n)
            self.drive(req)
            d.req_valid_i.value = 1
            d.dmem_rvalid_i.value = int(expected is not None)
            d.dmem_rdata_i.value = 0x12345678
            await self.settle()
            assert int(d.req_ready_o.value) and int(d.dmem_req_o.value)
            assert int(d.res_valid_o.value) == (expected is not None)
            if expected is not None:
                assert int(d.res_data_o.value) == (0 if expected['we'] else 0x12345678)
            expected = req
            await self.edge()
        # An error response must suppress the younger request even with permit.
        d.dmem_err_i.value = 1
        await self.settle()
        assert int(d.res_exception_valid_o.value) and not int(d.dmem_req_o.value)
        await self.edge()
        d.req_valid_i.value = 0
        d.dmem_rvalid_i.value = 0
        d.dmem_err_i.value = 0
        await self.settle()
        assert not int(d.busy_o.value)
        # Request-side flush cannot cancel an older WB-owned transaction.
        self.drive(access())
        d.req_valid_i.value = 1
        await self.edge()
        d.req_valid_i.value = 0
        d.flush_i.value = 1
        d.dmem_rvalid_i.value = 1
        await self.settle()
        assert int(d.res_valid_o.value)
        await self.edge()
        d.flush_i.value = 0
        d.dmem_rvalid_i.value = 0
        # A presented, stalled request keeps its payload even when flushed.
        self.drive(access(we=1, wdata=0xDEADBEEF))
        d.req_valid_i.value = 1
        d.dmem_gnt_i.value = 0
        await self.settle()
        saved = self.packet()
        await self.edge()
        d.flush_i.value = 1
        d.request_permit_i.value = 0
        d.req_valid_i.value = 0
        self.drive(access(addr=0xDEAD, op=7))
        await self.settle()
        assert int(d.dmem_req_o.value) and self.packet() == saved
        await self.edge()
        d.flush_i.value = 0
        d.dmem_gnt_i.value = 1
        await self.settle()
        assert not int(d.req_ready_o.value)  # Killed grant has no architectural owner.
        await self.edge()
        d.dmem_rvalid_i.value = 1
        await self.settle()
        assert not int(d.res_valid_o.value)
        await self.edge()
        d.dmem_rvalid_i.value = 0
        assert not int(d.busy_o.value)
        # Explicit WB cancellation drains an already accepted transaction.
        d.request_permit_i.value = 1
        d.req_valid_i.value = 1
        self.drive(access())
        await self.edge()
        d.req_valid_i.value = 0
        d.res_flush_i.value = 1
        await self.edge()
        d.res_flush_i.value = 0
        d.dmem_rvalid_i.value = 1
        await self.settle()
        assert not int(d.res_valid_o.value)
        await self.edge()
        d.dmem_rvalid_i.value = 0
        assert not int(d.busy_o.value)
        # Reset and unsolicited responses cannot manufacture completion.
        d.dmem_rvalid_i.value = 1
        await self.edge()
        assert not int(d.res_valid_o.value)
        await self.initialize()
        self.drop_objection()


@cocotb.test()
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test()
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)


@cocotb.test()
async def control(_dut):
    await uvm_root().run_test(ControlTest)
