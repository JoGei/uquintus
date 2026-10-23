"""Real ifetch/FIFO/aligner: credits, streams, fault containment and killed drains."""
from collections import deque
import json
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'common'))
from if_aligner_model import MASK, select
from response_queue import ResponseQueue


class PrefetchTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        p = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.compressed = p['ISA_C']
        self.depth = p['MUA_IF_BUFFER_WORDS']
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.words = {}
        self.errors = set()
        self.buffer = deque()
        self.reserved = deque()
        self.responses = ResponseQueue()
        self.response = None
        self.previous_bus = None
        self.pc = 0
        self.fetch_addr = 0
        self.fault_hold = False
        self.accepted = []
        self.granted = []
        self.delivered = []
        self.faults = []
        self.high_water = 0

    def memory(self,address):
        return self.words.get(address,0x00010001 if self.compressed else 0x00000013)

    async def cycle(self, grant=None, respond=None, **changes):
        i = dict(rst_n=1,flush=0,boot_addr=0,redirect_addr=0,fetch_enable=1,
                 request_permit=1,req_access_fault=0,instr_ready=0)
        i.update(changes)
        d = self.dut
        d.clk_i.value = 0
        for name,value in i.items():
            getattr(d,'rst_ni' if name=='rst_n' else name+'_i').value = value
        d.imem_gnt_i.value = 0
        d.imem_rvalid_i.value = 0
        d.imem_rdata_i.value = self.rng.getrandbits(32)
        d.imem_err_i.value = 1  # Deliberate invalid-response error noise.
        returning = bool(self.response is not None and
                         (self.response[0]==0 if respond is None else respond))
        d.imem_rvalid_i.value = int(returning)
        if returning:
            _,address,data,error = self.response
            d.imem_rdata_i.value = data
            d.imem_err_i.value = error
        await Timer(1,units='ns')
        bus_req = int(d.imem_req_o.value)
        bus_addr = int(d.imem_addr_o.value)
        if self.previous_bus and i['rst_n']:
            assert (bus_req,bus_addr)==(1,self.previous_bus),'presented request changed before grant'
        gnt = int(bool(bus_req and (self.rng.randrange(3)==0 if grant is None else grant)))
        d.imem_gnt_i.value = gnt
        await Timer(1,units='ns')
        names = ('instr_valid','instr','pc','compressed','next_pc','exception_valid',
                 'exception_cause','exception_tval','fetch_accepted','fetch_addr',
                 'fetch_busy','push_fire','pop_fire','word0_valid','word0_addr',
                 'word1_valid','word1_addr','association_error')
        o = {name:int(getattr(d,name+'_o').value) for name in names}
        o.update(imem_req=bus_req,imem_addr=bus_addr)
        active = bool(i['rst_n'] and not i['flush'])
        if i['rst_n']:
            assert o['pc']==self.pc and o['fetch_addr']==self.fetch_addr
        assert not o['association_error']
        for index in range(2):
            valid = active and len(self.buffer)>index
            assert o[f'word{index}_valid']==int(valid)
            assert o[f'word{index}_addr']==(self.buffer[index][0] if valid else 0)
        candidate = dict(valid=int(active and not self.fault_hold),
                         pc=self.pc if i['rst_n'] else o['pc'])
        for index in range(2):
            present = len(self.buffer)>index
            _,data,error = self.buffer[index] if present else (0,0,0)
            candidate.update({f'word{index}_valid':int(active and present),
                              f'word{index}_data':data,f'word{index}_error':error})
        expected = select(candidate,self.compressed)
        for name in ('valid','instr','compressed','next_pc','exception_valid',
                     'exception_cause','exception_tval'):
            output_name = 'instr_valid' if name=='valid' else name
            # Reset/flush updates the fixture PC on the edge, not combinationally.
            assert o[output_name]==expected[name],(name,o,expected,list(self.buffer))
        pop = bool(expected['valid'] and i['instr_ready'] and expected['drop_word'])
        assert o['pop_fire']==int(pop)
        room = len(self.buffer)<self.depth or pop
        issue = bool(o['fetch_accepted'])
        if issue:
            assert active and not self.fault_hold and i['fetch_enable'] and room
        assert len(self.buffer)<=self.depth and len(self.reserved)<=3, 'unbounded prefetch storage'
        self.high_water = max(self.high_water,len(self.buffer))
        if not active:
            assert not o['push_fire'] and not o['pop_fire'] and not o['instr_valid']
            self.buffer.clear()
            self.reserved.clear()
            self.pc = i['boot_addr'] if not i['rst_n'] else i['redirect_addr']
            self.fetch_addr = self.pc&~3
            self.fault_hold = False
        else:
            if expected['valid'] and i['instr_ready']:
                if expected['exception_valid']:
                    self.faults.append((self.pc,expected['exception_tval']))
                    self.fault_hold = True
                else:
                    self.delivered.append((self.pc,expected['instr'],2 if expected['compressed'] else 4))
                    self.pc = expected['next_pc']
            if pop:
                self.buffer.popleft()
            if o['push_fire']:
                assert self.reserved,'completion without a surviving reservation'
                self.buffer.append(self.reserved.popleft())
            if issue:
                address = self.fetch_addr
                error = bool(i['req_access_fault'] or address in self.errors)
                self.reserved.append((address,0 if error else self.memory(address),int(error)))
                self.accepted.append(address)
                self.fetch_addr = (address+4)&MASK
        if not i['rst_n']:
            self.responses.clear()
        else:
            self.responses.advance(returning)
            if gnt:
                assert bus_addr&3==0
                self.granted.append(bus_addr)
                self.responses.issue(self.rng.randrange(8),bus_addr,self.memory(bus_addr),int(bus_addr in self.errors))
        self.response = self.responses.head
        self.previous_bus = bus_addr if bus_req and not gnt and i['rst_n'] else None
        d.clk_i.value = 1
        await Timer(1,units='ns')
        return o

    async def reset(self,pc=0x1000):
        await self.cycle(rst_n=0,boot_addr=pc)
        await self.cycle(fetch_enable=0)

    async def until(self,predicate,limit=1024,**changes):
        for _ in range(limit):
            o = await self.cycle(**changes)
            if predicate(o):
                return o
        raise AssertionError('prefetch progress timeout')


