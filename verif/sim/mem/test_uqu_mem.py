"""MEM routing, one-shot LSU requests, delayed OBI, faults and canceled drains."""

import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from mem_model import FIELDS, OUTPUTS, ByteMemory, local_exception, outcome, request, token


class MemTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.memory = ByteMemory()
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.issues = self.transfers = self.checks = 0
        self.held_bus = None

    def drive(self, item):
        for field in FIELDS:
            getattr(self.dut, field + '_i').value = item[field]

    def outputs(self):
        return tuple(int(getattr(self.dut, field + '_o').value) for field in OUTPUTS)

    def packet(self):
        return tuple(int(getattr(self.dut, 'dmem_' + field + '_o').value)
                     for field in ('we', 'addr', 'wdata', 'be'))

    async def settle(self):
        await Timer(1, units='ns')

    async def step(self, **inputs):
        d = self.dut
        for name, value in inputs.items():
            getattr(d, name).value = value
        await self.settle()
        enabled = int(d.rst_ni.value)
        if enabled and self.held_bus is not None:
            assert int(d.dmem_req_o.value) and self.packet() == self.held_bus
        self.held_bus = self.packet() if enabled and int(d.dmem_req_o.value) and not int(d.dmem_gnt_i.value) else None
        snapshot = (int(d.valid_o.value), self.outputs(), int(d.ready_o.value))
        self.issues += int(d.u_lsu.req_valid_i.value) * int(d.u_lsu.req_ready_o.value)
        self.transfers += int(d.valid_o.value) * int(d.ready_i.value)
        d.clk_i.value = 1
        await Timer(1, units='ns')
        d.clk_i.value = 0
        await self.settle()
        return snapshot

    async def initialize(self):
        d = self.dut
        d.clk_i.value = 0
        self.drive(token())
        await self.step(rst_ni=0, flush_i=0, valid_i=0, ready_i=0,
                        request_permit_i=0, pmp_allow_i=1, dmem_gnt_i=0,
                        dmem_rvalid_i=0, dmem_rdata_i=0, dmem_err_i=1)
        d.rst_ni.value = 1
        await self.settle()
        assert int(d.ready_o.value) and not int(d.lsu_busy_o.value)

    async def run(self, item, allow=True, error=False, permission=0, grant=0, response=0, hold=0):
        d = self.dut
        issue_start, transfer_start, grants = self.issues, self.transfers, self.memory.grants
        self.drive(item)
        d.valid_i.value = 1
        d.ready_i.value = 0
        d.request_permit_i.value = int(permission == 0)
        d.pmp_allow_i.value = int(allow)
        d.dmem_gnt_i.value = 0
        d.dmem_rvalid_i.value = 0
        await self.settle()
        memory_op = bool(item['lsu'] and not item['exception_valid'])
        assert int(d.pmp_valid_o.value) == memory_op
        if memory_op:
            pmp = tuple(int(getattr(d, 'pmp_' + name + '_o').value)
                        for name in ('addr', 'size', 'access', 'priv_m'))
            assert pmp == (item['result'], item['op'] % 4, 2 if item['we'] else 1, item['priv_m'])
            assert not int(d.valid_o.value)
            await self.step()
            # Denial was captured at acceptance; later checker changes cannot
            # reinterpret an in-flight operation, including a retained fault.
            d.pmp_allow_i.value = int(not allow)
            await self.settle()
            assert not int(d.pmp_valid_o.value)
            req = request(item, allow)
            if not local_exception(req):
                for _ in range(permission):
                    assert not int(d.dmem_req_o.value) and not int(d.valid_o.value)
                    await self.step()
                if permission:
                    await self.step(request_permit_i=1)
                for _ in range(grant):
                    assert int(d.dmem_req_o.value) and not int(d.valid_o.value)
                    self.memory.check_request(req, self.packet())
                    await self.step()
                d.dmem_gnt_i.value = 1
                await self.settle()
                word = self.memory.grant(req, self.packet())
                await self.step()
                for _ in range(response):
                    assert not int(d.valid_o.value) and int(d.lsu_busy_o.value)
                    await self.step(dmem_gnt_i=0)
                before, _, _ = await self.step(dmem_gnt_i=0, dmem_rvalid_i=1,
                                               dmem_rdata_i=word, dmem_err_i=int(error))
                assert not before, 'external completion bypassed result register'
                d.dmem_rvalid_i.value = 0
                d.dmem_rdata_i.value = word ^ 0xFFFFFFFF
                d.dmem_err_i.value = int(not error)
        expected = outcome(item, self.memory, allow, error)
        await self.settle()
        for _ in range(hold):
            assert int(d.valid_o.value) and not int(d.ready_o.value)
            assert self.outputs() == expected, (self.outputs(), expected, item)
            await self.step()
        assert int(d.valid_o.value) and self.outputs() == expected, (self.outputs(), expected, item)
        snapshot = await self.step(ready_i=1)
        assert snapshot[0] and snapshot[2] and snapshot[1] == expected
        d.valid_i.value = 0
        await self.settle()
        assert not int(d.valid_o.value) and int(d.ready_o.value)
        assert not int(d.lsu_busy_o.value) and self.outputs() == (0,) * len(OUTPUTS)
        assert self.issues - issue_start == int(memory_op)
        assert self.transfers - transfer_start == 1
        assert self.memory.grants - grants == int(memory_op and not local_exception(request(item, allow)))
        self.checks += 1


