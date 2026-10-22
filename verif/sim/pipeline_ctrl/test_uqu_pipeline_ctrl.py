"""Movement, age barriers, live interrupt arbitration and retained fence handshakes."""
import itertools
import json
import os
import random

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

from control_model import ControlModel, STAGES, OUTPUTS


class ControlTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.fencei = json.loads(os.environ['UQU_COMPONENT_PARAMS'])['ISA_ZIFENCEI']
        self.model = ControlModel(self.fencei)
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.checks = 0

    async def cycle(self, **changes):
        i = dict(rst_n=1,if_valid=0,de_admit=1,commit_enable=1,wb_effect_safe=0,
            de_redirect=0,de_redirect_addr=0x1234,wb_redirect_valid=0,
            wb_redirect_addr=0x8000,wb_next_pc=0x4004,de_pc=0x1002,resume_pc=0x2002,
            priv_m=1,mstatus=0,mie=0,mip=0,mtvec=0,irq_mask=0,
            drain_req=0,drain_target=0x9000,drain_ready=1,data_idle=1,fence_ack=0,fencei_ack=0)
        for name in STAGES:
            i.update({name+'_valid':0,name+'_complete':1,name+'_exception':0,name+'_system':0})
            if name!='de':
                i[name+'_serialize'] = 0
        i.update(changes)
        d = self.dut
        d.clk_i.value = 0
        for name,value in i.items():
            getattr(d,'rst_ni' if name=='rst_n' else name+'_i').value = value
        await Timer(1,units='ns')
        expected = self.model.evaluate(i)
        actual = {name:int(getattr(d,name+'_o').value) for name in OUTPUTS}
        assert actual==expected,({k:(actual[k],v) for k,v in expected.items() if actual[k]!=v},i,self.model.fence)
        self.model.advance(i,expected)
        d.clk_i.value = 1
        await Timer(1,units='ns')
        self.checks += 1
        return actual

    async def reset(self):
        await self.cycle(rst_n=0,if_valid=1,drain_req=1,mie=0x888,mip=0x888,mstatus=8)


