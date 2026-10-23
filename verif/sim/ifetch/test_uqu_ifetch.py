"""Independent word transactions, OBI timing, retained results and killed drains."""
from collections import deque
import os
import json
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from ifetch_model import MASK, completion, word_address
from response_queue import ResponseQueue


class IfetchTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.bypass = bool(json.loads(os.environ["UQU_COMPONENT_PARAMS"])["MUA_REDIRECT_BYPASS"] & 4)
        self.previous = None
        self.count = 0

    async def cycle(self, **changes):
        i = dict(rst_n=1, flush=0, clear=0, replace=0, req_valid=0, req_addr=0, req_access_fault=0,
                 request_permit=1, res_ready=0, imem_gnt=0, imem_rvalid=0,
                 imem_rdata=0, imem_err=1)
        i.update(changes)
        d = self.dut
        d.clk_i.value = 0
        for name, value in i.items():
            getattr(d, 'rst_ni' if name == 'rst_n' else name+'_i').value = value
        await Timer(1, units='ns')
        o = {name:int(getattr(d,name+'_o').value) for name in
             ('req_ready','busy','res_valid','res_addr','res_data','res_error','imem_req','imem_addr')}
        if not o['res_valid']:
            assert (o['res_addr'],o['res_data'],o['res_error']) == (0,0,0)
        if o['imem_req']:
            assert o['busy'] or i['req_valid']
            assert o['imem_addr'] & 3 == 0
        if o['res_valid']:
            assert o['busy']
        if self.previous:
            old_i, old_o = self.previous
            if old_o['imem_req'] and not old_i['imem_gnt'] and i['rst_n']:
                assert o['imem_req'] and o['imem_addr'] == old_o['imem_addr'], 'request withdrawn/replaced'
            if old_o['res_valid'] and not old_i['res_ready'] and not old_i['clear'] and i['rst_n'] and not i['flush']:
                assert o['res_valid'] and self.result(o) == self.result(old_o), 'retained result changed'
        # Request admission must not borrow a live response credit. Probe both
        # values before the edge while keeping native/control inputs unchanged.
        d.imem_rvalid_i.value = 1-i['imem_rvalid']
        await Timer(1, units='ns')
        assert tuple(int(getattr(d,n+'_o').value) for n in ('imem_req','imem_addr','req_ready')) == \
            tuple(o[n] for n in ('imem_req','imem_addr','req_ready')), 'response-to-request dependency'
        d.imem_rvalid_i.value = i['imem_rvalid']
        await Timer(1, units='ns')
        self.previous = i,o
        d.clk_i.value = 1
        await Timer(1, units='ns')
        return o

    @staticmethod
    def result(o):
        return o['res_addr'],o['res_data'],o['res_error']

    async def reset(self):
        r = await self.cycle(rst_n=0)
        assert not any(value for name,value in r.items() if name!='imem_addr')
        r = await self.cycle()
        assert r['req_ready'] and not r['busy']

    async def accept(self, address, denied=False, permit=True, grant_high=False):
        r = await self.cycle(req_valid=1, req_addr=address, req_access_fault=int(denied),
                             request_permit=int(permit), imem_gnt=int(grant_high))
        assert r['req_ready'] and not r['busy'] and not r['res_valid']
        assert r['imem_req'] == (permit and not denied)
        if r['imem_req']:
            assert r['imem_addr'] == word_address(address)
        return bool(r['imem_req'] and grant_high)

    async def grant(self, address, delay=0, flush=False):
        for index in range(delay+1):
            r = await self.cycle(imem_gnt=int(index==delay), flush=int(flush),
                req_addr=address ^ MASK, req_access_fault=1, request_permit=0)
            assert r['imem_req'] and r['imem_addr'] == word_address(address)
            assert not r['res_valid']

    async def respond(self, data, error=False, delay=0, flush=False):
        for _ in range(delay):
            r = await self.cycle(imem_rdata=self.rng.getrandbits(32), imem_err=self.rng.randrange(2))
            assert r['busy'] and not r['res_valid'] and not r['imem_req']
        r = await self.cycle(imem_rvalid=1, imem_rdata=data, imem_err=int(error), flush=int(flush))
        if r['res_valid']:
            assert self.bypass and not flush
            assert (r['res_data'],r['res_error']) == (0 if error else data,int(error))
        assert r['busy'] and not r['imem_req']

    async def consume(self, expected, hold=0):
        for index in range(hold+1):
            r = await self.cycle(res_ready=int(index==hold),
                req_addr=0xBAD00000, req_access_fault=1, imem_rdata=MASK,
                imem_err=1, request_permit=0)
            assert r['res_valid'] and self.result(r) == expected, (r,expected)
        r = await self.cycle()
        assert r['req_ready'] and not r['busy'] and not r['res_valid']
        self.count += 1

    async def operation(self, address, data=0x12345678, denied=False, error=False,
                        grant_delay=0, response_delay=0, hold=0, permit_wait=0, grant_high=False):
        granted = await self.accept(address, denied, not permit_wait, grant_high)
        if not denied:
            if permit_wait:
                for _ in range(permit_wait):
                    r = await self.cycle(request_permit=0, imem_gnt=1, req_access_fault=1)
                    assert r['busy'] and not r['imem_req'] and not r['res_valid']
                r = await self.cycle(request_permit=1, req_access_fault=1)
                assert r['imem_req'] and r['imem_addr'] == word_address(address) and not r['res_valid']
            if not granted:
                await self.grant(address, grant_delay)
            await self.respond(data, error, response_delay)
        await self.consume(completion(address,data,denied,error),hold)


