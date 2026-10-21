"""Real parent registers and GPR/hazard integration around native DE."""
import json
import os

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test


class ParentTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.p = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.cycles = 0
        self.transfers = 0
        self.branches = []

    async def cycle(self, **changes):
        i = dict(rst_n=1, flush=0, permit=1, fetch_valid=0,
                 fetch_instr=0x13, fetch_original=0x13, fetch_pc=0x1000,
                 fetch_compressed=0, fetch_fault=0, fetch_cause=1, fetch_tval=0,
                 out_ready=0, ex_result_available=0, ex_result_forwardable=1, ex_result=0)
        for stage in ('mem', 'wb'):
            i.update({stage+'_valid':0, stage+'_pending':0, stage+'_rd0':0,
                      stage+'_rd1':0, stage+'_result_available':0,
                      stage+'_result_forwardable':0, stage+'_result':0, stage+'_advance':0})
        i.update(changes)
        if 'fetch_instr' in changes and 'fetch_original' not in changes:
            i['fetch_original'] = i['fetch_instr']
        self.dut.clk_i.value = 0
        for name,value in i.items():
            getattr(self.dut, 'rst_ni' if name == 'rst_n' else name+'_i').value = value
        await Timer(1, units='ns')
        result = {name:int(getattr(self.dut, name+'_o').value) for name in
                  ('fetch_ready','de_slot_valid','de_transfer','branch_resolve','branch_taken',
                   'next_pc','ex_valid','ex_fault','ex_cause','ex_tval','ex_instr',
                   'ex_pc','ex_rd','ex_a','ex_b','ex_store_data','ex_captured','ex_source_ready')}
        self.transfers += result['de_transfer']
        if result['branch_resolve']:
            self.branches.append((result['branch_taken'], result['next_pc']))
        self.dut.clk_i.value = 1
        await Timer(1, units='ns')
        self.cycles += 1
        return result

    async def initialize(self):
        await self.cycle(rst_n=0)
        # Integer state has no reset; explicitly establish all used nonzero GPRs.
        for reg,value in ((1,1),(2,9),(3,0)):
            await self.cycle(wb_valid=1, wb_pending=1, wb_rd0=reg,
                             wb_result=value, wb_result_available=1,
                             wb_result_forwardable=1, wb_advance=1)


class DependenciesTest(ParentTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        addi = 0x00700193             # x3 = 7
        sub = 0x40218233              # x4 = x3 - x2
        await self.cycle(fetch_valid=1, fetch_instr=addi)
        r = await self.cycle(fetch_valid=1, fetch_instr=sub, fetch_pc=0x1004)
        assert r['de_transfer']
        assert int(self.dut.ex_instr_o.value) == addi
        # Producer advances while consumer enters EX. With EX-to-DE disabled,
        # the unresolved source must be marked uncaptured and bypassed in EX.
        r = await self.cycle(out_ready=1, ex_result_available=1, ex_result=7)
        if (self.p['MUA_FORWARDING'] and not self.p['MUA_FORWARD_EX_TO_DE'] and
                self.p['MUA_FORWARD_MEM_TO_EX']):
            assert r['de_transfer'] and not int(self.dut.ex_captured_o.value) & 1
        if r['de_transfer']:
            assert int(self.dut.ex_instr_o.value) == sub
        await self.cycle(mem_valid=1, mem_pending=1, mem_rd0=3,
                         mem_result_available=1, mem_result_forwardable=1, mem_result=7)
        # EX can remain occupied while older WB writes and drains. Any operand
        # obtained from the disappearing producer must remain correct in EX.
        await self.cycle(wb_valid=1, wb_pending=1, wb_rd0=3,
                         wb_result_available=1, wb_result_forwardable=1,
                         wb_result=7, wb_advance=1)
        await self.cycle()
        await self.cycle()
        assert int(self.dut.ex_valid_o.value)
        assert int(self.dut.ex_instr_o.value) == sub
        assert int(self.dut.ex_a_o.value) == 7
        assert int(self.dut.ex_b_o.value) == 9
        assert int(self.dut.ex_source_ready_o.value) & 3 == 3
        for _ in range(5):
            r = await self.cycle()
            assert r['ex_a'] == 7 and r['ex_b'] == 9
        # Store-data selection must not replace the ALU offset operand.
        store = 0x0021A023            # sw x2, 0(x3)
        await self.cycle(fetch_valid=1, fetch_instr=store, fetch_pc=0x1008,
                         out_ready=1, ex_result_available=1, ex_result=0xFFFFFFFE)
        await self.cycle(out_ready=1)
        assert int(self.dut.ex_instr_o.value) == store
        assert int(self.dut.ex_a_o.value) == 7
        assert int(self.dut.ex_b_o.value) == 0
        assert int(self.dut.ex_store_data_o.value) == 9
        assert self.transfers == 3
        self.logger.info('Dependency parent fixture: %d cycles, %d transfers', self.cycles, self.transfers)
        self.drop_objection()


class BranchFaultsTest(ParentTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        branch = 0x00018463           # beq x3, x0, +8
        await self.cycle(fetch_valid=1, fetch_instr=branch, fetch_pc=0x2000)
        for _ in range(4):
            r = await self.cycle(mem_valid=1, mem_pending=1, mem_rd0=3,
                mem_result=0xDEAD, mem_result_available=0, mem_result_forwardable=1, out_ready=1)
            assert not r['de_transfer'] and not r['branch_resolve'] and not r['ex_valid']
        await self.cycle(mem_valid=1, mem_pending=1, mem_rd0=3, mem_result=0,
                         mem_result_available=1, mem_result_forwardable=1, mem_advance=1, out_ready=1)
        await self.cycle(wb_valid=1, wb_pending=1, wb_rd0=3, wb_result=0,
                         wb_result_available=1, wb_result_forwardable=1, wb_advance=1, out_ready=1)
        for _ in range(5):
            await self.cycle(out_ready=1)
        assert self.branches == [(1,0x2008)], self.branches
        # Fetch fault dominates a side-effecting instruction, and permit blocks
        # even the exception token on the interrupt/debug drain boundary.
        await self.cycle(fetch_valid=1, fetch_instr=0x0021A023, fetch_pc=0x3000,
                         fetch_fault=1, fetch_cause=1, fetch_tval=0x4000)
        r = await self.cycle(permit=0, out_ready=1)
        assert not r['de_transfer']
        r = await self.cycle(permit=1, out_ready=1)
        assert r['de_transfer']
        assert int(self.dut.ex_fault_o.value)
        assert int(self.dut.ex_cause_o.value) == 1
        assert int(self.dut.ex_tval_o.value) == 0x4000
        assert int(self.dut.ex_pc_o.value) == 0x3000
        assert not int(self.dut.ex_rd_o.value) and not int(self.dut.ex_store_data_o.value)
        await self.cycle(flush=1)
        assert not int(self.dut.de_slot_valid_o.value) and not int(self.dut.ex_valid_o.value)
        await self.cycle(fetch_valid=1, fetch_instr=0x00218067, fetch_pc=0x5000)
        await self.cycle()
        assert bool(int(self.dut.ex_fault_o.value)) == bool(not self.p['ISA_C'])
        if not self.p['ISA_C']:
            assert int(self.dut.ex_cause_o.value) == 0 and int(self.dut.ex_tval_o.value) == 2
        self.logger.info('Branch/fault parent fixture: %d cycles', self.cycles)
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def dependencies(_dut):
    await uvm_root().run_test(DependenciesTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def branch_faults(_dut):
    await uvm_root().run_test(BranchFaultsTest)
