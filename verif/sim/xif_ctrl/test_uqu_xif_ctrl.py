"""Interface lifetime tests, independent of instruction/pipeline implementation."""
import json
import os

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_test, uvm_root


class ControllerTest(uvm_test):
    def build_phase(self):
        self.dut=cocotb.top
        self.enabled=json.loads(os.environ['UQU_COMPONENT_PARAMS'])['XIF']
        self.inputs=dict(draining=0,de_valid=1,de_fire=0,de_flush=0,de_issued=0,issue_valid=0,
            de_cleanup_valid=0,de_cleanup_id=0,ex_valid=0,ex_xif=0,ex_id=0,ex_flush=0,
            mem_valid=0,mem_xif=0,mem_id=0,mem_flush=0,wb_retire=0,wb_xif=0,wb_id=0,
            commit_valid=0,commit_id=0,commit_kill=0,kill_ready=0)

    async def cycle(self, rst=1, **changes):
        self.inputs.update(changes)
        self.dut.clk_i.value=0
        self.dut.rst_ni.value=rst
        for name,value in self.inputs.items(): getattr(self.dut,name+'_i').value=value
        await Timer(1,units='ns')
        result={name:int(getattr(self.dut,name+'_o').value) for name in
            ('de_id_valid','de_id','de_cancel','de_cleanup_ready','kill_valid','kill_id','drain_ready')}
        if not self.enabled:
            assert result==dict(de_id_valid=0,de_id=0,de_cancel=0,de_cleanup_ready=0,
                                kill_valid=0,kill_id=0,drain_ready=1),result
        self.dut.clk_i.value=1
        await Timer(1,units='ns')
        return result

    async def reserve(self, ident):
        row=await self.cycle(issue_valid=1,de_issued=0,de_fire=0)
        if self.enabled: assert row['de_id_valid'] and row['de_id']==ident,row

    async def advance(self):
        await self.cycle(issue_valid=0,de_issued=1,de_fire=1)
        await self.cycle(de_issued=0,de_fire=0)

    async def acknowledge(self, ident):
        row=await self.cycle(kill_ready=1,commit_valid=1,commit_kill=1,commit_id=ident)
        if self.enabled: assert row['kill_valid'] and row['kill_id']==ident,row
        await self.cycle(kill_ready=0,commit_valid=0,commit_kill=0)


class Lifecycle(ControllerTest):
    async def run_phase(self):
        self.raise_objection(); await self.cycle(rst=0)
        for ident in range(4):
            await self.reserve(ident)
            for _ in range(3):
                row=await self.cycle()
                if self.enabled: assert row['de_id']==ident and not row['drain_ready'],row
            await self.advance()
        # Commit permission does not release the ID or retire an operation.
        for ident in range(4):
            row=await self.cycle(commit_valid=1,commit_kill=0,commit_id=ident)
            if self.enabled: assert not row['drain_ready'],row
            await self.cycle(commit_valid=0,wb_retire=1,wb_xif=1,wb_id=ident)
            await self.cycle(wb_retire=0)
        row=await self.cycle()
        if self.enabled: assert row['drain_ready'],row
        self.drop_objection()


class Cleanup(ControllerTest):
    async def run_phase(self):
        self.raise_objection(); await self.cycle(rst=0)
        # Unaccepted requests retract without a commit or result transaction.
        await self.reserve(0)
        await self.cycle(issue_valid=0,de_flush=1)
        row=await self.cycle(de_flush=0)
        if self.enabled: assert row['drain_ready'] and not row['kill_valid'],row
        for ident in (1,2,3):
            await self.reserve(ident); await self.advance()
        # Two flushed stages and an accepted speculative DE slot need separate
        # notifications even after the parent has discarded all three slots.
        await self.reserve(4)
        row=await self.cycle(issue_valid=0,de_issued=1,draining=1,
            ex_valid=1,ex_xif=1,ex_id=2,ex_flush=1,
            mem_valid=1,mem_xif=1,mem_id=3,mem_flush=1)
        if self.enabled: assert row['de_cancel'] and row['kill_valid'],row
        await self.cycle(de_issued=0,ex_valid=0,mem_valid=0)
        for ident in (2,3,4): await self.acknowledge(ident)
        # The older WB instruction survives speculative kills and drains last.
        row=await self.cycle(draining=0,wb_retire=1,wb_xif=1,wb_id=1)
        if self.enabled: assert not row['drain_ready'],row
        row=await self.cycle(wb_retire=0)
        if self.enabled: assert row['drain_ready'],row
        self.drop_objection()


class Wraparound(ControllerTest):
    async def run_phase(self):
        self.raise_objection(); await self.cycle(rst=0)
        await self.reserve(0); await self.advance()
        for ident in range(1,8):
            await self.reserve(ident)
            await self.cycle(issue_valid=0,de_issued=1,de_cleanup_valid=1,de_cleanup_id=ident)
            await self.acknowledge(ident)
            await self.cycle(de_cleanup_valid=0,de_fire=1)
            await self.cycle(de_issued=0,de_fire=0)
        row=await self.cycle()
        if self.enabled: assert not row['de_id_valid'],row
        await self.cycle(wb_retire=1,wb_xif=1,wb_id=0)
        row=await self.cycle(wb_retire=0)
        if self.enabled: assert row['de_id_valid'] and row['de_id']==0,row
        # Reset clears both reservations and pending kills.
        await self.reserve(0)
        await self.cycle(issue_valid=0,de_issued=1,de_cleanup_valid=1,de_cleanup_id=0)
        await self.cycle(rst=0)
        row=await self.cycle(de_cleanup_valid=0,de_issued=0)
        if self.enabled: assert row['drain_ready'] and row['de_id_valid'] and row['de_id']==0,row
        self.drop_objection()


@cocotb.test()
async def lifecycle(_dut): await uvm_root().run_test('Lifecycle')

@cocotb.test()
async def cleanup(_dut): await uvm_root().run_test('Cleanup')

@cocotb.test()
async def wraparound(_dut): await uvm_root().run_test('Wraparound')