class DirectedTest(IfetchTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        for address in (0,1,2,3,0x1000,0x1002,0xFFFFFFFC,0xFFFFFFFF):
            for denied,error in ((False,False),(False,True),(True,False),(True,True)):
                for permit_wait in (0,3):
                    await self.operation(address, self.rng.getrandbits(32), denied,error,
                        grant_delay=3,response_delay=4,hold=3,permit_wait=permit_wait,grant_high=True)
        # Unsupported bus activity in idle must not manufacture a completion.
        r = await self.cycle(imem_gnt=1, imem_rvalid=1, imem_rdata=MASK)
        assert r['req_ready'] and not r['res_valid']
        r = await self.cycle()
        assert r['req_ready'] and not r['res_valid']
        self.logger.info('%d directed word transactions checked',self.count)
        self.drop_objection()


class RandomizedTest(IfetchTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        for _ in range(512):
            await self.operation(self.rng.getrandbits(32),self.rng.getrandbits(32),
                denied=self.rng.randrange(5)==0,error=bool(self.rng.randrange(2)),
                grant_delay=self.rng.randrange(9),response_delay=self.rng.randrange(12),
                hold=self.rng.randrange(9),permit_wait=self.rng.randrange(4),
                grant_high=bool(self.rng.randrange(2)))
        self.logger.info('%d randomized word transactions checked',self.count)
        self.drop_objection()


class StreamingTest(IfetchTest):
    async def stream(self, count, random_wait=False):
        await self.reset()
        expected, bus = deque(), deque()
        pending = ResponseQueue()
        accepted = 0
        received = 0
        accepts, grants, results = [], [], []
        for tick in range(100000):
            address = (0x1000+accepted*4) & MASK
            denied = random_wait and accepted%17==3
            returning = bool(pending and pending.head[0]==0)
            data = pending.head[2] if returning else MASK
            error = pending.head[3] if returning else 1
            ready = int(not random_wait or self.rng.random()<0.6)
            grant = int(not random_wait or self.rng.random()<0.7)
            r = await self.cycle(req_valid=int(accepted<count), req_addr=address,
                req_access_fault=int(denied), request_permit=int(not random_wait or self.rng.random()<0.7),
                res_ready=ready, imem_gnt=grant, imem_rvalid=int(returning),
                imem_rdata=data, imem_err=error)
            if r['res_valid'] and ready:
                assert expected and self.result(r)==expected.popleft(), (r,expected)
                received += 1
                results.append(tick)
            if accepted<count and r['req_ready']:
                value = address ^ 0xa5c3f00d
                fault = random_wait and accepted%13==5
                expected.append(completion(address,value,denied,fault))
                if not denied:
                    bus.append((address,value,int(fault)))
                accepted += 1
                accepts.append(tick)
            pending.advance(returning)
            if r['imem_req'] and grant:
                assert bus, 'bus request without native acceptance / denied request leaked'
                addr,value,fault = bus.popleft()
                assert r['imem_addr']==addr, (r,addr)
                pending.issue(self.rng.randrange(9) if random_wait else 0, addr,value,fault)
                grants.append(tick)
            assert len(expected)<=3, 'unbounded accepted work'
            if received==count:
                assert not expected and not bus and not pending
                break
        else:
            raise AssertionError('stream did not drain')
        if not random_wait:
            assert grants[0] == accepts[0] == 0
            assert results[0] == (1 if self.bypass else 2)
            for name, events in [('accept', accepts), ('grant', grants), ('result', results)]:
                assert len(events)==count and all(b-a==1 for a,b in zip(events,events[1:])), (name,events)

    async def run_phase(self):
        self.raise_objection()
        await self.stream(256)
        await self.stream(1024, random_wait=True)
        self.drop_objection()


class OutstandingTest(IfetchTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        # Issue B before A responds. Saturation must block C even if an
        # incoming response merely moves a reservation into result storage.
        for address in (0x1000,0x1004):
            r=await self.cycle(req_valid=1,req_addr=address,imem_gnt=1)
            assert r['req_ready'] and r['imem_req'] and r['imem_addr']==address
        r=await self.cycle(req_valid=1,req_addr=0x1008,imem_gnt=1)
        assert r['req_ready'] and not r['imem_req']
        r=await self.cycle(imem_rvalid=1,imem_rdata=0xAAAAAAAA,imem_err=0)
        assert not r['imem_req']
        r=await self.cycle(res_ready=1,imem_gnt=1)
        assert r['imem_req'] and self.result(r)==completion(0x1000,0xAAAAAAAA)
        # B and C remain outstanding across repeated redirects. The new
        # target is privately accepted, but must not overbook their slots.
        r=await self.cycle(flush=1,replace=1,req_valid=1,req_addr=0x8000,imem_gnt=1)
        assert r['req_ready'] and not r['imem_req']
        await self.cycle(flush=1,replace=1,req_valid=1,req_addr=0x9000)
        for _ in range(4):
            r=await self.cycle(imem_gnt=1)
            assert not r['imem_req'] and not r['res_valid']
        r=await self.cycle(imem_rvalid=1,imem_rdata=MASK,imem_err=1)
        assert not r['imem_req'] and not r['res_valid']
        r=await self.cycle(imem_gnt=1)
        assert r['imem_req'] and r['imem_addr']==0x9000
        r=await self.cycle(imem_rvalid=1,imem_rdata=MASK,imem_err=1)
        assert not r['res_valid']
        await self.respond(0xCAFEBABE)
        await self.consume(completion(0x9000,0xCAFEBABE))
        self.drop_objection()


class StressTest(IfetchTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        expected, owners = deque(), deque()
        pending = ResponseQueue()
        serial = 0
        peak = 0
        for tick in range(6000):
            active = tick<5000
            invalidate = active and self.rng.random()<0.08
            local = invalidate and bool(self.rng.randrange(2))
            replace = invalidate and bool(self.rng.randrange(2))
            address = 0x1000+4*serial
            denied = self.rng.random()<0.1
            returning = bool(pending and pending.head[0]==0 and self.rng.random()<0.8)
            head = pending.head if pending else (0,0,0,0)
            grant = int(self.rng.random()<0.7)
            ready = int(self.rng.random()<0.7)
            valid = active and self.rng.random()<0.85
            r=await self.cycle(flush=int(invalidate and not local),clear=int(local),replace=int(replace),
                req_valid=int(valid),req_addr=address,req_access_fault=int(denied),
                request_permit=int(self.rng.random()<0.8),imem_gnt=grant,
                imem_rvalid=int(returning),imem_rdata=head[2],imem_err=head[3],res_ready=ready)
            if r['res_valid']:
                assert expected and self.result(r)==expected[0], (tick,r,list(expected))
                if ready: expected.popleft()
            if invalidate:
                expected.clear()
                # Preserve an old presented address even if permission/capacity
                # opened immediately after the preceding sampling edge.
                owners=deque(list(owners)[:1] if r['imem_req'] and owners and owners[0][0]==r['imem_addr'] else [])
            if valid and r['req_ready']:
                data=address^0xA5C3F00D
                error=bool(serial%11==3)
                expected.append(completion(address,data,denied,error))
                if not denied: owners.append((address,data,int(error)))
                serial+=1
            pending.advance(returning)
            if r['imem_req'] and grant:
                assert owners, (tick,r)
                addr,data,error=owners.popleft()
                assert r['imem_addr']==addr, (tick,r,addr)
                pending.issue(self.rng.randrange(12),addr,data,error)
            peak=max(peak,len(pending))
            assert len(expected)<=3
            if not active and not r['busy']:
                assert not expected and not owners and not pending
                break
        else:
            raise AssertionError('randomized redirected stream did not drain')
        assert peak==2
        self.logger.info('%d native words accepted, peak %d outstanding',serial,peak)
        self.drop_objection()


class PipelinedFlushTest(IfetchTest):
    async def run_phase(self):
        self.raise_objection()
        for phase in ('pending','return','held_request','full_results','denied_queued','reset'):
            await self.reset()
            r = await self.cycle(req_valid=1,req_addr=0x1000,imem_gnt=1)
            assert r['imem_req'] and r['imem_addr']==0x1000
            r = await self.cycle(req_valid=1,req_addr=0x1004,imem_gnt=1,
                                 imem_rvalid=1,imem_rdata=0xaaaaaaaa,imem_err=0)
            assert r['imem_req'] and r['imem_addr']==0x1004
            r = await self.cycle(req_valid=1,req_addr=0x1008,
                req_access_fault=int(phase=='denied_queued'), imem_gnt=1)
            assert not r['imem_req']
            # A is registered, B is outstanding, C is queued: all three
            # logical credits are occupied. Exercise every flush ownership.
            if phase=='pending':
                r = await self.cycle(flush=1)
                assert not r['imem_req'] and not r['res_valid']
                r = await self.cycle(req_valid=1,req_addr=0x2000)
                assert r['req_ready']
                r = await self.cycle(imem_rvalid=1,imem_rdata=MASK,imem_err=1,imem_gnt=1)
                assert r['imem_req'] and r['imem_addr']==0x2000 and not r['res_valid']
                await self.respond(0x11223344)
                await self.consume(completion(0x2000,0x11223344))
            elif phase in ('return','denied_queued'):
                r = await self.cycle(flush=1,imem_rvalid=1,imem_err=1,imem_gnt=1)
                assert not r['imem_req'] and not r['res_valid']
            elif phase=='held_request':
                r = await self.cycle(imem_rvalid=1,imem_rdata=0xbbbbbbbb,imem_err=0,res_ready=1)
                assert r['imem_req'] and r['imem_addr']==0x1008
                r = await self.cycle(flush=1)
                assert r['imem_req'] and r['imem_addr']==0x1008 and not r['res_valid']
                await self.grant(0x1008,flush=True)
                await self.respond(MASK,error=True)
            elif phase=='full_results':
                r = await self.cycle(imem_rvalid=1,imem_rdata=0xbbbbbbbb,imem_err=0,imem_gnt=1)
                assert not r['imem_req'], 'unreserved request with both result slots occupied'
                r = await self.cycle(flush=1)
                assert not r['imem_req'] and not r['res_valid']
            else:
                await self.reset()
            await self.operation(0x3000, data=0x55aa55aa)
        self.drop_objection()


class ClearTest(IfetchTest):
    async def run_phase(self):
        self.raise_objection()
        for simultaneous,ready in ((False,0),(False,1),(True,0),(True,1)):
            await self.reset()
            await self.cycle(req_valid=1,req_addr=0x1000,imem_gnt=1)
            await self.cycle(req_valid=1,req_addr=0x1004,imem_gnt=1,
                             imem_rvalid=1,imem_rdata=0xAAAAAAAA,imem_err=0)
            # The old registered head must remain visible while it requests
            # a synchronous clear, including a concurrent later bus response.
            r=await self.cycle(clear=1,res_ready=ready,req_valid=1,req_addr=0xDEAD0000,
                               imem_gnt=1,imem_rvalid=int(simultaneous),
                               imem_rdata=0xBBBBBBBB,imem_err=1)
            assert r['res_valid'] and self.result(r)==completion(0x1000,0xAAAAAAAA)
            assert not r['req_ready'] and not r['imem_req']
            if not simultaneous:
                await self.cycle(imem_rvalid=1,imem_rdata=MASK,imem_err=1)
            r=await self.cycle()
            assert not r['res_valid'] and not r['busy']
            await self.operation(0x2000,data=0x12345678)
        # A clear must also preserve an already presented, ungranted request.
        await self.accept(0x3000)
        r=await self.cycle(clear=1)
        assert r['imem_req'] and r['imem_addr']==0x3000
        await self.grant(0x3000,delay=3)
        await self.respond(MASK,error=True)
        r=await self.cycle()
        assert not r['res_valid'] and not r['busy']
        self.drop_objection()


class ReplaceTest(IfetchTest):
    async def run_phase(self):
        self.raise_objection()
        for local in (False,True):
            for phase in ('idle','private','ungranted','grant','pending','response','result','full'):
                for denied,error in ((False,False),(False,True),(True,False)):
                    await self.reset()
                    pending = deque()
                    if phase != 'idle':
                        await self.accept(0x1000,permit=phase!='private',
                                          grant_high=phase in ('pending','response','result','full'))
                        if phase in ('pending','response'):
                            pending.append(0x1000)
                        elif phase in ('result','full'):
                            await self.respond(0x11111111)
                            if phase == 'full':
                                await self.cycle(req_valid=1,req_addr=0x1004,imem_gnt=1)
                                await self.cycle(imem_rvalid=1,imem_rdata=0x22222222,imem_err=0)
                    target = 0x8000
                    r = await self.cycle(flush=int(not local),clear=int(local),replace=1,
                        req_valid=1,req_addr=target,req_access_fault=int(denied),
                        imem_gnt=int(phase!='ungranted'),imem_rvalid=int(phase=='response'),
                        imem_rdata=0xDEADBEEF,imem_err=1)
                    accepted = bool(r['req_ready'])
                    assert accepted == (phase!='ungranted'), (phase,r)
                    if phase=='response': pending.popleft()
                    if r['imem_req'] and phase!='ungranted': pending.append(r['imem_addr'])
                    seen = False
                    for tick in range(32):
                        returning = bool(pending and tick>=3)
                        head = pending[0] if pending else None
                        data = 0xCAFEBABE if head==target else 0xDEADBEEF
                        r = await self.cycle(req_valid=int(not accepted),req_addr=target,
                            req_access_fault=int(denied),imem_gnt=int(tick>=3),
                            imem_rvalid=int(returning),imem_rdata=data,
                            imem_err=int(error if head==target else True),res_ready=1)
                        if r['res_valid']:
                            assert self.result(r)==completion(target,0xCAFEBABE,denied,error), (phase,r)
                            assert not seen, 'duplicate new-stream completion'
                            seen=True
                        if returning: pending.popleft()
                        if r['imem_req'] and tick>=3:
                            assert len(pending)<2
                            assert r['imem_addr']==target or phase=='ungranted'
                            pending.append(r['imem_addr'])
                        if not accepted and r['req_ready']: accepted=True
                        if seen and not r['busy']: break
                    assert seen and accepted and not r['busy'], (local,phase,denied,error,r)
        self.drop_objection()


class FallthroughTest(IfetchTest):
    async def finish_live(self, address, data, error=False):
        r=await self.cycle(imem_rvalid=1,imem_rdata=data,imem_err=int(error),res_ready=1)
        assert bool(r['res_valid'])==self.bypass
        if self.bypass:
            assert self.result(r)==completion(address,data,error=error)
            r=await self.cycle(res_ready=1,imem_rdata=MASK)
            assert not r['res_valid'] and not r['busy'], 'live response enqueued twice'
        else:
            await self.consume(completion(address,data,error=error))

    async def run_phase(self):
        self.raise_objection()
        for error in (False,True):
            for ready in (False,True):
                await self.reset()
                await self.accept(0x1000,grant_high=True)
                if ready:
                    await self.finish_live(0x1000,0x12345678,error)
                else:
                    r=await self.cycle(imem_rvalid=1,imem_rdata=0x12345678,imem_err=int(error))
                    assert bool(r['res_valid'])==self.bypass
                    if self.bypass: assert self.result(r)==completion(0x1000,0x12345678,error=error)
                    await self.consume(completion(0x1000,0x12345678,error=error),hold=4)
        # A live newer response cannot overtake a stored head, even when that
        # head is consumed now. The new word is stored for the following cycle.
        await self.reset()
        await self.accept(0x2000,grant_high=True)
        await self.cycle(req_valid=1,req_addr=0x2004,imem_gnt=1,
                         imem_rvalid=1,imem_rdata=0xAAAAAAAA,imem_err=0)
        r=await self.cycle(imem_rvalid=1,imem_rdata=0xBBBBBBBB,imem_err=0,res_ready=1)
        assert self.result(r)==completion(0x2000,0xAAAAAAAA)
        await self.consume(completion(0x2004,0xBBBBBBBB),hold=4)
        # Local clear must leave the old live word visible for prediction;
        # neither consumer readiness nor old-response errors may leak it later.
        for ready in (0,1):
            await self.reset()
            await self.accept(0x3000,grant_high=True)
            r=await self.cycle(clear=1,replace=1,req_valid=1,req_addr=0x8000,
                imem_gnt=1,imem_rvalid=1,imem_rdata=0xDEADBEEF,imem_err=1,res_ready=ready)
            assert r['req_ready'] and r['imem_req'] and r['imem_addr']==0x8000
            assert bool(r['res_valid'])==self.bypass
            if self.bypass: assert self.result(r)==completion(0x3000,0,error=True)
            await self.finish_live(0x8000,0xCAFEBABE)
        await self.reset()
        await self.accept(0x4000,grant_high=True)
        r=await self.cycle(flush=1,imem_rvalid=1,imem_rdata=MASK,imem_err=1,res_ready=1)
        assert not r['res_valid']
        r=await self.cycle(res_ready=1)
        assert not r['res_valid'] and not r['busy']
        # Synthesized PMP denials remain registered and never touch OBI.
        r=await self.cycle(req_valid=1,req_addr=0x5000,req_access_fault=1,res_ready=1)
        assert r['req_ready'] and not r['res_valid'] and not r['imem_req']
        await self.consume(completion(0x5000,0,denied=True))
        self.drop_objection()


class ControlTest(IfetchTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        r = await self.cycle(flush=1,req_valid=1)
        assert not r['req_ready'] and not r['busy']
        # Permission waits can be canceled without starting a bus transaction.
        await self.accept(0x1002,permit=False)
        r = await self.cycle(flush=1)
        assert r['busy'] and not r['imem_req'] and not r['res_valid']
        await self.operation(0x2000)
        # Permission granted on an edge presents the captured request directly
        # afterwards; a flush on the following cycle must preserve that request.
        await self.accept(0x1800,permit=False)
        await self.cycle(request_permit=1)
        r = await self.cycle(flush=1,request_permit=0)
        assert r['imem_req'] and r['imem_addr']==0x1800
        await self.grant(0x1800,flush=True)
        await self.respond(0x11223344)
        r = await self.cycle()
        assert not r['busy'] and not r['res_valid']
        for phase in ('request','grant','response','response_edge','result','denied_result'):
            await self.accept(0x1002,denied=phase=='denied_result')
            if phase=='request':
                for _ in range(4):
                    r = await self.cycle(flush=1)
                    assert r['imem_req'] and r['imem_addr']==0x1000 and not r['res_valid']
                await self.grant(0x1002,2)
                await self.respond(MASK,error=True,delay=4)
            elif phase=='grant':
                await self.grant(0x1002,2,flush=True)
                await self.respond(MASK,error=True,delay=4)
            elif phase in ('response','response_edge'):
                await self.grant(0x1002)
                if phase=='response':
                    r = await self.cycle(flush=1)
                    assert r['busy'] and not r['res_valid'] and not r['imem_req']
                await self.respond(MASK,error=True,delay=3,flush=phase=='response_edge')
            else:
                if phase=='result':
                    await self.grant(0x1002)
                    await self.respond(0xDEADBEEF,error=False)
                r = await self.cycle(flush=1,res_ready=1)
                assert not r['res_valid'] and not r['imem_req']
            r = await self.cycle()
            assert r['req_ready'] and not r['busy'] and not r['res_valid'],phase
            await self.operation(0x3000,data=0xCAFEBABE)
        # No internal timeout, retry or request replacement during long waits.
        await self.operation(0x4000,grant_delay=128,response_delay=128,hold=16)
        for phase in ('permission','request','response','result'):
            await self.accept(0x5000,permit=phase!='permission')
            if phase in ('response','result'):
                await self.grant(0x5000)
            if phase=='result':
                await self.respond(0x55)
            await self.reset()
            await self.operation(0x6000,data=0xFEEDFACE)
        self.drop_objection()


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def control(_dut):
    await uvm_root().run_test(ControlTest)


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def streaming(_dut):
    await uvm_root().run_test(StreamingTest)


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def pipelined_flush(_dut):
    await uvm_root().run_test(PipelinedFlushTest)


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def clear(_dut):
    await uvm_root().run_test(ClearTest)


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def replace(_dut):
    await uvm_root().run_test(ReplaceTest)


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def fallthrough(_dut):
    await uvm_root().run_test(FallthroughTest)


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def outstanding(_dut):
    await uvm_root().run_test(OutstandingTest)


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def stress(_dut):
    await uvm_root().run_test(StressTest)
