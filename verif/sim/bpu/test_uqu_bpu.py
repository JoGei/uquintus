"""Black-box target/direction learning, aliasing and lifecycle regression."""
import json
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from bpu_model import BpuModel


class PredictorTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.model = BpuModel(self.params)
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))

    async def cycle(self, **changes):
        inputs = dict(rst_n=1, invalidate=0, lookup_valid=1, lookup_pc=0x1000,
                      update_valid=0, update_pc=0x1000, update_control_flow=1,
                      update_conditional=1, update_taken=1, update_target=0x2000)
        inputs.update(changes)
        self.dut.clk_i.value = 0
        for name, value in inputs.items():
            getattr(self.dut, 'rst_ni' if name == 'rst_n' else name + '_i').value = value
        await Timer(1, units='ns')
        expected = self.model.lookup(inputs['lookup_pc'], bool(inputs['lookup_valid'] and inputs['rst_n']),
                                     inputs['invalidate'])
        actual = {name: int(getattr(self.dut, name + '_o').value) for name in expected}
        assert actual == expected, (actual, expected, inputs)
        self.model.step(reset=not inputs['rst_n'], invalidate=inputs['invalidate'],
                        valid=inputs['update_valid'], pc=inputs['update_pc'],
                        control_flow=inputs['update_control_flow'], conditional=inputs['update_conditional'],
                        taken=inputs['update_taken'], target=inputs['update_target'])
        self.dut.clk_i.value = 1
        await Timer(1, units='ns')
        return actual


class TrainingTest(PredictorTest):
    async def run_phase(self):
        self.raise_objection()
        await self.cycle(rst_n=0)
        assert not (await self.cycle())['hit']
        # Both allocation directions, saturation and direction reversal.
        for initial in (0, 1):
            await self.cycle(invalidate=1)
            await self.cycle(update_valid=1, update_taken=initial)
            for taken in [initial] * 6 + [1-initial] * 6 + [initial] * 4:
                await self.cycle(update_valid=1, update_taken=taken)
            await self.cycle()
        # JAL/JALR predictions are unconditional, including changed targets.
        for target in (0x3000, 0x4000, 0x1000):
            await self.cycle(update_valid=1, update_conditional=0, update_target=target)
            actual = await self.cycle()
            if self.model.enabled:
                assert actual == dict(hit=1, taken=1, target=target)
        self.drop_objection()


class AliasingTest(PredictorTest):
    async def run_phase(self):
        self.raise_objection()
        await self.cycle(rst_n=0)
        stride = self.model.capacity * self.model.alignment
        # A colliding tag replaces an entry; non-control misses do not evict it.
        for pc in (0x1000, 0x1000+stride, 0x1000, 0xfffffff0):
            await self.cycle(update_valid=1, update_pc=pc, update_target=0x8000)
            await self.cycle(lookup_pc=pc)
            await self.cycle(lookup_pc=pc ^ 0x10000000)
            await self.cycle(update_valid=1, update_pc=(pc+stride)&0xffffffff,
                             update_control_flow=0, lookup_pc=pc)
            await self.cycle(lookup_pc=pc)
        # Adjacent halfword PCs are independent when compressed is enabled.
        for pc in (0x1000, 0x1002):
            await self.cycle(update_valid=1, update_pc=pc, update_target=0x2000)
        for pc in (0x1000, 0x1002, 0x1001):
            await self.cycle(lookup_pc=pc)
        self.drop_objection()


class LifecycleTest(PredictorTest):
    async def run_phase(self):
        self.raise_objection()
        await self.cycle(rst_n=0)
        await self.cycle(update_valid=1)
        await self.cycle(lookup_valid=0)
        await self.cycle()
        await self.cycle(update_valid=1, update_control_flow=0)
        assert not (await self.cycle())['hit']
        await self.cycle(update_valid=1)
        await self.cycle(update_valid=1, update_target=0x2001)
        assert not (await self.cycle())['hit']
        for reset in (False, True):
            await self.cycle(update_valid=1)
            await self.cycle(rst_n=int(not reset), invalidate=int(not reset), update_valid=1)
            assert not (await self.cycle())['hit']
        self.drop_objection()


class RandomizedTest(PredictorTest):
    async def run_phase(self):
        self.raise_objection()
        await self.cycle(rst_n=0)
        pcs = [0x1000 + self.model.alignment * k for k in range(2*self.model.capacity)]
        for _ in range(4096):
            await self.cycle(lookup_pc=self.rng.choice(pcs), lookup_valid=self.rng.randrange(2),
                             update_valid=self.rng.randrange(2), update_pc=self.rng.choice(pcs),
                             update_control_flow=int(self.rng.random() < 0.8),
                             update_conditional=self.rng.randrange(2), update_taken=self.rng.randrange(2),
                             update_target=self.rng.choice(pcs), invalidate=int(self.rng.random() < 0.005))
        self.drop_objection()


@cocotb.test()
async def training(dut):
    await uvm_root().run_test('TrainingTest')


@cocotb.test()
async def aliasing(dut):
    await uvm_root().run_test('AliasingTest')


@cocotb.test()
async def lifecycle(dut):
    await uvm_root().run_test('LifecycleTest')


@cocotb.test()
async def randomized(dut):
    await uvm_root().run_test('RandomizedTest')
