"""MEM grants transfer to WB; response completion is a separate channel."""

import os
import json
import random
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from lsu_model import ByteMemory, local_exception
from mem_model import FIELDS, token, request


class MemTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.memory = ByteMemory()
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])

    async def settle(self):
        await Timer(1, units='ns')

    async def edge(self):
        self.dut.clk_i.value = 1
        await Timer(1, units='ns')
        self.dut.clk_i.value = 0
        await self.settle()

    def drive(self, item):
        for field in FIELDS:
            getattr(self.dut, field+'_i').value = item[field]

    async def initialize(self):
        d = self.dut
        d.clk_i.value = 0
        d.mul_row_b_i.value = 0

        d.mul_phase2_i.value = 0
        d.mul_high_i.value = 0
        d.mul_accumulate_i.value = 0
        d.mul_addend_i.value = 0
        d.mul_addend_ready_i.value = 1
        self.drive(token())
        for name, value in dict(rst_n=0, flush=0, valid=0, ready=1, request_permit=1,
            pmp_allow=1, lsu_res_ready=0, lsu_res_flush=0, dmem_gnt=0,
            dmem_rvalid=0, dmem_rdata=0, dmem_err=0).items():
            getattr(d, 'rst_ni' if name == 'rst_n' else name+'_i').value = value
        await self.edge()
        d.rst_ni.value = 1
        await self.settle()

    async def execute(self, item, allow=True, error=False, grant_delay=0, response_delay=0, hold=0):
        d = self.dut
        self.drive(item)
        d.valid_i.value = 1
        d.pmp_allow_i.value = int(allow)
        d.dmem_gnt_i.value = 0
        d.dmem_rvalid_i.value = 0
        d.lsu_res_ready_i.value = 0
        await self.settle()
        # The candidate word is not masked by grant/completion/local faults.
        assert int(d.result_o.value) == item['result']
        fault = (item['exception_cause'], item['exception_tval']) if item['exception_valid'] else \
            local_exception(request(item, allow)) if item['lsu'] else None
        if fault or not item['lsu']:
            assert int(d.valid_o.value) and not int(d.dmem_req_o.value)
            assert int(d.exception_valid_o.value) == bool(fault)
            if fault:
                assert (int(d.exception_cause_o.value), int(d.exception_tval_o.value)) == fault
            else:
                assert int(d.result_o.value) == item['result']
            await self.edge()
            d.valid_i.value = 0
            return
        req = request(item, allow)
        for _ in range(grant_delay):
            assert int(d.dmem_req_o.value) and not int(d.valid_o.value)
            await self.edge()
        d.dmem_gnt_i.value = 1
        await self.settle()
        packet = tuple(int(getattr(d, 'dmem_'+n+'_o').value) for n in ('we', 'addr', 'wdata', 'be'))
        raw = self.memory.grant(req, packet)
        assert int(d.valid_o.value) and int(d.ready_o.value)
        assert not int(d.load_result_valid_o.value)  # Never forward the effective address.
        await self.edge()
        d.valid_i.value = 0
        d.dmem_gnt_i.value = 0
        # A younger flush cannot revoke the accepted WB-owned request.
        d.flush_i.value = 1
        for _ in range(response_delay):
            assert not int(d.lsu_res_valid_o.value)
            await self.edge()
        d.dmem_rvalid_i.value = 1
        d.dmem_rdata_i.value = raw
        d.dmem_err_i.value = int(error)
        d.lsu_res_ready_i.value = int(not hold)
        await self.settle()
        expected = self.memory.result(req, error)
        result = lambda: tuple(int(getattr(d, 'lsu_res_'+n+'_o').value)
                               for n in ('data', 'exception_valid', 'exception_cause', 'exception_tval'))
        assert int(d.lsu_res_valid_o.value) and result() == expected
        assert not int(d.lsu_res_registered_o.value)
        await self.edge()
        d.dmem_rvalid_i.value = 0
        d.dmem_rdata_i.value = raw ^ 0xFFFFFFFF
        d.dmem_err_i.value = int(not error)
        d.flush_i.value = 0
        for _ in range(hold):
            await self.settle()
            assert int(d.lsu_res_registered_o.value) and result() == expected
            await self.edge()
        if hold:
            d.lsu_res_ready_i.value = 1
            await self.edge()
        assert not int(d.lsu_busy_o.value)