class MovementTest(ControlTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        for occupied in itertools.product((0,1),repeat=4):
            for ready in itertools.product((0,1),repeat=4):
                for admit,commit,fetch in itertools.product((0,1),repeat=3):
                    i = dict(if_valid=fetch,de_admit=admit,commit_enable=commit)
                    for n,name in enumerate(STAGES):
                        i[name+'_valid'] = occupied[n]
                        i[name+'_complete'] = ready[n]
                    await self.cycle(**i)
        r = await self.cycle(de_valid=1,ex_valid=1,mem_valid=1,wb_valid=1,ex_complete=0)
        assert not r['de_fire'] and r['mem_fire'] and r['wb_fire']
        for stage in ('ex','mem','wb'):
            r = await self.cycle(de_valid=1,**{stage+'_valid':1,stage+'_serialize':1})
            assert not r['de_permit'] and r[stage+'_fire']
        # Taken DE branch consumes itself and never captures a wrong-path IF token.
        r = await self.cycle(if_valid=1,de_valid=1,de_redirect=1,mem_valid=1)
        assert r['de_fire'] and r['mem_fire'] and not r['if_fire'] and not r['de_flush']
        assert r['redirect_addr']==0x1234
        self.drop_objection()


class FaultsTest(ControlTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        for occupied in itertools.product((0,1),repeat=4):
            for faulty in itertools.product((0,1),repeat=4):
                for completed in (0,1):
                    i = dict(if_valid=1,wb_effect_safe=1)
                    for n,name in enumerate(STAGES):
                        i.update({name+'_valid':occupied[n],name+'_exception':faulty[n],name+'_complete':completed})
                    await self.cycle(**i)
        # A younger DE fault must neither cancel nor deny an older MEM request.
        r = await self.cycle(de_valid=1,de_exception=1,mem_valid=1)
        assert r['mem_fire'] and r['mem_request_permit'] and not r['mem_flush']
        # An unresolved older WB instruction blocks both reads and writes.
        r = await self.cycle(mem_valid=1,wb_valid=1,wb_complete=0,wb_effect_safe=0)
        assert not r['mem_request_permit']
        r = await self.cycle(mem_valid=1,wb_valid=1,wb_complete=0,wb_effect_safe=1)
        assert r['mem_request_permit'] and not r['wb_fire']
        r = await self.cycle(mem_valid=1,wb_valid=1,wb_exception=1,wb_effect_safe=1,commit_enable=0)
        assert not r['mem_request_permit'] and r['mem_flush']
        # Accepted WB recovery never cancels its own commitment permission.
        r = await self.cycle(wb_valid=1,wb_exception=1,wb_redirect_valid=1,
                             mem_valid=1,ex_valid=1,de_valid=1,de_redirect=1)
        assert r['wb_fire'] and not r['mem_fire'] and r['redirect_addr']==0x8000
        self.drop_objection()


class InterruptsTest(ControlTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        bits = [sum(flag<<cause for flag,cause in zip(flags,(3,7,11)))
                for flags in itertools.product((0,1),repeat=3)]
        for enable,pending in itertools.product(bits,repeat=2):
            for machine,global_enable,mask,de_fault in itertools.product((0,1),repeat=4):
                await self.cycle(mie=enable,mip=pending,mstatus=global_enable<<3,priv_m=machine,
                    irq_mask=mask,de_valid=1,de_exception=de_fault,mtvec=0xFFFFFFE5)
        for occupied in itertools.product((0,1),repeat=3):
            i = dict(mie=0x888,mip=0x888,mstatus=8,de_valid=1,de_exception=1)
            for n,name in enumerate(STAGES[1:]):
                i[name+'_valid'] = occupied[n]
            r = await self.cycle(**i)
            assert not r['de_fire'] and bool(r['trap_valid'])==(not any(occupied))
        r = await self.cycle(mie=0x888,mip=0x888,mstatus=8,mtvec=0xFFFFFFE5)
        assert r['trap_cause']==11 and r['redirect_addr']==0x10 and r['trap_pc']==0x2002
        r = await self.cycle(mie=0x888,mip=0x888,mstatus=8,drain_req=1,de_valid=1)
        assert r['drain_accept'] and not r['trap_valid'] and r['drain_pc']==0x1002
        r = await self.cycle(mie=0x888,mip=0x888,mstatus=8,drain_req=1,drain_ready=0)
        assert r['draining'] and not r['redirect_valid']
        # IRQ eligibility is live, including a vanished source or CSR disable.
        r = await self.cycle(mie=0x800,mip=0x800,mstatus=8,de_valid=1,ex_valid=1,ex_complete=0)
        assert not r['de_permit']
        r = await self.cycle(mie=0x800,mip=0,mstatus=8,de_valid=1,de_exception=1)
        assert r['de_fire'] and not r['trap_valid']
        self.drop_objection()


class FencesTest(ControlTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        for kind in ((6,7) if self.fencei else (6,)):
            i = dict(wb_valid=1,wb_system=kind,wb_serialize=1,de_valid=1)
            request = 'fence_req' if kind==6 else 'fencei_req'
            ack = 'fence_ack' if kind==6 else 'fencei_ack'
            for _ in range(5):
                r = await self.cycle(**i,data_idle=0)
                assert not r[request] and not r['wb_fire'] and not r['de_fire']
            r = await self.cycle(**i,commit_enable=0)
            assert r[request]
            for _ in range(8):
                r = await self.cycle(**i,data_idle=0,commit_enable=0,
                                     **{'fencei_ack' if kind==6 else 'fence_ack':1})
                assert r[request] and not r['wb_fire']
            r = await self.cycle(**i,commit_enable=0,**{ack:1})
            assert r[request] and not r['wb_fire']
            for _ in range(5):
                r = await self.cycle(**i,commit_enable=0,data_idle=0)
                assert not r[request] and not r['wb_fire']
            r = await self.cycle(**i,data_idle=0)
            assert r['wb_fire'] and bool(r['redirect_valid'])==(kind==7)
            await self.cycle()
            # A fault/reset cancels a pending request; no ack is reused by a new slot.
            await self.cycle(**i)
            r = await self.cycle(**dict(i,wb_exception=1))
            assert not r[request] and r['wb_fire']
            await self.reset()
            r = await self.cycle(**i,data_idle=0)
            assert not r[request] and not r['wb_fire']
            await self.reset()
        self.drop_objection()


class RandomizedTest(ControlTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        for index in range(8192):
            # Random combinations with an empty WB edge between vectors keep
            # synchronization state attached to one token rather than alias it.
            await self.cycle()
            i = dict(if_valid=self.rng.randrange(2),de_admit=self.rng.randrange(2),
                commit_enable=self.rng.randrange(2),wb_effect_safe=self.rng.randrange(2),
                de_redirect=self.rng.randrange(2),de_redirect_addr=self.rng.getrandbits(32),
                wb_redirect_valid=self.rng.randrange(2),wb_redirect_addr=self.rng.getrandbits(32),
                wb_next_pc=self.rng.getrandbits(32),de_pc=self.rng.getrandbits(32),
                resume_pc=self.rng.getrandbits(32),priv_m=self.rng.randrange(2),
                mstatus=self.rng.getrandbits(32),mie=self.rng.getrandbits(32),mip=self.rng.getrandbits(32),
                mtvec=self.rng.getrandbits(32),irq_mask=self.rng.randrange(2),
                drain_req=self.rng.randrange(2),drain_ready=self.rng.randrange(2),
                data_idle=self.rng.randrange(2),fence_ack=self.rng.randrange(2),fencei_ack=self.rng.randrange(2))
            for name in STAGES:
                for suffix in ('valid','complete','exception'):
                    i[name+'_'+suffix] = self.rng.randrange(2)
                i[name+'_system'] = self.rng.randrange(8)
                if name!='de':
                    i[name+'_serialize'] = self.rng.randrange(2)
            await self.cycle(**i)
        self.drop_objection()


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def movement(dut):
    await uvm_root().run_test('MovementTest')

@cocotb.test(timeout_time=1000,timeout_unit='us')
async def faults(dut):
    await uvm_root().run_test('FaultsTest')

@cocotb.test(timeout_time=1000,timeout_unit='us')
async def interrupts(dut):
    await uvm_root().run_test('InterruptsTest')

@cocotb.test(timeout_time=1000,timeout_unit='us')
async def fences(dut):
    await uvm_root().run_test('FencesTest')

@cocotb.test(timeout_time=1000,timeout_unit='us')
async def randomized(dut):
    await uvm_root().run_test('RandomizedTest')
