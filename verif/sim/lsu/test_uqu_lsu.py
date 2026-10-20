"""Exercise MEM requests, an independently delayed OBI bus, and killed drains."""

import os
import random
from pathlib import Path
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from lsu_model import MASK, ByteMemory, access, local_exception


class LsuTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.memory = ByteMemory()
        self.checks = 0

    async def settle(self):
        await Timer(1, units='ns')

    async def edge(self):
        self.dut.clk_i.value = 1
        await Timer(1, units='ns')
        self.dut.clk_i.value = 0

    def packet(self):
        return tuple(int(s.value) for s in (self.dut.dmem_we_o, self.dut.dmem_addr_o,
                     self.dut.dmem_wdata_o, self.dut.dmem_be_o))

    def result(self):
        return tuple(int(s.value) for s in (self.dut.res_data_o,
                     self.dut.res_exception_valid_o, self.dut.res_exception_cause_o,
                     self.dut.res_exception_tval_o))

    def drive(self, req):
        for name, value in req.items():
            getattr(self.dut, 'req_' + name + '_i').value = value

    async def initialize(self):
        d = self.dut
        d.clk_i.value = 0
        d.rst_ni.value = 0
        d.flush_i.value = 0
        d.req_valid_i.value = 0
        d.request_permit_i.value = 0
        d.res_ready_i.value = 0
        d.dmem_gnt_i.value = 0
        d.dmem_rvalid_i.value = 0
        d.dmem_rdata_i.value = 0
        d.dmem_err_i.value = 1
        self.drive(access())
        await self.settle()
        assert not int(d.req_ready_o.value) and not int(d.busy_o.value)
        assert not int(d.dmem_req_o.value) and not int(d.res_valid_o.value)
        await self.edge()
        d.rst_ni.value = 1
        await self.settle()
        assert int(d.req_ready_o.value) and not int(d.busy_o.value)

    async def begin(self, req, permit=True, grant_high=False):
        d = self.dut
        self.drive(req)
        d.req_valid_i.value = 1
        d.request_permit_i.value = int(permit)
        d.dmem_gnt_i.value = int(grant_high)
        d.dmem_rvalid_i.value = 0
        d.dmem_err_i.value = 1  # Must be ignored without a response.
        d.res_ready_i.value = 0
        await self.settle()
        assert int(d.req_ready_o.value) and not int(d.dmem_req_o.value)
        assert not int(d.res_valid_o.value)
        await self.edge()
        d.req_valid_i.value = 0
        # The native request was accepted once; changing invalid inputs must
        # not replace its bus payload, access decision, or fault address.
        self.drive(access(we=1 - req['we'], op=7, addr=req['addr'] ^ MASK,
                          wdata=req['wdata'] ^ MASK, instr=req['instr'] ^ MASK,
                          access_fault=1 - req['access_fault']))

    async def grant(self, req, delay=0):
        d = self.dut
        snapshot = None
        for cycle in range(delay + 1):
            d.dmem_gnt_i.value = int(cycle == delay)
            await self.settle()
            assert int(d.dmem_req_o.value) and int(d.busy_o.value)
            assert not int(d.req_ready_o.value) and not int(d.res_valid_o.value)
            self.memory.check_request(req, self.packet())
            if snapshot is None:
                snapshot = self.packet()
            assert self.packet() == snapshot
            if cycle == delay:
                word = self.memory.grant(req, self.packet())
            await self.edge()
        d.dmem_gnt_i.value = 0
        return word

    async def respond(self, word, error=False, delay=0):
        d = self.dut
        for _ in range(delay):
            d.dmem_rvalid_i.value = 0
            d.dmem_rdata_i.value = self.rng.getrandbits(32)
            d.dmem_err_i.value = self.rng.randrange(2)
            await self.settle()
            assert not int(d.dmem_req_o.value) and not int(d.res_valid_o.value)
            assert int(d.busy_o.value) and not int(d.req_ready_o.value)
            await self.edge()
        d.dmem_rvalid_i.value = 1
        d.dmem_rdata_i.value = word
        d.dmem_err_i.value = int(error)
        await self.settle()
        assert not int(d.res_valid_o.value), 'combinational bus-response bypass'
        assert not int(d.dmem_req_o.value)
        await self.edge()
        d.dmem_rvalid_i.value = 0
        d.dmem_rdata_i.value = word ^ MASK
        d.dmem_err_i.value = int(not error)

    async def consume(self, expected, hold=0):
        d = self.dut
        for _ in range(hold):
            await self.settle()
            assert int(d.res_valid_o.value) and int(d.busy_o.value)
            assert not int(d.req_ready_o.value) and not int(d.dmem_req_o.value)
            assert self.result() == expected, (self.result(), expected)
            await self.edge()
        d.res_ready_i.value = 1
        await self.settle()
        assert int(d.res_valid_o.value) and self.result() == expected, (self.result(), expected)
        assert not int(d.req_ready_o.value) and not int(d.dmem_req_o.value)
        await self.edge()
        d.res_ready_i.value = 0
        await self.settle()
        assert int(d.req_ready_o.value) and not int(d.busy_o.value)
        assert not int(d.res_valid_o.value) and self.result() == (0, 0, 0, 0)
        self.checks += 1

    async def operation(self, req, grant_delay=0, response_delay=0, hold=0,
                        permit_wait=0, error=False, grant_high=False):
        d = self.dut
        grants = self.memory.grants
        expected = self.memory.result(req, error)
        await self.begin(req, permit=not permit_wait, grant_high=grant_high)
        if local_exception(req):
            await self.settle()
            assert not int(d.dmem_req_o.value)
        else:
            for _ in range(permit_wait):
                await self.settle()
                assert int(d.busy_o.value) and not int(d.dmem_req_o.value)
                assert not int(d.res_valid_o.value) and not int(d.req_ready_o.value)
                await self.edge()
            if permit_wait:
                d.request_permit_i.value = 1
                await self.settle()
                assert not int(d.dmem_req_o.value)
                await self.edge()
            # A permit can no longer withdraw an already presented request.
            d.request_permit_i.value = 0
            word = await self.grant(req, grant_delay)
            await self.respond(word, error, response_delay)
        await self.consume(expected, hold)
        assert self.memory.grants - grants == int(local_exception(req) is None)


