"""Selection, incomplete words, fault portions and stream consumption hints."""
import itertools
import json
import os
import random
from pathlib import Path
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from if_aligner_model import MASK, select


class AlignerTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.enabled = json.loads(os.environ['UQU_COMPONENT_PARAMS'])['ISA_C']
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.checks = 0

    async def check(self, **changes):
        i = dict(valid=1,pc=0x1000,word0_valid=1,word0_data=0x00850001,
                 word0_error=0,word1_valid=1,word1_data=0x00010050,word1_error=0)
        i.update(changes)
        for name,value in i.items():
            getattr(self.dut,name+'_i').value = value
        await Timer(1,units='ns')
        expected = select(i,self.enabled)
        for name,value in expected.items():
            actual = int(getattr(self.dut,name+'_o').value)
            assert actual==value,(name,actual,value,i,self.enabled)
        assert not expected['exception_valid'] or expected['valid']
        if not expected['valid'] or expected['exception_valid']:
            assert not expected['instr'] and not expected['compressed'] and not expected['drop_word']
            assert expected['next_pc']==i['pc']
        self.checks += 1
        return expected

    def report(self):
        self.logger.info('%d selections checked; ISA_C=%d',self.checks,self.enabled)


class DirectedTest(AlignerTest):
    async def run_phase(self):
        self.raise_objection()
        for pc in (0,1,2,3,0x1000,0x1002,0xFFFFFFFC,0xFFFFFFFE):
            for flags in itertools.product((0,1),repeat=5):
                active,v0,e0,v1,e1 = flags
                for prefix in range(4):
                    half = 0x0090|prefix
                    word = half<<16|half
                    await self.check(valid=active,pc=pc,word0_valid=v0,word0_error=e0,
                                     word1_valid=v1,word1_error=e1,word0_data=word)
        if self.enabled:
            r = await self.check(pc=0x1002,word0_data=0x00930001)
            assert r['valid'] and r['instr']==0x00500093 and r['next_pc']==0x1006
            assert r['word1_needed'] and r['drop_word'] and not r['compressed']
            r = await self.check(pc=0x1002,word0_data=0x00930001,word1_valid=0,word1_error=1)
            assert not r['valid'] and r['word1_needed'] and not r['exception_valid']
            r = await self.check(pc=0x1002,word0_data=0x00930001,word1_error=1)
            assert r['valid'] and r['exception_tval']==0x1004 and r['exception_cause']==1
            r = await self.check(pc=0x1002,word0_data=0x00930001,word0_error=1,word1_valid=0)
            assert r['valid'] and r['exception_tval']==0x1002 and not r['word1_needed']
            r = await self.check(pc=0xFFFFFFFE,word0_data=0x00930001,word1_error=1)
            assert r['exception_valid'] and r['exception_tval']==0
            r = await self.check(pc=0xFFFFFFFE,word0_data=0x00930001)
            assert r['instr']==0x00500093 and r['next_pc']==2 and r['drop_word']
            r = await self.check(word1_error=1,word1_valid=0)
            assert r['instr']==1 and r['compressed'] and not r['word1_needed'] and not r['drop_word']
            r = await self.check(pc=0x1002,word1_error=1)
            assert r['instr']==0x0085 and r['compressed'] and r['next_pc']==0x1004 and r['drop_word']
        else:
            r = await self.check(word0_data=0x00850001,word1_error=1)
            assert r['instr']==0x00850001 and not r['compressed'] and r['next_pc']==0x1004
            assert r['drop_word'] and not r['word1_needed']
            r = await self.check(pc=0x1002)
            assert r['misaligned'] and not r['valid'] and not r['exception_valid']
        self.report()
        self.drop_objection()


class PrefixesTest(AlignerTest):
    async def run_phase(self):
        self.raise_objection()
        for half in range(65536):
            other = (half*31337 ^ 0xA55A)&65535
            second = (half*0x9E3779B1+0x12345678)&MASK
            for offset in (0,2):
                word = half<<16|other if offset else other<<16|half
                await self.check(pc=0x1000+offset,word0_data=word,word1_data=second)
        self.report()
        self.drop_objection()


class RandomizedTest(AlignerTest):
    async def run_phase(self):
        self.raise_objection()
        for _ in range(16384):
            await self.check(valid=self.rng.randrange(2),pc=self.rng.getrandbits(32),
                word0_valid=self.rng.randrange(2),word0_error=self.rng.randrange(2),
                word1_valid=self.rng.randrange(2),word1_error=self.rng.randrange(2),
                word0_data=self.rng.getrandbits(32),word1_data=self.rng.getrandbits(32))
        self.report()
        self.drop_objection()


class StreamTest(AlignerTest):
    async def run_phase(self):
        self.raise_objection()
        start = 0xFFFFFFE2 if self.enabled else 0xFFFFFFE0
        tokens = []
        for n in range(128):
            if self.enabled and n%3!=1:
                value = self.rng.getrandbits(16)&~3 | self.rng.randrange(3)
                size = 2
            else:
                value = self.rng.getrandbits(32)
                if self.enabled:
                    value |= 3
                size = 4
            tokens.append((value,size))
        image = {}
        absolute = start
        for value,size in tokens:
            for byte in value.to_bytes(size,'little'):
                image[absolute&MASK] = byte
                absolute += 1
        words = {addr&~3 for addr in image}
        data = {addr:sum(image.get((addr+k)&MASK,0x5A)<<(8*k) for k in range(4)) for addr in words}
        available = set()
        loaded = set()
        pc = start
        index = 0
        stalls = 0
        for _ in range(4096):
            base = pc&~3
            successor = (base+4)&MASK
            for address in (base,successor):
                if address in words and address not in available and self.rng.randrange(3)==0:
                    assert address not in loaded,'word fetched twice instead of reused'
                    available.add(address)
                    loaded.add(address)
            assert len(available)<=2
            r = await self.check(pc=pc,word0_valid=int(base in available),
                word0_data=data.get(base,0),word0_error=0,
                word1_valid=int(successor in available),word1_data=data.get(successor,0),word1_error=0)
            ready = self.rng.randrange(2)
            if r['valid']:
                value,size = tokens[index]
                assert r['instr']==value and r['compressed']==int(size==2)
                assert r['next_pc']==(pc+size)&MASK and not r['exception_valid']
                next_base = ((pc+size)&MASK)&~3
                assert r['drop_word']==int(next_base!=base)
                # Consumer stalls cannot themselves consume a halfword or word.
                if not ready:
                    stalls += 1
                    continue
                if r['drop_word']:
                    available.remove(base)
                pc = (pc+size)&MASK
                index += 1
                if index==len(tokens):
                    break
        else:
            raise AssertionError('stream did not drain')
        assert index==len(tokens) and stalls
        self.logger.info('%d instructions from %d fetched words; %d consumer stalls',index,len(loaded),stalls)
        self.report()
        self.drop_objection()


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def prefixes(_dut):
    await uvm_root().run_test(PrefixesTest)


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def stream(_dut):
    await uvm_root().run_test(StreamTest)
