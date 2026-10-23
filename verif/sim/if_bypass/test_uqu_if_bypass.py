"""IF delivery policy: shared deque checks plus live first/second-word cases."""
from pathlib import Path
import sys

import cocotb
from pyuvm import uvm_root

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'if_buffer'))
from test_uqu_if_buffer import BufferTest, DirectedTest, RandomizedTest, ControlTest


class LiveWordsTest(BufferTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        # An aligned target can be consumed at once. If blocked, its complete
        # address/data/error token must survive the upstream word disappearing.
        for error in (0,1):
            r=await self.cycle(push_valid=1,push_addr=0x1001,push_data=0xDEADBEEF,
                               push_error=error,pop=1)
            assert r['word0_valid']==self.bypass
            r=await self.cycle()
            assert r['word0_valid']==(not self.bypass)
            await self.cycle(pop=1)
            await self.cycle(push_valid=1,push_addr=0x2000,push_data=0x12345678,push_error=error)
            for _ in range(8):
                r=await self.cycle()
                assert r['word0_valid'] and r['word0_error']==error
                assert r['word0_data']==(0 if error else 0x12345678)
            await self.cycle(pop=1)
        # A crossing instruction consumes the stored first word while using
        # the arriving second word, whose remaining half must stay in storage.
        await self.cycle(push_valid=1,push_addr=0x3000,push_data=0x00930001)
        r=await self.cycle(push_valid=1,push_addr=0x3004,push_data=0x00850010,pop=1)
        assert r['word1_valid']==self.bypass
        r=await self.cycle()
        assert r['word0_valid'] and r['word0_addr']==0x3004 and r['word0_data']==0x00850010
        assert not r['word1_valid']
        # A failed second word has the same visibility/retention contract.
        await self.cycle(push_valid=1,push_addr=0x3008,push_data=0xBAD,push_error=1)
        r=await self.cycle(pop=1)
        assert r['word1_valid'] and r['word1_error'] and not r['word1_data']
        r=await self.cycle()
        assert r['word0_addr']==0x3008 and r['word0_error']
        # Prediction clear observes the current token, then invalidates it.
        await self.cycle(clear=1,push_valid=1,push_addr=0x3010,push_data=0x13,pop=1)
        r=await self.cycle()
        assert not r['word0_valid'] and not r['word1_valid']
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


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def live_words(dut):
    await uvm_root().run_test('LiveWordsTest')
