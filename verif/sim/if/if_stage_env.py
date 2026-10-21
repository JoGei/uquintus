"""Component-local black-box IF stimulus and scoreboard."""
from collections import deque
import json
import os
import random

from cocotb.triggers import Timer
from pyuvm import uvm_test

from compressed_model import compressed

MASK = (1 << 32)-1


class IfStageTest(uvm_test):
    def build_phase(self):
        import cocotb
        self.dut = cocotb.top
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.c = self.params['ISA_C']
        self.expand_if = self.c and self.params['MUA_C_IMPL']==0 and self.params['MUA_C_DECOMPRESS_STAGE']==0
        self.depth = self.params['MUA_IF_BUFFER_WORDS']
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.words = {}
        self.errors = set()
        self.denied = set()
        self.deny_user = False
        self.live = {}
        self.complete = set()
        self.bus_owners = deque()
        self.response = None
        self.previous_bus = None
        self.pc = 0
        self.fetch_addr = 0
        self.running = True
        self.fault_hold = False
        self.epoch = 0
        self.credits = 0
        self.accepted = []
        self.granted = []
        self.delivered = []
        self.faults = []

    def memory(self,address):
        return self.words.get(address,0x00010001 if self.c else 0x00000013)

    def token(self):
        """Expected complete token, using bytes and retained access decisions."""
        base = self.pc&~3
        if base not in self.complete:
            return None
        data,error = self.live[base]
        if error:
            return dict(instr=0,original_instr=0,compressed=0,next_pc=self.pc,
                        exception_valid=1,exception_cause=1,exception_tval=self.pc)
        window = data.to_bytes(4,'little')
        offset = self.pc%4
        size = 2 if self.c and window[offset]&3!=3 else 4
        if offset+size>4:
            successor = (base+4)&MASK
            if successor not in self.complete:
                return None
            data,error = self.live[successor]
            if error:
                return dict(instr=0,original_instr=0,compressed=0,next_pc=self.pc,
                            exception_valid=1,exception_cause=1,exception_tval=(self.pc+2)&MASK)
            window += data.to_bytes(4,'little')
        original = int.from_bytes(window[offset:offset+size],'little')
        decoded = compressed(original) if size==2 and self.expand_if else None
        illegal = size==2 and self.expand_if and decoded is None
        return dict(instr=0 if illegal else decoded[1] if decoded else original,
                    original_instr=original,compressed=int(size==2),
                    next_pc=self.pc if illegal else (self.pc+size)&MASK,
                    exception_valid=int(illegal),exception_cause=2 if illegal else 0,
                    exception_tval=original if illegal else 0)

    async def cycle(self, grant=None, respond=None, **changes):
        i = dict(rst_n=1,boot_addr=0x1000,flush=0,redirect_valid=0,redirect_addr=0,
                 fetch_enable=1,request_permit=1,branch_pending=0,permit=1,ready=0,priv_m=1)
        i.update(changes)
        d = self.dut
        d.clk_i.value = 0
        for name,value in i.items():
            getattr(d,'rst_ni' if name=='rst_n' else name+'_i').value = value
        d.pmp_allow_i.value = 1
        d.imem_gnt_i.value = 0
        d.imem_rvalid_i.value = 0
        d.imem_rdata_i.value = self.rng.getrandbits(32)
        d.imem_err_i.value = 1
        await Timer(1,units='ns')
        query = int(d.pmp_valid_o.value),int(d.pmp_addr_o.value)
        allowed = query[1] not in self.denied and not (self.deny_user and not i['priv_m'])
        d.pmp_allow_i.value = int(allowed)
        req,addr = int(d.imem_req_o.value),int(d.imem_addr_o.value)
        if self.previous_bus and i['rst_n']:
            assert (req,addr)==(1,self.previous_bus),'presented OBI request changed before grant'
        gnt = int(bool(req and (self.rng.randrange(3)==0 if grant is None else grant)))
        returning = bool(self.response is not None and
                         (self.response[0]==0 if respond is None else respond))
        d.imem_gnt_i.value = gnt
        d.imem_rvalid_i.value = int(returning)
        if returning:
            _,_,_,data,error = self.response
            d.imem_rdata_i.value = data
            d.imem_err_i.value = error
        await Timer(1,units='ns')
        names = ('valid','pc','instr','original_instr','compressed','next_pc',
                 'exception_valid','exception_cause','exception_tval','misaligned',
                 'fetch_busy','pmp_valid','pmp_addr','pmp_size','pmp_priv_m')
        o = {name:int(getattr(d,name+'_o').value) for name in names}
        o.update(imem_req=req,imem_addr=addr)
        assert query==(o['pmp_valid'],o['pmp_addr']),'PMP decision fed back into query'
        invalidate = i['flush'] or i['redirect_valid']
        active = i['rst_n'] and not invalidate and self.running and not self.fault_hold
        misaligned = active and bool(self.pc % (2 if self.c else 4))
        assert o['misaligned']==int(bool(misaligned))
        if i['rst_n']:
            assert o['pc']==self.pc,(o,self.pc)
        expected = self.token() if active and not misaligned else None
        if o['valid']:
            assert active and i['permit'] and expected is not None,('invalid/early delivery',o,expected)
            for name,value in expected.items():
                assert o[name]==value,(name,o,expected)
        else:
            for name in ('instr','original_instr','compressed','exception_valid','exception_cause','exception_tval'):
                assert o[name]==0,(name,o)
        assert o['next_pc']==(expected['next_pc'] if o['valid'] else o['pc'])
        transfer = bool(o['valid'] and i['ready'])
        pop = transfer and not o['exception_valid'] and (self.pc&~3)!=(o['next_pc']&~3)
        if o['pmp_valid']:
            assert active and not misaligned and i['fetch_enable']
            assert self.params['MUA_BRANCH_PREDICTOR']!=0 or not i['branch_pending']
            assert not o['fetch_busy'] and self.credits-int(pop)<self.depth
            assert o['pmp_addr']==self.fetch_addr and o['pmp_size']==2
            assert o['pmp_priv_m']==i['priv_m']
            assert expected is None or not expected['exception_valid'],'fetch started past contained fault'
        else:
            assert not o['pmp_addr'] and not o['pmp_size'] and not o['pmp_priv_m']
        if not i['rst_n'] or invalidate:
            self.epoch += 1
            self.live.clear()
            self.complete.clear()
            self.credits = 0
            self.fault_hold = False
            if not req:
                self.bus_owners.clear()  # A private unpresented request is canceled.
            if not i['rst_n']:
                self.pc = i['boot_addr']
                self.fetch_addr = self.pc&~3
                self.running = True
                self.bus_owners.clear()
            elif i['redirect_valid']:
                self.pc = i['redirect_addr']
                self.fetch_addr = self.pc&~3
                self.running = True
            else:
                self.running = False
        else:
            if pop:
                del self.live[self.pc&~3]
                self.complete.remove(self.pc&~3)
                self.credits -= 1
            if transfer:
                if o['exception_valid']:
                    self.faults.append((self.pc,o['exception_cause'],o['exception_tval']))
                    self.fault_hold = True
                else:
                    self.delivered.append((self.pc,o['original_instr'],o['compressed'],o['instr']))
                    self.pc = o['next_pc']
            if o['pmp_valid']:
                address = o['pmp_addr']
                self.accepted.append(address)
                self.live[address] = self.memory(address),int(not allowed or address in self.errors)
                self.credits += 1
                self.fetch_addr = (address+4)&MASK
                if allowed:
                    self.bus_owners.append((self.epoch,address,self.memory(address),int(address in self.errors)))
                else:
                    self.complete.add(address)
        assert 0<=self.credits<=self.depth
        if not i['rst_n']:
            self.response = None
        else:
            if returning:
                _,epoch,address,_,_ = self.response
                if epoch==self.epoch:
                    self.complete.add(address)
                self.response = None
            elif self.response is not None and self.response[0]>0:
                delay,*payload = self.response
                self.response = (delay-1,*payload)
            if gnt:
                assert self.response is None,'multiple outstanding OBI responses'
                epoch,address,data,error = self.bus_owners.popleft()
                assert addr==address and addr&3==0
                self.granted.append(addr)
                self.response = self.rng.randrange(8),epoch,address,data,error
        self.previous_bus = addr if req and not gnt and i['rst_n'] else None
        d.clk_i.value = 1
        await Timer(1,units='ns')
        return o

    async def reset(self,pc=0x1000):
        await self.cycle(rst_n=0,boot_addr=pc)
        await self.cycle(fetch_enable=0)

    async def until(self,predicate,limit=2048,**changes):
        for _ in range(limit):
            o = await self.cycle(**changes)
            if predicate(o):
                return o
        raise AssertionError('IF progress timeout')

    def put(self,pc,values):
        """Install (raw value, original size) pairs into a byte-addressed image."""
        image = {}
        expected = []
        for value,size in values:
            result = compressed(value) if size==2 and self.expand_if else None
            assert not (size==2 and self.expand_if) or result is not None
            expected.append((pc,value,int(size==2),result[1] if result else value))
            for offset,byte in enumerate(value.to_bytes(size,'little')):
                image[(pc+offset)&MASK] = byte
            pc = (pc+size)&MASK
        for address in {address&~3 for address in image}:
            self.words[address] = sum(image.get((address+k)&MASK,0x13)<<(8*k) for k in range(4))
        return expected
