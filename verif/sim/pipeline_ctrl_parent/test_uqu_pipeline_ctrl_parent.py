"""Actual parent slots + MEM/LSU + WB/CSR under core controller arbitration."""
import json
import os
import random

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test


def packet(pc,**changes):
    p = dict(pc=pc,next_pc=pc+4,instr=0x00000013,data=pc,store_data=0,
             kind=0,system=0,serialize=0,branch=0,fault=0,cause=0,tval=0,
             lsu=0,we=0,csr_addr=0,csr_op=1)
    p.update(changes)
    return p


class ParentTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.fencei = json.loads(os.environ['UQU_COMPONENT_PARAMS'])['ISA_ZIFENCEI']
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.slots = [None]*4
        self.accepted = []
        self.retired = []
        self.faults = []
        self.traps = []
        self.drains = []
        self.redirects = []
        self.canceled = []
        self.writes = []
        self.memory = {}
        self.errors = set()
        self.accesses = []
        self.response = None
        self.held_request = None
        self.fence_acks = []

    async def cycle(self, token=None,grant=None,respond=None,**changes):
        i = dict(rst_n=1,in_valid=int(token is not None),ex_done=1,ex_fault=0,
            commit_enable=1,wb_effect_safe=1,de_admit=1,irq_software=0,irq_timer=0,
            irq_external=0,irq_mask=0,drain_req=0,drain_ready=1,fence_ack=1,fencei_ack=1)
        i.update(changes)
        d = self.dut
        d.clk_i.value = 0
        for name,value in i.items():
            getattr(d,'rst_ni' if name=='rst_n' else name+'_i').value = value
        for name,value in (token or packet(0)).items():
            getattr(d,'in_'+name+'_i').value = value
        d.dmem_gnt_i.value = 0
        d.dmem_rvalid_i.value = 0
        d.dmem_rdata_i.value = self.rng.getrandbits(32)
        d.dmem_err_i.value = 1
        await Timer(1,units='ns')
        bus = tuple(int(getattr(d,'dmem_'+name+'_o').value) for name in ('req','we','addr','wdata','be'))
        if self.held_request and i['rst_n']:
            assert bus==self.held_request,'presented data request changed before grant'
        if bus[0]:
            owner = self.slots[2]
            assert owner and owner['lsu'] and not owner['fault']
            assert (bus[1],bus[2])==(owner['we'],owner['data'])
            if owner['we']:
                assert bus[3]==owner['store_data']
        granted = bool(bus[0] and (self.rng.randrange(3)!=0 if grant is None else grant))
        returning = bool(self.response is not None and (self.response[0]==0 if respond is None else respond))
        d.dmem_gnt_i.value = int(granted)
        d.dmem_rvalid_i.value = int(returning)
        if returning:
            _,data,error = self.response
            d.dmem_rdata_i.value = data
            d.dmem_err_i.value = error
        await Timer(1,units='ns')
        names = ('occupied','advance','clear','in_ready','in_fire','de_pc','ex_pc','mem_pc','wb_pc',
                 'retire','exception_fire','exception_cause','exception_tval','write','write_data',
                 'trap_valid','trap_pc','trap_cause','drain_accept','drain_pc','redirect_valid',
                 'redirect_addr','fence_req','fencei_req','mstatus','mepc','mtvec','mie')
        o = {name:int(getattr(d,name+'_o').value) for name in names}
        o.update(dmem_req=bus[0],dmem_addr=bus[2])
        if i['rst_n']:
            assert o['occupied']==sum(int(p is not None)<<n for n,p in enumerate(self.slots))
            for n,name in enumerate(('de','ex','mem','wb')):
                if self.slots[n]:
                    assert o[name+'_pc']==self.slots[n]['pc']
        wb = self.slots[3]
        if o['advance']&8:
            assert wb and (o['retire'] ^ o['exception_fire'])
        if o['retire']:
            self.retired.append(wb['pc'])
            if wb['kind']==0 and not wb['we'] and wb['system']==0:
                assert o['write'] and o['write_data']==wb.get('expected_data',wb['data'])
            if wb['system'] in (6,7):
                assert not o['write'],'fence wrote a destination register'
        if o['write']:
            self.writes.append((wb['pc'],o['write_data']))
        if o['exception_fire']:
            assert not o['retire'] and not o['write'] and o['redirect_valid']
            self.faults.append((wb['pc'],o['exception_cause'],o['exception_tval']))
        if o['trap_valid']:
            assert o['occupied']&14==0 and not o['advance'] and not o['in_fire']
            self.traps.append((o['trap_pc'],o['trap_cause']))
        if o['drain_accept']:
            assert o['occupied']&14==0 and not o['trap_valid']
            self.drains.append(o['drain_pc'])
        if o['redirect_valid']:
            self.redirects.append(o['redirect_addr'])
        if (o['fence_req'] and i['fence_ack']) or (o['fencei_req'] and i['fencei_ack']):
            self.fence_acks.append(wb['pc'])
        if not i['rst_n']:
            self.slots = [None]*4
            self.response = None
        else:
            # Memory responses are captured even when the WB slot is stalled.
            if returning:
                assert self.slots[2] is not None
                self.slots[2]['expected_data'] = self.response[1]
                self.response = None
            elif self.response is not None and self.response[0]>0:
                delay,data,error = self.response
                self.response = delay-1,data,error
            if granted:
                assert self.response is None
                _,write,address,data,be = bus
                assert be==15 and address%4==0
                error = address in self.errors
                self.accesses.append((address,write))
                if write and not error:
                    self.memory[address] = data
                self.response = self.rng.randrange(6),self.memory.get(address,0xCAFE0000|address),int(error)
            previous = self.slots[:]
            for n in range(4):
                if n<3 and o['clear']&(1<<n):
                    if previous[n]:
                        self.canceled.append(previous[n]['pc'])
                    self.slots[n] = None
                elif previous[n] is None or o['advance']&(1<<n):
                    incoming = bool(o['in_fire']) if n==0 else bool(o['advance']&(1<<(n-1)))
                    self.slots[n] = dict(token if n==0 else previous[n-1]) if incoming else None
            if o['in_fire']:
                self.accepted.append(token['pc'])
        self.held_request = bus if bus[0] and not granted and i['rst_n'] else None
        d.clk_i.value = 1
        await Timer(1,units='ns')
        return o

    async def reset(self):
        await self.cycle(rst_n=0)
        await self.cycle()

    async def until(self,predicate,**changes):
        for _ in range(4096):
            o = await self.cycle(**changes)
            if predicate(o):
                return o
        raise AssertionError('controller parent progress timeout')

    async def send(self,p,**changes):
        for _ in range(4096):
            o = await self.cycle(token=p,**changes)
            if o['in_fire']:
                return o
        raise AssertionError('controller parent issue timeout')

    async def csr(self,pc,address,value):
        completed = self.retired.count(pc)
        await self.send(packet(pc,kind=1,serialize=1,csr_addr=address,data=value))
        await self.until(lambda o:self.retired.count(pc)>completed)
        return await self.cycle()

    async def setup_irq(self):
        await self.csr(0x1000,0x305,0x4001)
        await self.csr(0x1004,0x304,0x888)
        await self.csr(0x1008,0x300,8)


