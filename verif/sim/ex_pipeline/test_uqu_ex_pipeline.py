"""Verify the real EX stage inside two registers belonging to its parent."""

from collections import deque
import json
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from ex_model import FU_MULDIV, FU_PASS, assert_outcome, cycles, outcome, random_token, token

FIELDS = ('fu', 'op', 'a', 'b', 'c', 'rm', 'pass_data', 'store_data', 'instr',
          'exception_valid', 'exception_cause', 'exception_tval', 'pc', 'rd')
OUTPUTS = ('result', 'store_data', 'fflags_valid', 'fflags', 'exception_valid',
           'exception_cause', 'exception_tval', 'pc', 'instr', 'rd')


class PipelineTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))

    async def settle(self):
        await Timer(1, units='ns')

    async def edge(self):
        self.dut.clk_i.value = 1
        await Timer(1, units='ns')
        self.dut.clk_i.value = 0

    def drive(self, payload):
        for field in FIELDS:
            getattr(self.dut, 'in_' + field + '_i').value = payload[field]

    def outputs(self):
        return tuple(int(getattr(self.dut, 'out_' + field + '_o').value) for field in OUTPUTS)

    def expected(self, payload):
        return outcome(payload, self.params) + (payload['pc'], payload['instr'], payload['rd'])

    async def initialize(self):
        d = self.dut
        d.clk_i.value = 0
        d.rst_ni.value = 0
        d.flush_i.value = 0
        d.in_valid_i.value = 0
        d.out_ready_i.value = 0
        d.operands_ready_i.value = 1
        self.drive(token())
        await self.settle()
        assert not int(d.out_valid_o.value) and not int(d.in_ready_o.value)
        await self.edge()
        d.rst_ni.value = 1

    async def stream(self, payloads, random_stalls=False):
        d = self.dut
        expected = deque()
        sent = received = 0
        held_output = None
        held_ex_pc = None
        for cycle in range(100000):
            d.in_valid_i.value = int(sent < len(payloads))
            if sent < len(payloads):
                self.drive(payloads[sent])
            d.out_ready_i.value = self.rng.randrange(2) if random_stalls else 1
            d.operands_ready_i.value = self.rng.randrange(2) if random_stalls else 1
            await self.settle()
            if held_output is not None:
                assert int(d.out_valid_o.value) and self.outputs() == held_output
            if held_ex_pc is not None:
                assert int(d.ex_valid_o.value) and int(d.ex_pc_o.value) == held_ex_pc
            if int(d.out_valid_o.value):
                assert expected, 'unsolicited or duplicate pipeline result'
                assert_outcome(self.outputs(), expected[0])
                if int(d.out_ready_i.value):
                    expected.popleft()
                    received += 1
            if int(d.in_valid_i.value) and int(d.in_ready_o.value):
                expected.append(self.expected(payloads[sent]))
                sent += 1
            held_output = self.outputs() if int(d.out_valid_o.value) and not int(d.out_ready_i.value) else None
            held_ex_pc = (int(d.ex_pc_o.value) if int(d.ex_valid_o.value) and
                          not int(d.u_ex.ready_o.value) else None)
            await self.edge()
            if received == len(payloads):
                assert sent == received and not expected
                return cycle + 1
        raise AssertionError('parent pipeline failed to drain')

    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        sequence = [token(op=0, a=i, b=1, pc=0x1000 + i * 4, rd=i % 32,
                          instr=0x10000000 | i, store_data=0x12340000 | i) for i in range(64)]
        elapsed = await self.stream(sequence)
        assert elapsed == len(sequence) + 2, 'unexpected added execution/pipeline cycle'
        payloads = [random_token(self.rng, i, self.params) for i in range(512)]
        await self.stream(payloads, random_stalls=True)
        # End with a bubble rather than a hidden duplicate of the last token.
        self.dut.in_valid_i.value = 0
        for _ in range(4):
            await self.settle()
            assert not int(self.dut.out_valid_o.value) and not int(self.dut.ex_valid_o.value)
            await self.edge()
        self.logger.info('Parent pipeline: 576 ordered transfers, metadata and stalls verified')
        self.drop_objection()


