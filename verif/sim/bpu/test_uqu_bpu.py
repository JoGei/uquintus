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
        inputs.update(stream_flush=0, capture_valid=0, capture_pc=0, capture_instr=0)
        inputs.update(changes)
        self.history = (getattr(self, 'history', []) + [inputs])[-12:]
        self.dut.clk_i.value = 0
        for name, value in inputs.items():
            getattr(self.dut, 'rst_ni' if name == 'rst_n' else name + '_i').value = value
        await Timer(1, units='ns')
        expected = self.model.lookup(inputs['lookup_pc'], bool(inputs['lookup_valid'] and inputs['rst_n']),
                                     inputs['invalidate'])
        prefix = self.model.payload(inputs['lookup_pc']) if inputs['rst_n'] and not inputs['invalidate'] and inputs['lookup_valid'] else []
        assert int(self.dut.idata_hwords_o.value) == sum(self.model.length(w)//2 for w in prefix), (int(self.dut.idata_hwords_o.value),prefix,self.model.fill,self.model.payloads,self.history)
        assert int(self.dut.idata_o.value) == self.model.packed(prefix)
        if prefix:
            target = self.model.entries[(inputs['lookup_pc']//self.model.alignment)%self.model.capacity]['target']
            assert int(self.dut.idata_next_pc_o.value) == (target + sum(map(self.model.length, prefix))) & 0xffffffff
        actual = {name: int(getattr(self.dut, name + '_o').value) for name in expected}
        assert actual == expected, (actual, expected, inputs)
        self.model.step(reset=not inputs['rst_n'], invalidate=inputs['invalidate'],
                        valid=inputs['update_valid'], pc=inputs['update_pc'],
                        control_flow=inputs['update_control_flow'], conditional=inputs['update_conditional'],
                        taken=inputs['update_taken'], target=inputs['update_target'],
                        stream_flush=inputs['stream_flush'], capture_valid=inputs['capture_valid'],
                        capture_pc=inputs['capture_pc'], capture_instr=inputs['capture_instr'])
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

class IdataTest(PredictorTest):
    async def run_phase(self):
        self.raise_objection()
        await self.cycle(rst_n=0)
        hwords = self.model.hwords
        if not hwords:
            await self.cycle(update_valid=1, capture_valid=1, capture_pc=0x2000, capture_instr=0x13)
            assert int(self.dut.idata_hwords_o.value) == 0
            self.drop_objection(); return
        if hwords == 1:
            # One halfword may retain C16, never a partial C32 instruction.
            await self.cycle(update_valid=1,capture_valid=1,capture_pc=0x2000,capture_instr=0x13)
            assert self.model.payload(0x1000) == []
            await self.cycle(update_valid=1,capture_valid=1,capture_pc=0x2000,capture_instr=1)
            assert self.model.payload(0x1000) == [1]
            await self.cycle(capture_valid=1,capture_pc=0x2002,capture_instr=0x13)
            assert self.model.payload(0x1000) == [1]
            await self.cycle(invalidate=1)
            assert self.model.payload(0x1000) == []
            self.drop_objection(); return
        # Concurrent allocation/first capture; bubbles do not consume slots.
        # C16 and crossing C32 are stored as original assembled instructions.
        words = self.model.fit_prefix([1 if self.params['ISA_C'] and k%2 == 0 else 0x100093+0x100000*k
                 for k in range(hwords)])
        pc = 0xfffffffe if self.params['ISA_C'] else 0xfffffff8
        target = pc
        await self.cycle(update_valid=1, update_target=target, capture_valid=1,
                         capture_pc=pc, capture_instr=words[0])
        pc = (pc+self.model.length(words[0])) & 0xffffffff
        for word in words[1:]:
            await self.cycle(capture_instr=self.rng.getrandbits(32))
            await self.cycle(capture_valid=1,capture_pc=pc,capture_instr=word)
            pc = (pc+self.model.length(word)) & 0xffffffff
        await self.cycle(capture_valid=1,capture_pc=pc,capture_instr=0x13)
        assert self.model.payload(0x1000) == words
        # Reads, flushes and repeated updates retain a warm prefix.
        for _ in range(3):
            await self.cycle(stream_flush=1)
            await self.cycle(update_valid=1, update_target=target)
            await self.cycle(capture_valid=1,capture_pc=target,capture_instr=words[0])
            await self.cycle()
            assert self.model.payload(0x1000) == words
        # Changed target, partial fill and later extension at the fixed origin.
        await self.cycle(update_valid=1,update_target=0x4000)
        await self.cycle(capture_valid=1,capture_pc=0x4000,capture_instr=0x13)
        await self.cycle(stream_flush=1)
        assert self.model.payload(0x1000) == [0x13]
        await self.cycle(update_valid=1,update_target=0x4000)
        for k in range(hwords//2):
            await self.cycle(capture_valid=1,capture_pc=0x4000+4*k,capture_instr=0x13)
        assert self.model.payload(0x1000) == [0x13]*(hwords//2)
        # Tag miss by a non-control does not clear somebody else's payload.
        alias = 0x1000+self.model.capacity*self.model.alignment
        await self.cycle(update_valid=1,update_pc=alias,update_control_flow=0)
        await self.cycle()
        assert self.model.payload(0x1000) == [0x13]*(hwords//2)
        # Replacement, stale fill and global invalidation cannot leak bytes.
        await self.cycle(update_valid=1,update_pc=alias,update_target=0x8000)
        await self.cycle(capture_valid=1,capture_pc=0x4004,capture_instr=0x13)
        await self.cycle(lookup_pc=alias)
        await self.cycle(invalidate=1,capture_valid=1,capture_pc=0x8000,capture_instr=0x13)
        await self.cycle(lookup_pc=alias)
        if self.params['ISA_C']:
            # Leave one halfword free: C32 must not be partially appended.
            # Upper input padding is irrelevant to a retained C16 encoding.
            await self.cycle(invalidate=1)
            target = 0x8002
            await self.cycle(update_valid=1,update_target=target,
                             capture_valid=1,capture_pc=target,capture_instr=0xdead0001)
            for k in range(1,hwords-1):
                await self.cycle(capture_valid=1,capture_pc=target+2*k,capture_instr=1)
            tail = target+2*(hwords-1)
            await self.cycle(capture_valid=1,capture_pc=tail,capture_instr=0x13)
            assert self.model.payload(0x1000) == [1]*(hwords-1)
            await self.cycle(capture_valid=1,capture_pc=tail,capture_instr=1)
            assert self.model.payload(0x1000) == [1]*(hwords-1), 'overflow must stop the old fill stream'
            await self.cycle(update_valid=1,update_target=target,
                             capture_valid=1,capture_pc=target,capture_instr=1)
            for k in range(1,hwords):
                await self.cycle(capture_valid=1,capture_pc=target+2*k,capture_instr=1)
            assert self.model.payload(0x1000) == [1]*hwords
        # Random lifecycle/capture interleavings, checked against the model.
        pcs = [0x1000+self.model.alignment*k for k in range(2*self.model.capacity)]
        for _ in range(2048):
            fill_pc = self.model.fill[1] if self.model.fill else 0x2000
            await self.cycle(lookup_pc=self.rng.choice(pcs),update_valid=self.rng.random()<0.2,
                update_pc=self.rng.choice(pcs),update_target=0x2000,
                update_control_flow=self.rng.random()<0.8,update_taken=self.rng.randrange(2),
                stream_flush=self.rng.random()<0.01,capture_valid=self.rng.random()<0.6,
                capture_pc=fill_pc if self.rng.random()<0.9 else 0x4000,
                capture_instr=1 if self.params['ISA_C'] and self.rng.random()<0.5 else 0x13,
                invalidate=self.rng.random()<0.005)
        self.drop_objection()


@cocotb.test()
async def idata(dut):
    await uvm_root().run_test('IdataTest')