class StreamTest(PrefetchTest):
    async def run_phase(self):
        self.raise_objection()
        # Start near the address wrap; native and crossing words, reusable halves.
        start = 0xFFFFFFE0
        pc = start
        expected = []
        image = {}
        for index in range(256):
            size = 2 if self.compressed and index%3!=2 else 4
            value = self.rng.getrandbits(size*8)
            value = value&~3|self.rng.randrange(3) if size==2 else value|3
            expected.append((pc,value,size))
            for offset,byte in enumerate(value.to_bytes(size,'little')):
                image[(pc+offset)&MASK] = byte
            pc = (pc+size)&MASK
        for address in {address&~3 for address in image}:
            self.words[address] = sum(image.get((address+offset)&MASK,0)<<(8*offset) for offset in range(4))
        await self.reset(start)
        # Downstream stalled: FIFO fills, engine completion/skid slots retain excess.
        await self.until(lambda o:len(self.buffer)==self.depth)
        for _ in range(128):
            await self.cycle()
        assert self.accepted==[(start+4*k)&MASK for k in range(len(self.accepted))]
        for _ in range(32):
            o = await self.cycle()
            assert not o['fetch_accepted'] and len(self.buffer)==self.depth
        # A DE branch hold blocks new requests, but does not suppress old completions.
        accepted = len(self.accepted)
        for _ in range(16):
            await self.cycle(fetch_enable=0,instr_ready=int(self.rng.random()<0.7))
        assert len(self.accepted)==accepted
        for _ in range(8192):
            await self.cycle(instr_ready=int(self.rng.random()<0.7))
            assert self.delivered==expected[:len(self.delivered)],'instruction dropped, changed or repeated'
            if len(self.delivered)==len(expected):
                break
        else:
            raise AssertionError('instruction stream did not finish')
        assert self.high_water==self.depth and not self.faults
        assert len(self.accepted)==len(set(self.accepted)),'word fetched twice'
        self.drop_objection()


