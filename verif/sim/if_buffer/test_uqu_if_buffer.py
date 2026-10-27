"""Fetched-word storage checked against a deque, including non-power-of-two rings."""
from collections import Counter, deque
import json
import os
import random

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test


class BufferTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.depth = params['MUA_IF_BUFFER_WORDS']
        self.bypass = bool(params.get('MUA_REDIRECT_BYPASS',0) & 1)
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.queue = deque()
        self.coverage = Counter()

    async def cycle(self, **changes):
        i = dict(rst_n=1,flush=0,clear=0,push_valid=0,push_addr=0,push_data=0,
                 push_error=0,pop=0)
        i.update(changes)
        d = self.dut
        d.clk_i.value = 0
        for name,value in i.items():
            getattr(d,'rst_ni' if name=='rst_n' else name+'_i').value = value
        await Timer(1,units='ns')
        active = bool(i['rst_n'] and not i['flush'])
        incoming = (i['push_addr']&0xFFFFFFFC,0 if i['push_error'] else i['push_data'],i['push_error'])
        view = list(self.queue)
        if active and self.bypass and i['push_valid'] and len(view)<2:
            view.append(incoming)
        removing = bool(active and view and i['pop'])
        expected = dict(push_ready=int(active and (len(self.queue)<self.depth or bool(self.queue and i['pop']))))
        for index in range(2):
            present = active and len(view)>index
            word = view[index] if present else (0,0,0)
            expected.update({f'word{index}_valid':int(present),f'word{index}_addr':word[0],
                             f'word{index}_data':word[1],f'word{index}_error':word[2]})
        for name,value in expected.items():
            if name.endswith('_data') and not expected[name.replace('_data','_valid')]:
                index = int(name[4])
                if i['rst_n'] and i['flush'] and len(self.queue)>index:
                    actual = int(getattr(d,name+'_o').value)
                    assert actual==self.queue[index][1], 'flush changed stored lookahead bytes before the edge'
                continue
            actual = int(getattr(d,name+'_o').value)
            assert actual==value,(name,actual,value,i,list(self.queue),self.depth)
        inserting = bool(i['push_valid'] and expected['push_ready'])
        self.coverage[(len(self.queue),inserting,removing)] += 1
        if not active or i['clear']:
            self.queue.clear()
        else:
            if inserting:
                self.queue.append(incoming)
            if removing:
                self.queue.popleft()
        assert len(self.queue)<=self.depth
        d.clk_i.value = 1
        await Timer(1,units='ns')
        return expected

    async def reset(self):
        await self.cycle(rst_n=0,push_valid=1,pop=1,push_error=1)
        await self.cycle()

    async def push(self, number, **changes):
        return await self.cycle(push_valid=1,push_addr=(0xFFFFFFE0+4*number)&0xFFFFFFFF,
            push_data=(number*0x9E3779B1)&0xFFFFFFFF,push_error=number%3==1,**changes)


class DirectedTest(BufferTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        # Only the optional IF wrapper may consume a live first word directly.
        r = await self.push(0,pop=1)
        assert r['word0_valid']==self.bypass
        await self.cycle(pop=1)
        await self.cycle(pop=1)
        for round_number in range(4):
            for index in range(self.depth):
                await self.push(round_number*self.depth+index)
            for _ in range(8):
                r = await self.push(100)
                assert not r['push_ready']
            # Full-ring simultaneous replacement crosses both pointer wrap points.
            for index in range(3*self.depth):
                r = await self.push(200+index,pop=1)
                assert r['push_ready'] and r['word1_valid']
            for _ in range(self.depth):
                await self.cycle(pop=1)
            r = await self.cycle(pop=1)
            assert not r['word0_valid'] and not r['word1_valid']
        # Alignment, repeated addresses, arbitrary payload, and failed words.
        for address in (0,1,2,3,0xFFFFFFFF,0xFFFFFFFE,0x1234567B):
            await self.cycle(push_valid=1,push_addr=address,push_data=0xDEADBEEF,push_error=1)
            for _ in range(4):
                r = await self.cycle()
                assert r['word0_addr']==address&~3 and r['word0_error'] and not r['word0_data']
            await self.cycle(pop=1)
        assert self.coverage[(self.depth,True,True)]>=12*self.depth
        self.drop_objection()


class RandomizedTest(BufferTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        for index in range(8192):
            await self.cycle(push_valid=int(self.rng.random()<0.7),
                push_addr=self.rng.getrandbits(32),push_data=self.rng.getrandbits(32),
                push_error=self.rng.randrange(2),pop=int(self.rng.random()<0.6),
                clear=int(index%127==126),flush=int(index%257==256),rst_n=int(index%1021!=1020))
        while self.queue:
            await self.cycle(pop=1)
        await self.cycle()
        for count in range(self.depth+1):
            assert any(key[0]==count for key in self.coverage),('occupancy not reached',count)
        assert self.coverage[(self.depth,True,True)]
        assert self.coverage[(0,True,False)]
        self.drop_objection()


class ControlTest(BufferTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        for count in range(self.depth+1):
            for reset in (False,True):
                for index in range(count):
                    await self.push(index)
                await self.cycle(rst_n=int(not reset),flush=int(not reset),
                                 push_valid=1,push_addr=0x8000,push_data=0xBAD,pop=1)
                r = await self.cycle(pop=1)
                assert r['push_ready'] and not r['word0_valid'] and not r['word1_valid']
                # Old payload/error storage must stay hidden after invalidation.
                await self.cycle(flush=1,push_valid=1,push_error=1)
                await self.cycle(flush=1,pop=1)
                await self.push(9)
                r = await self.cycle()
                assert r['word0_valid'] and not r['word1_valid']
                await self.cycle(pop=1)
        self.drop_objection()


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def directed(dut):
    await uvm_root().run_test('DirectedTest')


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def randomized(dut):
    await uvm_root().run_test('RandomizedTest')


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def control(dut):
    await uvm_root().run_test('ControlTest')