class DirectedTest(MemTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        for flags in (0, 1):
            await self.run(token(result=0xDEADBEEF, fflags_valid=flags, fflags=21), hold=5)
        for we in (0, 1):
            for op in range(8):
                for offset in range(4):
                    for allow in (False, True):
                        item = token(lsu=1, we=we, op=op, result=0x1000+offset,
                                     store_data=0xA15E80FF, fflags_valid=1, fflags=31)
                        await self.run(item, allow=allow, permission=2, grant=2, response=2, hold=3)
            for error in (0, 1):
                await self.run(token(lsu=1, we=we, result=0x1000), error=error, hold=4)
            # An incoming exception takes priority over any illegal memory
            # control or access denial, without issuing LSU or PMP work.
            await self.run(token(lsu=1, we=we, op=7, result=0x1003,
                                 exception_valid=1, exception_cause=3, exception_tval=0xBAD),
                           allow=False, hold=4)
        for offset in range(4):
            await self.run(token(lsu=1, we=1, op=0, result=0x2000+offset,
                                 store_data=0x80+offset))
            await self.run(token(lsu=1, op=0, result=0x2000+offset))
            await self.run(token(lsu=1, op=4, result=0x2000+offset))
        await self.run(token(lsu=1, op=2, result=0xFFFFFFFC), grant=17, response=19, hold=6)
        self.logger.info('Directed MEM completions: %d', self.checks)
        self.drop_objection()


class RandomizedTest(MemTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        for _ in range(512):
            item = token(lsu=int(self.rng.randrange(4) != 0), we=self.rng.randrange(2),
                         op=self.rng.choice((0, 1, 2, 4, 5, 7)), result=0x3000+self.rng.randrange(256),
                         store_data=self.rng.getrandbits(32), priv_m=self.rng.randrange(2),
                         instr=self.rng.getrandbits(32), fflags_valid=self.rng.randrange(2),
                         fflags=self.rng.randrange(32), exception_valid=int(self.rng.randrange(16) == 0),
                         exception_cause=2, exception_tval=self.rng.getrandbits(32))
            await self.run(item, allow=self.rng.randrange(8) != 0, error=self.rng.randrange(8) == 0,
                           permission=self.rng.randrange(5), grant=self.rng.randrange(7),
                           response=self.rng.randrange(8), hold=self.rng.randrange(6))
        self.logger.info('Randomized MEM completions: %d', self.checks)
        self.drop_objection()


class ControlTest(MemTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        d = self.dut
        # Empty stage is fillable even with downstream blocked.
        await self.step(ready_i=0)
        assert int(d.ready_o.value)
        self.drive(token(lsu=1, we=1, result=0x4000))
        await self.step(valid_i=1, flush_i=1, dmem_gnt_i=1, request_permit_i=1)
        assert not int(d.dmem_req_o.value) and not int(d.valid_o.value)
        await self.step(valid_i=0, flush_i=0, dmem_gnt_i=0)
        for we in (0, 1):
            for error in (0, 1):
                for phase in ('permission', 'request', 'grant', 'wait_response', 'response', 'result'):
                    original = token(lsu=1, we=we, result=0x4000, store_data=0xF00DBABE)
                    self.drive(original)
                    await self.step(valid_i=1, ready_i=0, request_permit_i=int(phase != 'permission'),
                                    pmp_allow_i=1, dmem_gnt_i=0, dmem_rvalid_i=0)
                    word = self.memory.word(0x4000)
                    if phase in ('wait_response', 'response', 'result'):
                        word = self.memory.grant(request(original), self.packet())
                        await self.step(dmem_gnt_i=1)
                        await self.step(dmem_gnt_i=0)
                        if phase == 'result':
                            await self.step(dmem_rvalid_i=1, dmem_rdata_i=word, dmem_err_i=error)
                            assert int(d.valid_o.value)
                    if phase == 'grant':
                        word = self.memory.grant(request(original), self.packet())
                    snapshot = await self.step(flush_i=1, dmem_gnt_i=int(phase == 'grant'),
                                               dmem_rvalid_i=int(phase == 'response'),
                                               dmem_rdata_i=word, dmem_err_i=error)
                    assert not snapshot[0] and not snapshot[2]
                    # Replace the invalidated slot with a new-path pass token.
                    # The killed LSU work must never complete as this token.
                    fresh = token(result=0x12345678, fflags_valid=1, fflags=11)
                    self.drive(fresh)
                    d.flush_i.value = 0
                    d.dmem_gnt_i.value = 0
                    d.dmem_rvalid_i.value = 0
                    d.ready_i.value = 1
                    await self.settle()
                    if phase in ('request', 'grant', 'wait_response'):
                        assert int(d.lsu_busy_o.value) and not int(d.valid_o.value)
                        # Repeated flush still must not withdraw the old bus request.
                        if phase == 'request':
                            for _ in range(3):
                                await self.step(flush_i=1)
                                assert int(d.dmem_req_o.value)
                            d.flush_i.value = 0
                            await self.settle()
                            word = self.memory.grant(request(original), self.packet())
                            await self.step(dmem_gnt_i=1)
                        for _ in range(3):
                            await self.step(dmem_gnt_i=0)
                            assert not int(d.valid_o.value)
                        await self.step(dmem_rvalid_i=1, dmem_rdata_i=word, dmem_err_i=error)
                        d.dmem_rvalid_i.value = 0
                    await self.settle()
                    assert not int(d.lsu_busy_o.value)
                    assert int(d.valid_o.value) and self.outputs() == outcome(fresh, self.memory)
                    await self.step()
                    d.valid_i.value = 0
                    await self.run(token(lsu=1, result=0x4000), hold=1)
        # Reset may abandon tracking only under coordinated memory reset.
        for phase in ('permission', 'request', 'response', 'result'):
            item = token(lsu=1, result=0x5000)
            self.drive(item)
            await self.step(valid_i=1, ready_i=0, pmp_allow_i=1,
                            request_permit_i=int(phase != 'permission'), dmem_gnt_i=0, dmem_rvalid_i=0)
            if phase in ('wait_response', 'response', 'result'):
                await self.step(dmem_gnt_i=1)
            if phase == 'result':
                await self.step(dmem_gnt_i=0, dmem_rvalid_i=1, dmem_rdata_i=0xBAD)
            await self.step(rst_ni=0, valid_i=0, dmem_gnt_i=0, dmem_rvalid_i=0)
            assert not int(d.lsu_busy_o.value) and not int(d.valid_o.value)
            await self.step(rst_ni=1)
            await self.run(token(result=0xCAFEBABE))
        await self.run(token(lsu=1, result=0x6000), permission=129, grant=257, response=263, hold=17)
        self.logger.info('MEM flush/drain/reset/recovery checks passed')
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def control(_dut):
    await uvm_root().run_test(ControlTest)
