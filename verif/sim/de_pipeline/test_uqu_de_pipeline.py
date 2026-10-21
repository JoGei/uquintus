"""Real parent registers and GPR/hazard integration around native DE."""
import json
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from compressed_model import expand


class ParentTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.p = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.cycles = 0
        self.transfers = 0
        self.branches = []
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))

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
                   'ex_pc','ex_rd','ex_a','ex_b','ex_store_data','ex_captured','ex_source_ready',
                   'de_instr','de_original','de_compressed','de_fault','de_cause','de_tval',
                   'ex_original','ex_compressed','ex_link')}
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


class CompressedTokensTest(ParentTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        expand_if = self.p['MUA_C_IMPL'] == 0 and self.p['MUA_C_DECOMPRESS_STAGE'] == 0
        if not self.p['ISA_C']:
            await self.cycle(fetch_valid=1, fetch_instr=0x0085, fetch_original=0x0085,
                             fetch_compressed=1)
            r = await self.cycle()
            assert r['de_transfer'] and int(self.dut.ex_fault_o.value)
            assert int(self.dut.ex_cause_o.value) == 2
            assert int(self.dut.ex_tval_o.value) == 0x0085
            self.drop_objection()
            return
        # A full EX slot holds the compressed call in IF/DE for several cycles.
        await self.cycle(fetch_valid=1, fetch_instr=0x13)
        await self.cycle(fetch_valid=1, fetch_instr=0x2001,
                         fetch_original=0x2001, fetch_compressed=1, fetch_pc=0x1002)
        for _ in range(4):
            r = await self.cycle()
            assert r['de_slot_valid'] and not r['de_transfer'] and not r['branch_resolve']
            assert r['de_instr'] == (0xEF if expand_if else 0x2001)
            assert r['de_original'] == 0x2001 and r['de_compressed'] and not r['de_fault']
        r = await self.cycle(out_ready=1)
        assert r['de_transfer'] and r['branch_resolve'] and r['next_pc'] == 0x1002
        assert int(self.dut.ex_pc_o.value) == 0x1002 and int(self.dut.ex_rd_o.value) == 1
        assert int(self.dut.ex_original_o.value) == 0x2001
        assert int(self.dut.ex_compressed_o.value) and int(self.dut.ex_link_o.value) == 0x1004
        r = await self.cycle(out_ready=1)
        assert not r['de_transfer'] and not r['branch_resolve']
        await self.cycle(flush=1)
        await self.cycle(fetch_valid=1, fetch_instr=0x0185,
                         fetch_original=0x0185, fetch_compressed=1, fetch_pc=0x1004)
        r = await self.cycle()
        assert r['de_transfer'] and not int(self.dut.ex_fault_o.value)
        assert int(self.dut.ex_rd_o.value) == 3
        assert int(self.dut.ex_a_o.value) == 0 and int(self.dut.ex_b_o.value) == 1
        # Reserved C.LWSP x0 retains its original halfword through a held fault.
        await self.cycle(flush=1)
        await self.cycle(fetch_valid=1, fetch_instr=0x4002,
                         fetch_original=0x4002, fetch_compressed=1, fetch_pc=0x2002)
        r = await self.cycle(permit=0)
        assert not r['de_transfer']
        assert r['de_instr'] == (0 if expand_if else 0x4002)
        assert r['de_fault'] == int(expand_if)
        assert r['de_original'] == 0x4002 and r['de_compressed']
        if expand_if:
            assert r['de_cause'] == 2 and r['de_tval'] == 0x4002
        r = await self.cycle(permit=1)
        assert r['de_transfer'] and int(self.dut.ex_fault_o.value)
        assert int(self.dut.ex_pc_o.value) == 0x2002
        assert int(self.dut.ex_cause_o.value) == 2 and int(self.dut.ex_tval_o.value) == 0x4002
        assert int(self.dut.ex_original_o.value) == 0x4002
        assert int(self.dut.ex_compressed_o.value) and not int(self.dut.ex_link_o.value)
        # A prior fetch fault wins over illegal expansion in every placement.
        await self.cycle(flush=1)
        await self.cycle(fetch_valid=1, fetch_instr=0x4002, fetch_original=0x4002,
                         fetch_compressed=1, fetch_pc=0x3002,
                         fetch_fault=1, fetch_cause=1, fetch_tval=0x4004)
        r = await self.cycle(permit=0)
        assert r['de_fault'] and r['de_cause'] == 1 and r['de_tval'] == 0x4004
        await self.cycle()
        assert int(self.dut.ex_fault_o.value) and int(self.dut.ex_cause_o.value) == 1
        assert int(self.dut.ex_tval_o.value) == 0x4004
        assert int(self.dut.ex_original_o.value) == 0x4002
        # Flush a held compressed call; its length must not leak to replacement.
        await self.cycle(flush=1)
        await self.cycle(fetch_valid=1, fetch_instr=0x2001, fetch_original=0x2001,
                         fetch_compressed=1, fetch_pc=0x5002)
        r = await self.cycle(permit=0)
        assert r['de_slot_valid'] and not r['de_transfer']
        r = await self.cycle(flush=1)
        assert not r['branch_resolve']
        assert not int(self.dut.de_slot_valid_o.value) and not int(self.dut.ex_valid_o.value)
        await self.cycle(fetch_valid=1, fetch_instr=0x000000EF, fetch_pc=0x6000)
        await self.cycle()
        assert not int(self.dut.ex_compressed_o.value)
        assert int(self.dut.ex_original_o.value) == 0x000000EF
        assert int(self.dut.ex_link_o.value) == 0x6004
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def compressed_tokens(_dut):
    await uvm_root().run_test(CompressedTokensTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def branch_faults(_dut):
    await uvm_root().run_test(BranchFaultsTest)


class CompressedStreamTest(ParentTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        expand_if = self.p['MUA_C_IMPL'] == 0 and self.p['MUA_C_DECOMPRESS_STAGE'] == 0
        templates = [(0x13, 0), (0x12345017, 0), (0x6F, 0)]
        if self.p['ISA_C']:
            templates = [(0xBEEF0001, 1), (0x13, 0), (0xCAFE0005, 1),
                         (0x12345017, 0), (0xA5A50006, 1), (0x6F, 0), (0xBEEFA001, 1)]
        tokens = []
        pc = 0xFFFFFFF2 if self.p['ISA_C'] else 0xFFFFFFF0
        for raw, compressed in templates*4:
            expanded, _ = expand(raw, bool(self.p['ISA_C']))
            assert not expanded['illegal']
            jump = raw & 127 == 0x6F or compressed and raw & 65535 == 0xA001
            link = (pc+(2 if compressed else 4)) & 0xFFFFFFFF if jump else 0
            tokens.append(dict(raw=raw, instr=expanded['instr'] if expand_if else raw,
                               original=expanded['original_instr'], pc=pc,
                               compressed=compressed, link=link, jump=bool(jump)))
            pc = (pc+(2 if compressed else 4)) & 0xFFFFFFFF
        next_token = retired = 0
        de = ex = None
        for _ in range(512):
            incoming = tokens[next_token] if next_token < len(tokens) else None
            ready, permit = self.rng.randrange(2), self.rng.randrange(2)
            fields = dict(fetch_valid=int(incoming is not None), out_ready=ready, permit=permit)
            if incoming:
                fields.update(fetch_instr=incoming['raw'], fetch_original=incoming['raw'],
                              fetch_pc=incoming['pc'], fetch_compressed=incoming['compressed'])
            r = await self.cycle(**fields)
            assert r['de_slot_valid'] == bool(de) and r['ex_valid'] == bool(ex)
            assert r['de_transfer'] == bool(de and permit and (ex is None or ready))
            if de:
                assert (r['de_instr'], r['de_original'], r['de_compressed']) == (
                    de['instr'], de['original'], de['compressed'])
                assert not r['de_fault']
                assert r['branch_resolve'] == bool(r['de_transfer'] and de['jump'])
            if ex:
                assert (r['ex_instr'], r['ex_original'], r['ex_compressed'], r['ex_pc'], r['ex_link']) == (
                    ex['instr'], ex['original'], ex['compressed'], ex['pc'], ex['link'])
                assert not r['ex_fault'] and r['ex_rd'] == 0
                if ready:
                    retired += 1  # Transfer from fixture EX, not architectural retirement.
            if ex is None or ready:
                ex = de if r['de_transfer'] else None
            if r['fetch_ready']:
                de = incoming
                next_token += int(incoming is not None)
            if next_token == len(tokens) and de is None and ex is None:
                break
        else:
            raise AssertionError('compressed stream did not drain')
        assert retired == len(tokens)
        self.logger.info('%d mixed-length tokens crossed real IF/DE and DE/EX storage', retired)
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def compressed_stream(_dut):
    await uvm_root().run_test(CompressedStreamTest)