class DirectedTest(MemTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        await self.execute(token(result=42, fflags_valid=1, fflags=3))
        for we in (0, 1):
            for op in range(8):
                for offset in range(4):
                    await self.execute(token(lsu=1, we=we, op=op, result=0x1000+offset,
                        store_data=0x87654321), grant_delay=2, response_delay=3, hold=2)
            await self.execute(token(lsu=1, we=we, result=0x1000), error=True)
            await self.execute(token(lsu=1, we=we, result=0x1000), allow=False)
        await self.execute(token(lsu=1, exception_valid=1, exception_cause=2, exception_tval=0xBAD))
        self.drop_objection()


class RandomizedTest(MemTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        for _ in range(512):
            await self.execute(token(lsu=1, we=self.rng.randrange(2), op=self.rng.randrange(8),
                result=0x1000+self.rng.randrange(32), store_data=self.rng.getrandbits(32)),
                allow=self.rng.randrange(8) != 0, error=self.rng.randrange(5) == 0,
                grant_delay=self.rng.randrange(4), response_delay=self.rng.randrange(4), hold=self.rng.randrange(4))
        self.drop_objection()


class ControlTest(MemTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        d = self.dut
        self.drive(token(lsu=1, result=0x1000))
        d.valid_i.value = 1
        d.dmem_gnt_i.value = 1
        d.ready_i.value = 0
        await self.settle()
        assert not int(d.dmem_req_o.value)  # Reserve WB capacity before presentation.
        d.ready_i.value = 1
        d.request_permit_i.value = 0
        await self.settle()
        assert not int(d.dmem_req_o.value)
        d.request_permit_i.value = 1
        d.dmem_gnt_i.value = 0
        await self.edge()  # Request is now held waiting for grant.
        d.ready_i.value = 0
        d.dmem_gnt_i.value = 1
        await self.edge()  # Grant cannot be withdrawn merely because ready fell.
        d.dmem_gnt_i.value = 0
        await self.settle()
        assert int(d.valid_o.value) and not int(d.dmem_req_o.value)
        d.dmem_rvalid_i.value = 1
        d.dmem_rdata_i.value = 0xCAFE
        await self.edge()  # Buffer response while MEM cannot transfer ownership.
        d.dmem_rvalid_i.value = 0
        assert int(d.lsu_res_registered_o.value)
        d.ready_i.value = 1
        await self.edge()
        d.valid_i.value = 0
        d.flush_i.value = 1
        d.lsu_res_ready_i.value = 1
        await self.settle()
        assert int(d.lsu_res_valid_o.value)
        await self.edge()
        assert not int(d.lsu_busy_o.value)
        # Flush an accepted-but-not-transferred operation: cancel and drain.
        await self.initialize()
        self.drive(token(lsu=1, result=0x1000))
        d.valid_i.value = 1
        await self.edge()  # present, no grant
        d.ready_i.value = 0
        d.dmem_gnt_i.value = 1
        await self.edge()
        d.dmem_gnt_i.value = 0
        d.flush_i.value = 1
        await self.edge()
        d.valid_i.value = 0
        d.flush_i.value = 0
        await self.edge()
        d.dmem_rvalid_i.value = 1
        await self.settle()
        assert not int(d.lsu_res_valid_o.value)
        await self.edge()
        assert not int(d.lsu_busy_o.value)
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


class SplitTest(MemTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        if not self.params['ISA_M'] or self.params['MUA_MUL'] not in (13,):
            self.drop_objection()
            return
        d = self.dut
        rows = [(0xffffffff,1), (0xffffffffffffffff,1), (0x7fffffffffffffff,1),
                (0x8000000000000000,0x8000000000000000)]
        rows += [(self.rng.getrandbits(64),self.rng.getrandbits(64)) for _ in range(128)]
        for a,b in rows:
            self.drive(token(result=a & 0xffffffff, store_data=a >> 32))
            d.mul_row_b_i.value = b

            d.mul_phase2_i.value = 1
            d.valid_i.value = 1
            for high in (0,1):
                d.mul_high_i.value = high
                expected = (((a+b) & ((1 << 64)-1)) >> (32*high)) & 0xffffffff
                for _ in range(self.rng.randrange(1,5)):
                    d.ready_i.value = 0
                    await self.settle()
                    assert int(d.valid_o.value) and not int(d.ready_o.value)
                    assert int(d.result_o.value) == expected
                    assert not int(d.dmem_req_o.value) and not int(d.pmp_valid_o.value)
                    assert not int(d.fflags_valid_o.value) and not int(d.exception_valid_o.value)
                    await self.edge()
                d.ready_i.value = 1
                await self.settle()
                assert int(d.ready_o.value) and int(d.result_o.value) == expected
                await self.edge()
        # Flush suppresses the token, including accidental LSU qualification.
        d.lsu_i.value = 1
        d.dmem_gnt_i.value = 1
        await self.settle()
        assert not int(d.dmem_req_o.value) and not int(d.pmp_valid_o.value)
        d.flush_i.value = 1
        await self.settle()
        assert not int(d.valid_o.value) and not int(d.dmem_req_o.value)
        await self.edge()
        self.drop_objection()


@cocotb.test()
async def split(_dut):
    await uvm_root().run_test(SplitTest)


class LateMacTest(MemTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        if self.params['ISA_M'] and self.params['MUA_MUL'] == 13:
            d = self.dut
            self.drive(token())
            d.valid_i.value = 1
            d.mul_phase2_i.value = 1
            for _ in range(256):
                a, b = self.rng.getrandbits(64), self.rng.getrandbits(64)
                c = self.rng.getrandbits(32)
                d.result_i.value = a & 0xffffffff
                d.store_data_i.value = a >> 32
                d.mul_row_b_i.value = b
                d.mul_addend_i.value = c
                d.mul_accumulate_i.value = 1
                d.mul_addend_ready_i.value = 0
                await self.settle()
                assert not int(d.valid_o.value) and not int(d.dmem_req_o.value)
                d.mul_addend_ready_i.value = 1
                await self.settle()
                assert int(d.valid_o.value) and int(d.result_o.value) == (a+b+c) & 0xffffffff
                # Native MULH ignores C, even when C is unavailable.
                d.mul_accumulate_i.value = 0
                d.mul_addend_ready_i.value = 0
                d.mul_high_i.value = 1
                await self.settle()
                assert int(d.valid_o.value) and int(d.result_o.value) == ((a+b) >> 32) & 0xffffffff
                d.mul_high_i.value = 0
            # A known exception must drain without waiting for its unused C.
            d.mul_accumulate_i.value = 1
            d.exception_valid_i.value = 1
            d.exception_cause_i.value = 2
            await self.settle()
            assert int(d.valid_o.value) and int(d.exception_valid_o.value)
            d.flush_i.value = 1
            await self.settle()
            assert not int(d.valid_o.value)
        self.drop_objection()


@cocotb.test()
async def late_mac(_dut):
    await uvm_root().run_test(LateMacTest)
