"""Independent word transactions, OBI timing, retained results and killed drains."""
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from ifetch_model import MASK, completion, word_address


class IfetchTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.previous = None
        self.count = 0

    async def cycle(self, **changes):
        i = dict(rst_n=1, flush=0, req_valid=0, req_addr=0, req_access_fault=0,
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
        if not o['imem_req']:
            assert o['imem_addr'] == 0
        else:
            assert o['busy'] and not o['req_ready'] and not o['res_valid']
            assert o['imem_addr'] & 3 == 0
        if o['res_valid']:
            assert o['busy'] and not o['req_ready'] and not o['imem_req']
        if self.previous:
            old_i, old_o = self.previous
            if old_o['imem_req'] and not old_i['imem_gnt'] and i['rst_n']:
                assert o['imem_req'] and o['imem_addr'] == old_o['imem_addr'], 'request withdrawn/replaced'
            if old_o['res_valid'] and not old_i['res_ready'] and i['rst_n'] and not i['flush']:
                assert o['res_valid'] and self.result(o) == self.result(old_o), 'retained result changed'
        self.previous = i,o
        d.clk_i.value = 1
        await Timer(1, units='ns')
        return o

    @staticmethod
    def result(o):
        return o['res_addr'],o['res_data'],o['res_error']

    async def reset(self):
        r = await self.cycle(rst_n=0)
        assert not any(r.values())
        r = await self.cycle()
        assert r['req_ready'] and not r['busy']

    async def accept(self, address, denied=False, permit=True, grant_high=False):
        r = await self.cycle(req_valid=1, req_addr=address, req_access_fault=int(denied),
                             request_permit=int(permit), imem_gnt=int(grant_high))
        assert r['req_ready'] and not r['busy'] and not r['imem_req'] and not r['res_valid']

    async def grant(self, address, delay=0, flush=False):
        for index in range(delay+1):
            r = await self.cycle(imem_gnt=int(index==delay), flush=int(flush),
                req_valid=1, req_addr=address ^ MASK, req_access_fault=1, request_permit=0)
            assert r['imem_req'] and r['imem_addr'] == word_address(address)
            assert not r['req_ready'] and not r['res_valid']

    async def respond(self, data, error=False, delay=0, flush=False):
        for _ in range(delay):
            r = await self.cycle(imem_rdata=self.rng.getrandbits(32), imem_err=self.rng.randrange(2))
            assert r['busy'] and not r['res_valid'] and not r['imem_req']
        r = await self.cycle(imem_rvalid=1, imem_rdata=data, imem_err=int(error), flush=int(flush))
        assert not r['res_valid'], 'combinational bus-response bypass'
        assert r['busy'] and not r['imem_req']

    async def consume(self, expected, hold=0):
        for index in range(hold+1):
            r = await self.cycle(res_ready=int(index==hold), req_valid=1,
                req_addr=0xBAD00000, req_access_fault=1, imem_rdata=MASK,
                imem_err=1, request_permit=0)
            assert r['res_valid'] and self.result(r) == expected, (r,expected)
            assert not r['req_ready']
        r = await self.cycle()
        assert r['req_ready'] and not r['busy'] and not r['res_valid']
        self.count += 1

    async def operation(self, address, data=0x12345678, denied=False, error=False,
                        grant_delay=0, response_delay=0, hold=0, permit_wait=0, grant_high=False):
        await self.accept(address, denied, not permit_wait, grant_high)
        if not denied:
            if permit_wait:
                for _ in range(permit_wait):
                    r = await self.cycle(request_permit=0, imem_gnt=1, req_access_fault=1)
                    assert r['busy'] and not r['imem_req'] and not r['res_valid']
                r = await self.cycle(request_permit=1, req_access_fault=1)
                assert not r['imem_req'] and not r['res_valid']
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