class DrainFlushTest(PipelineTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        d = self.dut
        older = token(op=0, a=1, b=2, pc=0x1000, instr=0x13)
        younger = token(fu=FU_MULDIV, op=4, a=0x81234567, b=7, pc=0x1004,
                        instr=0x023140B3, store_data=0xFEDCBA98)
        if not self.params['ISA_M']:
            younger = token(fu=FU_PASS, pass_data=99, pc=0x1004)
        # Fill EX/MEM with the older instruction, hold the younger in DE/EX.
        d.out_ready_i.value = 0
        self.drive(older)
        d.in_valid_i.value = 1
        await self.settle()
        assert int(d.in_ready_o.value)
        await self.edge()
        self.drive(younger)
        await self.settle()
        assert int(d.in_ready_o.value)
        await self.edge()
        d.in_valid_i.value = 0
        await self.settle()
        assert int(d.out_valid_o.value) and self.outputs() == self.expected(older)
        assert int(d.ex_valid_o.value) and int(d.ex_pc_o.value) == younger['pc']
        if self.params['ISA_M']:
            # DIV has at least three cycles, even when fully unrolled. While
            # EX computes, the occupied older MEM slot must still drain.
            assert not int(d.ex_fire_o.value)
            await self.edge()  # First execution cycle, with MEM blocked.
            d.out_ready_i.value = 1
            await self.settle()
            assert int(d.out_valid_o.value) and not int(d.ex_fire_o.value)
            await self.edge()  # Older MEM drains, EX is still computing.
            await self.settle()
            assert not int(d.out_valid_o.value), 'busy EX froze the older MEM slot'
            # Flush the owning EX token; it must not produce a late result.
            d.flush_i.value = 1
            await self.settle()
            assert not int(d.ex_fire_o.value) and not int(d.in_ready_o.value)
            await self.edge()
            d.flush_i.value = 0
            for _ in range(cycles(younger, self.params) + 2):
                await self.settle()
                assert not int(d.out_valid_o.value) and not int(d.ex_valid_o.value)
                await self.edge()
        else:
            d.flush_i.value = 1
            await self.settle()
            await self.edge()
            d.flush_i.value = 0
            d.out_ready_i.value = 1
            await self.settle()
            assert int(d.out_valid_o.value) and self.outputs() == self.expected(older)
            await self.edge()
        # Flush EX again with an older result blocked in EX/MEM. That older
        # payload belongs to the parent and must survive the EX cancellation.
        recovery = token(op=8, a=50, b=8, pc=0x2000, rd=7, instr=0x40000033)
        d.out_ready_i.value = 0
        self.drive(recovery)
        d.in_valid_i.value = 1
        await self.settle()
        await self.edge()
        d.in_valid_i.value = 0
        await self.settle()
        await self.edge()
        await self.settle()
        assert int(d.out_valid_o.value) and self.outputs() == self.expected(recovery)
        d.flush_i.value = 1
        await self.settle()
        await self.edge()
        d.flush_i.value = 0
        await self.settle()
        assert int(d.out_valid_o.value) and self.outputs() == self.expected(recovery)
        d.out_ready_i.value = 1
        await self.edge()
        # Reset does invalidate both parent registers and all unit tracking.
        d.rst_ni.value = 0
        await self.settle()
        await self.edge()
        d.rst_ni.value = 1
        await self.stream([token(op=0, a=9, b=1, pc=0x3000)])
        self.logger.info('Older drain, EX-only flush, parent retention, and reset recovery verified')
        self.drop_objection()


@cocotb.test(timeout_time=2, timeout_unit='ms')
async def pipeline(_dut):
    await uvm_root().run_test(PipelineTest)


@cocotb.test(timeout_time=2, timeout_unit='ms')
async def drain_flush(_dut):
    await uvm_root().run_test(DrainFlushTest)
