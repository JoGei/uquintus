"""Component-local black-box IF stimulus and scoreboard."""
from collections import deque
import json
import os
import random

from cocotb.triggers import Timer
from pyuvm import uvm_test

from compressed_model import compressed
from bpu_model import BpuModel

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
        self.predictor = BpuModel(self.params)
        self.replay = []
        self.held_prediction = None
        self.response_latency = None

    def memory(self,address):
        return self.words.get(address,0x00010001 if self.c else 0x00000013)

    def token(self):
        """Expected complete token, using bytes and retained access decisions."""
        base = self.pc&~3
        if self.replay:
            original = self.replay[0]
            short = self.c and original & 3 != 3
            fault = (base in self.denied or self.deny_user and not self.current_priv or
                     (self.c and self.pc & 2 and not short and ((base+4)&MASK) in self.denied))
            if fault:
                tval = self.pc if base in self.denied or self.deny_user and not self.current_priv else (self.pc+2)&MASK
                return dict(instr=0,original_instr=0,compressed=0,next_pc=self.pc,
                            exception_valid=1,exception_cause=1,exception_tval=tval)
            result = compressed(original) if short and self.expand_if else None
            illegal = short and self.expand_if and result is None
            return dict(instr=0 if illegal else result[1] if result else original,
                        original_instr=original,compressed=int(short),
                        next_pc=self.pc if illegal else (self.pc+(2 if short else 4))&MASK,
                        exception_valid=int(illegal),exception_cause=2 if illegal else 0,
                        exception_tval=original if illegal else 0)
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
                 fetch_enable=1,request_permit=1,branch_pending=0,permit=1,ready=0,priv_m=1,
                 predictor_invalidate=0,predictor_update_valid=0,predictor_update_pc=0,
                 predictor_update_control_flow=0,predictor_update_conditional=0,
                 predictor_update_taken=0,predictor_update_target=0)
        i.update(changes)
        d = self.dut
        d.clk_i.value = 0
        for name,value in i.items():
            getattr(d,'rst_ni' if name=='rst_n' else name+'_i').value = value
        self.current_priv = i['priv_m']
        # Replay permission can legitimately block a new continuation fetch.
        # Set it before observing that fetch's independent ordinary PMP query.
        replay_addr = (self.pc&~3) if self.replay else 0
        d.replay_pmp_allow_i.value = sum(int(((replay_addr+4*k)&MASK) not in self.denied and
            not (self.deny_user and not i['priv_m'])) << k for k in range(2))
        d.pmp_allow_i.value = 1
        d.imem_gnt_i.value = 0
        d.imem_rvalid_i.value = 0
        d.imem_rdata_i.value = self.rng.getrandbits(32)
        d.imem_err_i.value = 1
        returning = bool(self.response is not None and
                         (self.response[0]==0 if respond is None else respond))
        d.imem_rvalid_i.value = int(returning)
        if returning:
            _,_,_,data,error = self.response
            d.imem_rdata_i.value = data
            d.imem_err_i.value = error
        await Timer(1,units='ns')
        req,addr = int(d.imem_req_o.value),int(d.imem_addr_o.value)
        if self.previous_bus and i['rst_n']:
            assert (req,addr)==(1,self.previous_bus),'presented OBI request changed before grant'
        gnt = int(bool(req and (self.rng.randrange(3)==0 if grant is None else grant)))
        d.imem_gnt_i.value = gnt
        await Timer(1,units='ns')
        query = int(d.pmp_valid_o.value),int(d.pmp_addr_o.value)
        allowed = query[1] not in self.denied and not (self.deny_user and not i['priv_m'])
        d.pmp_allow_i.value = int(allowed)
        await Timer(1,units='ns')
        names = ('valid','pc','instr','original_instr','compressed','next_pc','predicted_next_pc',
                 'exception_valid','exception_cause','exception_tval','misaligned',
                 'fetch_busy','pmp_valid','pmp_addr','pmp_size','pmp_priv_m')
        o = {name:int(getattr(d,name+'_o').value) for name in names}
        o.update(imem_req=req,imem_addr=addr)
        assert query==(o['pmp_valid'],o['pmp_addr']),'PMP decision fed back into query'
        recover = bool(self.predictor.hwords and i['predictor_invalidate'])
        invalidate = i['flush'] or i['redirect_valid'] or recover
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
        prediction = self.predictor.lookup(self.pc, invalidate=i['predictor_invalidate'])
        predicted_pc = o['pc']
        if o['valid'] and not o['exception_valid']:
            predicted_pc = self.held_prediction if self.held_prediction is not None else (
                prediction['target'] if prediction['taken'] else expected['next_pc'])
        assert o['predicted_next_pc']==predicted_pc, (o,predicted_pc,prediction)
        transfer = bool(o['valid'] and i['ready'])
        prediction_redirect = transfer and not o['exception_valid'] and predicted_pc != o['next_pc']
        prefix = self.predictor.payload(self.pc) if prediction['taken'] else []
        replay_start = bool(prediction_redirect and prefix and prediction['target']==predicted_pc)
        pop = transfer and not self.replay and not o['exception_valid'] and (self.pc&~3)!=(o['next_pc']&~3)
        if o['pmp_valid']:
            assert active and not misaligned and i['fetch_enable']
            assert self.params['MUA_BRANCH_PREDICTOR']!=0 or not i['branch_pending']
            assert self.credits-int(pop)<self.depth+3
            assert o['pmp_addr']==self.fetch_addr and o['pmp_size']==2
            assert o['pmp_priv_m']==i['priv_m']
            assert not o['exception_valid'],'fetch started past visible contained fault'
        else:
            assert not o['pmp_addr'] and not o['pmp_size'] and not o['pmp_priv_m']
        if not i['rst_n'] or invalidate:
            self.epoch += 1
            self.replay = []
            self.live.clear()
            self.complete.clear()
            self.credits = 0
            self.fault_hold = False
            self.bus_owners = deque(list(self.bus_owners)[:1] if req else [])
            if not i['rst_n']:
                self.pc = i['boot_addr']
                self.fetch_addr = self.pc&~3
                self.running = True
                self.bus_owners.clear()
            elif i['redirect_valid']:
                self.pc = i['redirect_addr']
                self.fetch_addr = self.pc&~3
                self.running = True
            elif recover and not i['flush']:
                self.fetch_addr = self.pc&~3
            else:
                self.running = False
        else:
            if prediction_redirect:
                self.epoch += 1
                self.live.clear()
                self.complete.clear()
                self.credits = 0
                self.bus_owners = deque(list(self.bus_owners)[:1] if req else [])
                self.replay = prefix if replay_start else []
                continuation = predicted_pc + (sum(map(self.predictor.length,prefix)) if replay_start else 0)
                self.fetch_addr = (continuation&MASK)&~3
            elif transfer and self.replay:
                self.replay.pop(0)
            elif pop:
                del self.live[self.pc&~3]
                self.complete.remove(self.pc&~3)
                self.credits -= 1
            if transfer:
                if o['exception_valid']:
                    self.faults.append((self.pc,o['exception_cause'],o['exception_tval']))
                    self.fault_hold = True
                    self.replay = []
                else:
                    self.delivered.append((self.pc,o['original_instr'],o['compressed'],o['instr']))
                    self.pc = predicted_pc
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
        assert 0<=self.credits<=self.depth+3
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
                self.response = (self.rng.randrange(8) if self.response_latency is None else self.response_latency-1),epoch,address,data,error
        self.previous_bus = addr if req and not gnt and i['rst_n'] else None
        if not i['rst_n'] or invalidate or transfer:
            self.held_prediction = None
        elif o['valid'] and not i['ready'] and self.held_prediction is None and self.predictor.enabled:
            self.held_prediction = predicted_pc
        self.predictor.step(reset=not i['rst_n'], invalidate=i['predictor_invalidate'],
            valid=i['predictor_update_valid'],pc=i['predictor_update_pc'],
            control_flow=i['predictor_update_control_flow'],conditional=i['predictor_update_conditional'],
            taken=i['predictor_update_taken'],target=i['predictor_update_target'],
            stream_flush=invalidate,capture_valid=transfer and not o['exception_valid'],
            capture_pc=o['pc'],capture_instr=o['original_instr'])
        d.clk_i.value = 1
        await Timer(1,units='ns')
        return o

    async def fill(self, **changes):
        last, stable = -1, 0
        for _ in range(1024):
            o = await self.cycle(**changes)
            stable = stable+1 if len(self.accepted)==last else 0
            last = len(self.accepted)
            if self.credits>=self.depth and stable==32:
                return o
        raise AssertionError('prefetch did not reach bounded backpressure')

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