class FlowTest(ParentTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        tokens = []
        for index in range(128):
            p = packet(0x1000+4*index,data=self.rng.getrandbits(32))
            if index%5==1:
                p.update(lsu=1,data=0x2000+4*(index%8),we=int(index%3==0),store_data=self.rng.getrandbits(32))
            tokens.append(p)
        index = 0
        for _ in range(8192):
            o = await self.cycle(token=tokens[index] if index<len(tokens) else None,
                ex_done=int(self.rng.random()<0.7),commit_enable=int(self.rng.random()<0.7),
                wb_effect_safe=int(self.rng.random()<0.7))
            index += o['in_fire']
            assert self.retired==[p['pc'] for p in tokens[:len(self.retired)]]
            if len(self.retired)==len(tokens):
                break
        else:
            raise AssertionError('randomized pipeline did not drain')
        assert not self.faults and not self.canceled
        # Unproven older WB holds a MEM load privately; proof may release the bus
        # while WB itself is still held, then responses survive that hold.
        await self.send(packet(0x3000),commit_enable=0,wb_effect_safe=0)
        await self.send(packet(0x3004,lsu=1,data=0x5000),commit_enable=0,wb_effect_safe=0)
        await self.until(lambda o:o['occupied']&12==12,commit_enable=0,wb_effect_safe=0)
        for _ in range(8):
            o = await self.cycle(commit_enable=0,wb_effect_safe=0)
            assert not o['dmem_req']
        await self.until(lambda o:bool(o['dmem_req']),commit_enable=0,wb_effect_safe=1)
        await self.until(lambda o:self.response is None,commit_enable=0)
        assert 0x3000 not in self.retired
        await self.until(lambda o:0x3004 in self.retired)
        self.drop_objection()


class FaultsTest(ParentTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        # CSR access failure is discovered by the real WB CSR unit.
        await self.send(packet(0x1000,kind=1,serialize=1,csr_addr=0xFFF,instr=0xFFF010F3))
        await self.send(packet(0x1004,lsu=1,we=1,data=0x5000,store_data=0xBAD))
        await self.until(lambda o:bool(self.faults))
        assert self.faults==[(0x1000,2,0xFFF010F3)] and not self.accesses
        assert 0x1004 in self.canceled and 0x1004 not in self.retired
        # Real MEM access fault with older WB stalled and younger EX held.
        await self.reset()
        self.errors.add(0x6000)
        await self.send(packet(0x2000),commit_enable=0)
        await self.send(packet(0x2004,lsu=1,data=0x6000),commit_enable=0,respond=0)
        await self.until(lambda o:o['occupied']&12==12,commit_enable=0,respond=0)
        await self.send(packet(0x2008),commit_enable=0,ex_done=0,respond=0)
        await self.send(packet(0x200C,lsu=1,we=1,data=0x6004,store_data=0xBAD),
                        commit_enable=0,ex_done=0,respond=0)
        await self.until(lambda o:self.response is not None,commit_enable=0,ex_done=0,respond=0)
        await self.cycle(commit_enable=0,ex_done=0,respond=1)
        o = await self.until(lambda o:o['clear']&3==3,commit_enable=0,ex_done=0)
        assert o['occupied']&12==12 and not self.faults[-1][0]==0x2004
        await self.until(lambda o:any(p==0x2004 for p,_,_ in self.faults))
        assert self.faults[-1]==(0x2004,5,0x6000)
        assert 0x2000 in self.retired and 0x2008 in self.canceled and 0x200C in self.canceled
        assert (0x6004,1) not in self.accesses
        self.drop_objection()


class InterruptsTest(ParentTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        await self.setup_irq()
        await self.send(packet(0x2000),ex_done=0)
        await self.send(packet(0x2004,fault=1,cause=11),ex_done=0)
        for _ in range(8):
            o = await self.cycle(irq_external=1,ex_done=0)
            assert not o['advance']&1 and not o['trap_valid']
        await self.until(lambda o:bool(self.traps),irq_external=1)
        assert self.traps==[(0x2004,11)] and not self.faults
        assert self.redirects[-1]==0x402C and 0x2000 in self.retired
        o = await self.cycle(irq_external=1)
        assert o['mepc']==0x2004 and not o['mstatus']&8
        # Older CSR disables the pending interrupt before entry: preserve DE's
        # fault and resume its ordinary WB exception path after re-evaluation.
        await self.reset()
        await self.setup_irq()
        await self.send(packet(0x3000,kind=1,serialize=1,csr_addr=0x304,data=0),ex_done=0)
        await self.send(packet(0x3004,fault=1,cause=11),ex_done=0)
        traps = len(self.traps)
        for _ in range(6):
            await self.cycle(irq_external=1,ex_done=0)
        await self.until(lambda o:any(p==0x3004 for p,_,_ in self.faults),irq_external=1)
        assert len(self.traps)==traps and self.faults[-1]==(0x3004,11,0)
        # MRET restores MIE then IRQ entry precedes a faulting target instruction.
        await self.reset()
        await self.csr(0x1000,0x305,0x4001)
        await self.csr(0x1004,0x304,0x800)
        await self.csr(0x1008,0x341,0x7000)
        await self.csr(0x100C,0x300,0x1880)
        await self.send(packet(0x4000,kind=2,system=3,serialize=1,next_pc=0x7000))
        await self.send(packet(0x7000,fault=1,cause=2),irq_external=1)
        count = len(self.traps)
        await self.until(lambda o:len(self.traps)>count,irq_external=1)
        assert self.traps[-1]==(0x7000,11) and not any(p==0x7000 for p,_,_ in self.faults)
        # The normalized higher-priority drain endpoint wins a boundary over IRQ.
        await self.reset()
        await self.setup_irq()
        o = await self.cycle(irq_external=1,drain_req=1)
        assert o['drain_accept'] and not o['trap_valid']
        # An older synchronous fault enters normally before the generic halt
        # endpoint, which then saves the post-trap handler PC.
        await self.reset()
        await self.csr(0x1000,0x305,0x4001)
        await self.send(packet(0x5000,fault=1,cause=11))
        await self.cycle()
        before = len(self.faults)
        await self.until(lambda o:len(self.faults)>before,drain_req=1)
        assert self.faults[-1]==(0x5000,11,0)
        o = await self.cycle(drain_req=1)
        assert o['drain_accept'] and o['drain_pc']==0x4000 and o['mepc']==0x5000
        self.drop_objection()


class FencesTest(ParentTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        for kind in ((6,7) if self.fencei else (6,)):
            pc = 0x4000+kind*0x100
            await self.send(packet(pc,system=kind,serialize=1),fence_ack=0,fencei_ack=0)
            await self.send(packet(pc+4,lsu=1,we=1,data=0x8000+kind*4,store_data=kind),fence_ack=0,fencei_ack=0)
            request = 'fence_req' if kind==6 else 'fencei_req'
            ack = 'fence_ack' if kind==6 else 'fencei_ack'
            await self.until(lambda o:o[request],fence_ack=0,fencei_ack=0)
            for _ in range(8):
                o = await self.cycle(commit_enable=0,fence_ack=0,fencei_ack=0)
                assert o[request] and not o['dmem_req']
            await self.cycle(commit_enable=0,**{ack:1})
            for _ in range(6):
                o = await self.cycle(commit_enable=0,fence_ack=0,fencei_ack=0)
                assert not o[request] and pc not in self.retired
            await self.until(lambda o:pc in self.retired,fence_ack=0,fencei_ack=0)
            assert self.fence_acks.count(pc)==1 and self.retired.count(pc)==1
            if kind==6:
                await self.until(lambda o:pc+4 in self.retired)
            else:
                assert self.redirects[-1]==pc+4 and pc+4 in self.canceled
        self.drop_objection()


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def flow(dut):
    await uvm_root().run_test('FlowTest')

@cocotb.test(timeout_time=1000,timeout_unit='us')
async def faults(dut):
    await uvm_root().run_test('FaultsTest')

@cocotb.test(timeout_time=1000,timeout_unit='us')
async def interrupts(dut):
    await uvm_root().run_test('InterruptsTest')

@cocotb.test(timeout_time=1000,timeout_unit='us')
async def fences(dut):
    await uvm_root().run_test('FencesTest')
