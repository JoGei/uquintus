"""Passive monitor lifecycle: held lookup, boundary stalls, squash and retirement."""
import json
import os
from pathlib import Path
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from bpu_stats import COUNTERS, statistics, unpack_snapshot


class MonitorTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.valid = 0
        self.pc = 0x1000

    async def tick(self, **changes):
        values = dict(rst_n=1, if_valid=0, if_ready=0, if_flush=0,
                      if_pc=self.pc, if_predicted_next_pc=self.pc+4,
                      if_btb_hit=0, if_direction_taken=0, if_effective_taken=0, if_replay=0,
                      stage_valid=self.valid, stage_enable=0, stage_next_valid=0,
                      de_pc=self.pc, de_branch_kind=0, de_taken=0,
                      de_next_pc=self.pc+4, de_redirect=0, de_compressed=0,
                      retire=0, retire_pc=self.pc)
        values.update(changes)
        self.dut.clk_i.value = 0
        for name, value in values.items():
            getattr(self.dut, 'rst_ni' if name == 'rst_n' else name+'_i').value = value
        await Timer(1, units='ns')
        self.dut.clk_i.value = 1
        await Timer(1, units='ns')
        self.valid = ((self.valid & ~values['stage_enable']) |
                      (values['stage_next_valid'] & values['stage_enable'])) if values['rst_n'] else 0
        self.counts = dict(zip(COUNTERS, unpack_snapshot(int(self.dut.counters_o.value))))
        assert int(self.dut.counter_count_o.value) == len(COUNTERS)

    async def instruction(self, *, kind=0, taken=0, prediction=None, btb=0,
                          direction=0, effective=0, compressed=0, retire=True, squash=False, replayed=0):
        actual = self.pc+0x100 if taken else self.pc+4
        prediction = self.pc+4 if prediction is None else prediction
        lookup = dict(if_valid=1, if_pc=self.pc, if_predicted_next_pc=prediction,
                      if_btb_hit=btb, if_direction_taken=direction, if_effective_taken=effective, if_replay=replayed)
        # First presentation is held; live table outputs then change underneath it.
        await self.tick(**lookup)
        changed = dict(lookup, if_btb_hit=1-btb, if_direction_taken=1-direction,
                       if_effective_taken=1-effective)
        await self.tick(**changed)
        await self.tick(**changed, if_ready=1, stage_enable=1, stage_next_valid=1)
        for _ in range(3):
            await self.tick(de_branch_kind=kind, de_taken=taken, de_next_pc=actual)
        if squash:
            await self.tick(stage_enable=1, stage_next_valid=0, if_flush=1)
            return
        await self.tick(stage_enable=3, stage_next_valid=2, de_branch_kind=kind,
                        de_taken=taken, de_next_pc=actual, de_compressed=compressed,
                        de_redirect=int(actual != prediction))
        for source in (1, 2):
            await self.tick()  # Retention under boundary backpressure.
            await self.tick(stage_enable=(3 << source), stage_next_valid=(2 << source))
        await self.tick()  # WB must not count until retirement.
        before = dict(self.counts)
        await self.tick(retire=int(retire), stage_enable=8, stage_next_valid=0)
        if not retire:
            assert self.counts == before
        self.pc += 4

    async def run_phase(self):
        self.raise_objection()
        await self.tick(rst_n=0)
        predicting = self.params['MUA_BRANCH_PREDICTOR'] != 0
        active = predicting and self.params['MUA_BTB'] != 0
        # Three conditional branches: correct taken, wrong direction, wrong target.
        await self.instruction(kind=1, taken=1, prediction=self.pc+0x100 if active else None,
                               btb=int(active), direction=int(predicting), effective=int(active))
        await self.instruction(kind=1, taken=0, prediction=self.pc+0x100 if active else None,
                               btb=int(active), direction=int(predicting), effective=int(active))
        await self.instruction(kind=1, taken=1, prediction=self.pc+0x104 if active else None,
                               btb=int(active), direction=int(predicting), effective=int(active), compressed=1)
        await self.instruction(kind=2, taken=1, replayed=int(active))
        await self.instruction(kind=3, taken=1)
        await self.instruction(btb=int(active))  # Stale BTB entry on ordinary instruction.
        before = dict(self.counts)
        await self.instruction(kind=1, taken=1, squash=True, replayed=1)
        await self.instruction(kind=1, taken=1, retire=False, replayed=1)  # Faulting WB token.
        assert self.counts == before
        assert self.counts['idata_replayed_instructions'] == int(active)
        assert self.counts['retired_instructions'] == 6
        assert self.counts['conditional_branches'] == 3
        assert self.counts['direct_jumps'] == self.counts['indirect_jumps'] == 1
        assert self.counts['taken_conditional_branches'] == 2
        assert self.counts['compressed_control_flow'] == 1
        assert self.counts['btb_hits'] == (4 if active else 0)
        assert self.counts['false_btb_hits'] == int(active)
        assert self.counts['direction_mispredictions'] == int(predicting)
        assert self.counts['target_mispredictions'] == int(active)
        assert self.counts['de_redirects'] == 4
        statistics([0]*len(COUNTERS), [self.counts[k] for k in COUNTERS], self.params, 6)
        # Flush a held IF observation: its metadata must not contaminate replacement.
        await self.tick(if_valid=1, if_btb_hit=1)
        await self.tick(if_flush=1)
        before_hits = self.counts['btb_hits']
        await self.instruction()
        assert self.counts['btb_hits'] == before_hits
        await self.tick(rst_n=0)
        assert not any(self.counts.values())
        self.drop_objection()


@cocotb.test()
async def retirement_and_lifecycle(dut):
    await uvm_root().run_test('MonitorTest')