class DirectedTest(LsuTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        # Every normalized op, address offset, load/store, and denial outcome.
        for we in (0, 1):
            for op in range(8):
                for offset in range(8):
                    for deny in (0, 1):
                        await self.operation(access(we=we, op=op, addr=0x1000 + offset,
                                                   access_fault=deny, wdata=0x89ABCDEF), hold=1)
        for pattern in (0, MASK, 0x80FF7F00, 0x8000FFFF, 0x7FFF8000, 0x01234567):
            for op in (0, 1, 2, 4, 5):
                for offset in range(4):
                    self.memory.seed(0x2000, pattern)
                    await self.operation(access(op=op, addr=0x2000 + offset),
                                         grant_delay=1, response_delay=2)
        for we in (0, 1):
            for op in (0, 1, 2):
                await self.operation(access(we=we, op=op, addr=0x3000,
                                           wdata=0xDEADBEEF), error=True, hold=3)
        for op in (0, 1, 2):
            for offset in range(4):
                for value in (0, 1, MASK, 0x89ABCDEF):
                    await self.operation(access(we=1, op=op, addr=0x4000 + offset,
                                               wdata=value), grant_high=True)
                    await self.operation(access(addr=0x4000))
        await self.operation(access(addr=0xFFFFFFFC), permit_wait=5)
        self.logger.info('Directed LSU completions: %d', self.checks)
        self.drop_objection()


class RandomizedTest(LsuTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        for _ in range(1024):
            we = self.rng.randrange(2)
            op = self.rng.choice((0, 1, 2) if we else (0, 1, 2, 4, 5))
            addr = 0x8000 + self.rng.randrange(256)
            req = access(we=we, op=op, addr=addr, wdata=self.rng.getrandbits(32),
                         access_fault=int(self.rng.randrange(16) == 0))
            await self.operation(req, grant_delay=self.rng.randrange(8),
                                 response_delay=self.rng.randrange(10),
                                 permit_wait=self.rng.randrange(5), hold=self.rng.randrange(7),
                                 error=self.rng.randrange(8) == 0,
                                 grant_high=bool(self.rng.randrange(2)))
        self.logger.info('Randomized LSU completions: %d', self.checks)
        self.drop_objection()


class ControlTest(LsuTest):
    async def flush_phase(self, req, phase, error=False):
        d = self.dut
        before = self.memory.grants
        await self.begin(req, permit=phase != 'permission')
        if phase == 'permission':
            d.flush_i.value = 1
            d.request_permit_i.value = 1
            await self.settle()
            assert not int(d.dmem_req_o.value)
            await self.edge()
            d.flush_i.value = 0
        else:
            # Flush before grant must preserve the full asserted request.
            if phase in ('request', 'grant'):
                d.flush_i.value = 1
                await self.settle()
                assert int(d.dmem_req_o.value)
                assert not int(d.res_valid_o.value) and not int(d.req_ready_o.value)
                word = await self.grant(req, delay=3 if phase == 'request' else 0)
                d.flush_i.value = 0
                # Repeat cancellation while the old response is outstanding.
                await self.settle()
                await self.edge()
                d.flush_i.value = 1
                await self.edge()
                d.flush_i.value = 0
            else:
                word = await self.grant(req, 1)
            if phase == 'response':
                d.flush_i.value = 1
            if phase == 'waiting':
                d.flush_i.value = 1
                await self.settle()
                await self.edge()
                d.flush_i.value = 0
            await self.respond(word, error, delay=0 if phase == 'response' else 3)
            if phase == 'result':
                await self.settle()
                assert int(d.res_valid_o.value)
                d.flush_i.value = 1
                d.res_ready_i.value = 1
                await self.settle()
                assert not int(d.res_valid_o.value)
                await self.edge()
            d.flush_i.value = 0
        d.res_ready_i.value = 1
        for _ in range(4):
            await self.settle()
            assert not int(d.res_valid_o.value) and not int(d.dmem_req_o.value)
            assert int(d.req_ready_o.value) and not int(d.busy_o.value)
            await self.edge()
        assert self.memory.grants - before == int(phase != 'permission')
        await self.operation(access(op=4, addr=req['addr']), hold=2)

    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        d = self.dut
        # Flush before native acceptance, including a preasserted bus grant.
        self.drive(access(we=1, wdata=0x12345678))
        d.req_valid_i.value = 1
        d.request_permit_i.value = 1
        d.dmem_gnt_i.value = 1
        d.flush_i.value = 1
        await self.settle()
        assert not int(d.req_ready_o.value) and not int(d.dmem_req_o.value)
        await self.edge()
        d.req_valid_i.value = 0
        d.flush_i.value = 0
        for we in (0, 1):
            for error in (False, True):
                for phase in ('permission', 'request', 'grant', 'waiting', 'response', 'result'):
                    await self.flush_phase(access(we=we, addr=0x9000, wdata=0xAABBCCDD), phase, error)
        # Reset may abandon tracking only with coordinated memory reset. No
        # response from the abandoned access is delivered after reset release.
        for phase in ('permission', 'request', 'waiting', 'result'):
            await self.begin(access(), permit=phase != 'permission')
            if phase in ('waiting', 'result'):
                word = await self.grant(access())
                if phase == 'result':
                    await self.respond(word)
            d.rst_ni.value = 0
            await self.settle()
            assert not int(d.dmem_req_o.value) and not int(d.res_valid_o.value)
            assert not int(d.busy_o.value) and not int(d.req_ready_o.value)
            await self.edge()
            d.dmem_rvalid_i.value = 0
            d.dmem_gnt_i.value = 0
            d.rst_ni.value = 1
            await self.operation(access(op=0, addr=0x1003))
        # A second native request waits through the outstanding transaction and
        # retained completion. It cannot allocate another OBI transaction early.
        first = access(addr=0xA000)
        second = access(we=1, op=0, addr=0xA003, wdata=0xFE)
        await self.begin(first)
        expected = self.memory.result(first)
        self.drive(second)
        d.req_valid_i.value = 1
        word = await self.grant(first, delay=3)
        await self.respond(word, delay=4)
        for _ in range(5):
            await self.settle()
            assert int(d.res_valid_o.value) and self.result() == expected
            assert not int(d.req_ready_o.value) and not int(d.dmem_req_o.value)
            await self.edge()
        d.res_ready_i.value = 1
        await self.settle()
        assert not int(d.req_ready_o.value)
        await self.edge()  # The pending second request is not accepted yet.
        d.res_ready_i.value = 0
        d.request_permit_i.value = 1
        await self.settle()
        assert int(d.req_ready_o.value) and not int(d.res_valid_o.value)
        await self.edge()  # Accept the unchanged pending second request.
        d.req_valid_i.value = 0
        word = await self.grant(second)
        await self.respond(word)
        await self.consume(self.memory.result(second))
        await self.operation(access(addr=0xA000))
        # Long bus waits cause neither timeout nor retry.
        await self.operation(access(), grant_delay=257, response_delay=263,
                             permit_wait=129, hold=17)
        self.logger.info('LSU cancellation/reset/recovery completions: %d', self.checks)
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