class FaultsTest(PrefetchTest):
    async def run_phase(self):
        self.raise_objection()
        # Local PMP denial must not reach OBI. The fixture supplies the core decision.
        await self.reset()
        await self.cycle(req_access_fault=1)
        await self.until(lambda o:bool(o['instr_valid']),fetch_enable=0)
        await self.cycle(fetch_enable=0,instr_ready=1)
        assert self.faults==[(0x1000,0x1000)] and not self.granted
        for _ in range(16):
            o = await self.cycle(instr_ready=1)
            assert not o['instr_valid'] and not o['fetch_accepted']
        # First word fault at upper-half PC does not wait for a successor.
        pc = 0x2002 if self.compressed else 0x2000
        self.errors.add(0x2000)
        await self.cycle(flush=1,redirect_addr=pc)
        await self.until(lambda o:bool(o['instr_valid']),instr_ready=0)
        await self.cycle(instr_ready=1,fetch_enable=0)
        assert self.faults[-1]==(pc,pc)
        if self.compressed:
            # A good low-half compressed instruction ignores an errored successor;
            # the crossing native instruction uses it and faults at address zero.
            self.words[0xFFFFFFFC] = 0x00930001
            self.errors.add(0)
            await self.cycle(flush=1,redirect_addr=0xFFFFFFFC)
            await self.until(lambda o:len(self.buffer)==self.depth)
            await self.cycle(instr_ready=1,fetch_enable=0)
            assert self.delivered[-1]==(0xFFFFFFFC,1,2)
            for _ in range(4):
                o = await self.cycle(fetch_enable=0)
                assert o['instr_valid'] and o['exception_tval']==0 and o['pc']==0xFFFFFFFE
            await self.cycle(instr_ready=1,fetch_enable=0)
            assert self.faults[-1]==(0xFFFFFFFE,0)
        self.drop_objection()


class RedirectsTest(PrefetchTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        target = 0x8002 if self.compressed else 0x8000
        for phase in ('private','ungranted','grant','response','response_edge','result','buffered'):
            origin = 0x1000+len(self.accepted)*0x100
            self.errors.add(origin)
            await self.cycle(flush=1,redirect_addr=origin,fetch_enable=0)
            await self.until(lambda o:not o['fetch_busy'],fetch_enable=0)
            await self.cycle(request_permit=int(phase!='private'),grant=0)
            if phase in ('response','response_edge','result','buffered'):
                await self.cycle(grant=1,respond=0,fetch_enable=0)
            if phase in ('result','buffered'):
                await self.cycle(respond=1,fetch_enable=0)
            if phase=='buffered':
                await self.cycle(fetch_enable=0)
                assert self.buffer
            await self.cycle(flush=1,redirect_addr=target,grant=int(phase=='grant'),
                             respond=int(phase=='response_edge'),fetch_enable=0)
            # Even a second flush cannot cancel a bus request before its grant.
            await self.cycle(flush=1,redirect_addr=target,grant=0,respond=0,fetch_enable=0)
            before = len(self.faults)
            delivered = len(self.delivered)
            accepted = len(self.accepted)
            await self.until(lambda o:len(self.delivered)>delivered,instr_ready=1)
            assert len(self.faults)==before,'discarded old-path error escaped'
            assert self.delivered[delivered][0]==target
            assert self.accepted[accepted]==target&~3
            target = (target+0x100)&MASK
        # Coordinated reset abandons a request; the memory model drops its response.
        await self.cycle(flush=1,redirect_addr=0xF000)
        await self.cycle(grant=0)
        await self.cycle(grant=0)
        await self.reset(0xA000)
        delivered = len(self.delivered)
        await self.until(lambda o:len(self.delivered)>delivered,instr_ready=1)
        assert self.delivered[delivered][0]==0xA000
        self.drop_objection()


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def stream(dut):
    await uvm_root().run_test('StreamTest')


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def faults(dut):
    await uvm_root().run_test('FaultsTest')


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def redirects(dut):
    await uvm_root().run_test('RedirectsTest')
