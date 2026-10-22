"""Native IF stage: production prefetch control and all compressed placements."""
from pathlib import Path
import sys

import cocotb
from pyuvm import uvm_root

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'common'))
from if_stage_env import IfStageTest, MASK
from compressed_model import compressed as decode_compressed


class StreamTest(IfStageTest):
    async def run_phase(self):
        self.raise_objection()
        values = []
        for index in range(256):
            if self.c and index%3!=2:
                value = 0x0085 if index%2 else 1  # C.ADDI x1,1 / C.NOP
                size = 2
            else:
                value = self.rng.getrandbits(32)|3
                size = 4
            values.append((value,size))
        expected = self.put(0xFFFFFFE0,values)
        await self.reset(0xFFFFFFE0)
        await self.fill()
        assert self.accepted==[(0xFFFFFFE0+4*k)&MASK for k in range(len(self.accepted))]
        for _ in range(24):
            o = await self.cycle()
            assert not o['pmp_valid'] and o['valid']
        for _ in range(8192):
            await self.cycle(ready=int(self.rng.random()<0.7),permit=int(self.rng.random()<0.9))
            assert self.delivered==expected[:len(self.delivered)]
            if len(self.delivered)==len(expected):
                break
        else:
            raise AssertionError('stream did not finish')
        assert not self.faults and len(self.accepted)==len(set(self.accepted))
        self.drop_objection()


class ThroughputTest(IfStageTest):
    async def run_phase(self):
        self.raise_objection()
        count = 256
        self.put(0x1000, [(0x00000013,4)]*count)
        self.response_latency = 1
        await self.reset()
        deliveries = []
        for tick in range(count+64):
            o = await self.cycle(grant=1,ready=1)
            if o['valid']:
                deliveries.append(tick)
            if len(deliveries)==count:
                break
        assert len(deliveries)==count
        assert all(b-a==1 for a,b in zip(deliveries,deliveries[1:])), deliveries
        assert [pc for pc,*_ in self.delivered]==list(range(0x1000,0x1000+4*count,4))
        self.drop_objection()


class ControlTest(IfStageTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        # A private request waits for the combined request/control permits.
        o = await self.cycle(request_permit=0,grant=0)
        assert o['pmp_valid']
        for _ in range(8):
            o = await self.cycle(request_permit=0)
            assert o['fetch_busy'] and not o['imem_req']
        for _ in range(8):
            o = await self.cycle(fetch_enable=0)
            assert o['fetch_busy'] and not o['imem_req']
        # No-prediction mode also holds a privately accepted request.
        if self.params['MUA_BRANCH_PREDICTOR']==0:
            for _ in range(8):
                o = await self.cycle(branch_pending=1)
                assert not o['imem_req'] and not o['pmp_valid']
        await self.until(lambda o:bool(o['imem_req']),grant=0)
        for _ in range(12):
            o = await self.cycle(grant=0,request_permit=0,fetch_enable=0,branch_pending=1)
            assert o['imem_req'],'hold withdrew an asserted request'
        await self.cycle(grant=1,fetch_enable=0)
        await self.until(lambda o:bool(o['valid']),fetch_enable=0)
        # Delivery permission and downstream ready do not govern prefetch filling.
        before = len(self.accepted)
        await self.fill(permit=0)
        assert len(self.accepted)>before and not self.delivered
        for _ in range(8):
            o = await self.cycle(permit=0,ready=1)
            assert not o['valid']
        # A recognized DE branch gates requests only in none mode.
        await self.cycle(redirect_valid=1,redirect_addr=0x4000)
        before = len(self.accepted)
        for _ in range(128):
            await self.cycle(branch_pending=1,permit=0)
        if self.params['MUA_BRANCH_PREDICTOR']==0:
            assert len(self.accepted)==before
        else:
            assert self.depth<=len(self.accepted)-before<=self.depth+3
        await self.until(lambda o:bool(o['valid']),ready=1)
        # Misaligned redirect is an integration diagnostic, not a new trap.
        bad = 0x6001 if self.c else 0x6002
        await self.cycle(redirect_valid=1,redirect_addr=bad)
        for _ in range(12):
            o = await self.cycle(ready=1)
            assert o['misaligned'] and not o['valid'] and not o['pmp_valid']
        self.drop_objection()


class FaultsTest(IfStageTest):
    async def run_phase(self):
        self.raise_objection()
        self.denied.add(0x1000)
        await self.reset()
        await self.until(lambda o:bool(o['valid']))
        await self.cycle(ready=1)
        assert self.faults==[(0x1000,1,0x1000)] and 0x1000 not in self.granted
        for _ in range(12):
            o = await self.cycle(ready=1)
            assert not o['valid'] and not o['pmp_valid']
        # Privilege is supplied by the core; denial is latched at acceptance.
        self.deny_user = True
        await self.cycle(redirect_valid=1,redirect_addr=0x2000)
        o = await self.cycle(priv_m=0,request_permit=0)
        assert o['pmp_valid'] and not o['pmp_priv_m']
        await self.until(lambda o:bool(o['valid']),priv_m=1)
        await self.cycle(ready=1)
        assert self.faults[-1]==(0x2000,1,0x2000)
        # A real bus error must wait for its response; a held token stays exact.
        self.errors.add(0x3000)
        pc = 0x3002 if self.c else 0x3000
        await self.cycle(redirect_valid=1,redirect_addr=pc)
        await self.until(lambda o:bool(o['valid']))
        for _ in range(8):
            o = await self.cycle()
            assert o['exception_valid'] and o['exception_tval']==pc
        await self.cycle(ready=1)
        assert self.faults[-1]==(pc,1,pc)
        if self.c:
            self.words[0xFFFFFFFC] = 0x00930001
            self.errors.add(0)
            await self.cycle(redirect_valid=1,redirect_addr=0xFFFFFFFC)
            await self.until(lambda o:len(self.delivered)>0,ready=1)
            assert self.delivered[-1][0:3]==(0xFFFFFFFC,1,1)
            await self.until(lambda o:bool(o['exception_valid']))
            await self.cycle(ready=1)
            assert self.faults[-1]==(0xFFFFFFFE,1,0)
        self.drop_objection()


class RedirectsTest(IfStageTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        target = 0x8002 if self.c else 0x8000
        for phase in ('private','ungranted','grant','response','response_edge','result','buffered'):
            origin = 0x1000+len(self.accepted)*0x100
            self.errors.add(origin)
            await self.cycle(redirect_valid=1,redirect_addr=origin,fetch_enable=0)
            await self.until(lambda o:not o['fetch_busy'],fetch_enable=0)
            await self.cycle(request_permit=int(phase!='private'),grant=0)
            if phase in ('response','response_edge','result','buffered'):
                await self.cycle(grant=1,respond=0,fetch_enable=0)
            if phase in ('result','buffered'):
                await self.cycle(respond=1,fetch_enable=0)
            if phase=='buffered':
                await self.cycle(fetch_enable=0)
                o = await self.cycle(fetch_enable=0)
                assert o['valid']
            await self.cycle(redirect_valid=1,redirect_addr=target,grant=int(phase=='grant'),
                             respond=int(phase=='response_edge'),fetch_enable=0)
            # Later redirects win while the same old request drains.
            await self.cycle(redirect_valid=1,redirect_addr=target+0x100,grant=0,respond=0,fetch_enable=0)
            before = len(self.delivered)
            await self.until(lambda o:len(self.delivered)>before,ready=1)
            assert self.delivered[before][0]==target+0x100 and not self.faults
            target += 0x200
        # Flush without a redirect stops, even after the engine finishes draining.
        await self.cycle(flush=1)
        await self.until(lambda o:not o['fetch_busy'])
        for _ in range(24):
            o = await self.cycle(ready=1)
            assert not o['valid'] and not o['pmp_valid']
        before = len(self.delivered)
        await self.cycle(flush=1,redirect_valid=1,redirect_addr=0xA000)
        await self.until(lambda o:len(self.delivered)>before,ready=1)
        assert self.delivered[before][0]==0xA000
        await self.cycle(redirect_valid=1,redirect_addr=0xB000)
        await self.until(lambda o:bool(o['imem_req']),grant=0)
        await self.reset(0xC000)
        before = len(self.delivered)
        await self.until(lambda o:len(self.delivered)>before,ready=1)
        assert self.delivered[before][0]==0xC000
        self.drop_objection()


class CompressedTest(IfStageTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        # Every supported compressed encoding reaches IF/DE with the right form.
        # Reserved forms must fault only in IF-expansion mode, with original tval.
        samples = [0,1,0x0085,0x2001,0x4002,0x9002,0xFFFE]
        samples += [self.rng.randrange(65536)&~3|self.rng.randrange(3) for _ in range(128)]
        for index,value in enumerate(samples):
            pc = 0x10000+index*16+(2 if self.c and index%2 else 0)
            self.words[pc&~3] = value<<16|1 if pc&2 else 0x00010000|value
            await self.cycle(redirect_valid=1,redirect_addr=pc,fetch_enable=0)
            await self.until(lambda o:bool(o['valid']))
            o = await self.cycle(ready=1)
            if self.c:
                result = decode_compressed(value)
                assert o['original_instr']==value and o['compressed']
                if self.expand_if and result is None:
                    assert o['exception_cause']==2 and o['exception_tval']==value
                else:
                    assert not o['exception_valid']
                    assert o['instr']==(result[1] if self.expand_if else value)
            else:
                assert not o['compressed'] and not o['exception_valid']
        self.drop_objection()


class PredictionTest(IfStageTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        if not self.predictor.enabled:
            await self.until(lambda o:bool(o['valid']))
            o = await self.cycle(ready=1,predictor_update_valid=1,predictor_update_pc=0x1000,
                predictor_update_control_flow=1,predictor_update_taken=1,predictor_update_target=0x8000)
            assert o['predicted_next_pc']==o['next_pc']
            self.drop_objection(); return
        # Capture a prediction while IF is stalled. Training the same entry must
        # not mutate that token; the next visit observes the new target.
        await self.cycle(predictor_update_valid=1,predictor_update_pc=0x1000,
            predictor_update_control_flow=1,predictor_update_taken=1,predictor_update_target=0x8000)
        await self.until(lambda o:bool(o['valid']))
        for _ in range(4):
            o = await self.cycle(predictor_update_valid=1,predictor_update_pc=0x1000,
                predictor_update_control_flow=1,predictor_update_taken=1,predictor_update_target=0x9000)
            assert o['predicted_next_pc']==0x8000
        before=len(self.delivered)
        await self.cycle(ready=1)
        await self.until(lambda o:len(self.delivered)>before+1,ready=1)
        assert self.delivered[before+1][0]==0x8000
        await self.cycle(redirect_valid=1,redirect_addr=0x1000)
        await self.until(lambda o:bool(o['valid']))
        assert (await self.cycle())['predicted_next_pc']==0x9000
        # External recovery wins over a predicted redirect on the same cycle.
        await self.cycle(ready=1,redirect_valid=1,redirect_addr=0xA000)
        await self.until(lambda o:bool(o['valid']))
        assert (await self.cycle())['pc']==0xA000
        # Prediction uses ordinary fetch/PMP: a denied predicted target faults
        # at that target, never at the original branch.
        await self.cycle(predictor_update_valid=1,predictor_update_pc=0xB000,
            predictor_update_control_flow=1,predictor_update_taken=1,predictor_update_target=0xC000)
        self.denied.add(0xC000)
        await self.cycle(redirect_valid=1,redirect_addr=0xB000)
        await self.until(lambda o:o['pc']==0xC000 and o['exception_valid'],ready=1)
        assert self.faults[-1]==(0xC000,1,0xC000)
        # FENCE.I-style invalidation discards learned targets.
        await self.cycle(predictor_invalidate=1,redirect_valid=1,redirect_addr=0xB000)
        await self.until(lambda o:bool(o['valid']))
        o=await self.cycle(ready=1)
        assert o['predicted_next_pc']==o['next_pc']
        self.drop_objection()


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def stream(dut):
    await uvm_root().run_test('StreamTest')


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def control(dut):
    await uvm_root().run_test('ControlTest')


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def faults(dut):
    await uvm_root().run_test('FaultsTest')


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def redirects(dut):
    await uvm_root().run_test('RedirectsTest')


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def compressed(dut):
    await uvm_root().run_test('CompressedTest')


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def prediction(dut):
    await uvm_root().run_test('PredictionTest')


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def throughput(dut):
    await uvm_root().run_test('ThroughputTest')

class IdataTest(IfStageTest):
    async def seed_prefix(self, branch, target, values):
        expected = self.put(target, values)
        await self.cycle(redirect_valid=1,redirect_addr=target)
        await self.until(lambda o: bool(o['valid']),grant=1)
        await self.cycle(ready=1,grant=1,predictor_update_valid=1,
            predictor_update_pc=branch,predictor_update_control_flow=1,
            predictor_update_conditional=0,predictor_update_taken=1,predictor_update_target=target)
        before = len(self.delivered)
        retained = self.predictor.fit_prefix([instr for instr,_ in values])
        while len(self.delivered)<before+len(retained)-1:
            await self.cycle(ready=1,grant=1)
        return expected

    async def visit(self, branch):
        await self.cycle(redirect_valid=1,redirect_addr=branch,grant=1)
        await self.until(lambda o: bool(o['valid']),grant=1)
        o = await self.cycle(ready=1,grant=1)
        assert o['pc'] == branch and o['predicted_next_pc'] != o['next_pc']
        return await self.cycle(grant=1)

    async def run_phase(self):
        self.raise_objection()
        self.response_latency = 1
        await self.reset()
        hwords = self.predictor.hwords
        if not hwords:
            self.drop_objection(); return
        target = 0x8002 if self.c else 0x8000
        # Alternating C32/C16, starting with a crossing C32. Continuation ends
        # inside a word at several depths; its other half must stay available.
        values = [(0x100093+0x100000*k,4) if not self.c or (hwords > 1 and k%2 == 0) else (0x0085,2)
                  for k in range(hwords+6)]
        depth = len(self.predictor.fit_prefix([instr for instr,_ in values]))
        expected = await self.seed_prefix(0x1000,target,values)
        assert len(self.predictor.payload(0x1000))==depth
        o = await self.visit(0x1000)
        assert o['valid'] and o['pc']==target, 'warm target must be available next cycle'
        before=len(self.delivered)
        accepted_before=len(self.accepted)
        # Stalled replay must stay stable even when its BTB owner is replaced.
        alias = 0x1000+self.predictor.capacity*self.predictor.alignment
        for _ in range(5):
            await self.cycle(grant=1,predictor_update_valid=1,predictor_update_pc=alias,
                predictor_update_control_flow=1,predictor_update_taken=1,predictor_update_target=0xC000)
        for _ in range(256):
            await self.cycle(ready=int(self.rng.random()<0.7),grant=1)
            if len(self.delivered)==before+len(values): break
        else: raise AssertionError('replay/continuation did not finish')
        assert self.delivered[before:] == expected
        continuation = expected[depth][0]&~3
        assert self.accepted[accepted_before-1] == continuation, self.accepted[accepted_before-1:]
        # A new visit learns the displaced branch again. Replays themselves
        # may refill missing slots, and an external recovery retains the prefix.
        await self.seed_prefix(0x1000,target,values)
        await self.visit(0x1000)
        await self.cycle(redirect_valid=1,redirect_addr=0xD000)
        o=await self.visit(0x1000)
        assert o['valid'] and o['pc']==target
        # Live denial at the first word must not use the old fill-time allow.
        self.denied.add(target&~3)
        o=await self.cycle(ready=1)
        assert o['exception_valid'] and o['exception_tval']==target
        self.denied.clear()
        if self.c and values[0][1] == 4:
            await self.visit(0x1000)
            self.denied.add((target&~3)+4)
            o=await self.cycle(ready=1)
            assert o['exception_valid'] and o['exception_tval']==target+2
            self.denied.clear()
        # Invalidation while held drops the active snapshot. Changed code must
        # be fetched again; no explicit redirect is required for this recovery.
        await self.visit(0x1000)
        new = [(0x00200113,4)]*(depth+6)
        fresh = self.put(target,new)
        await self.cycle(predictor_invalidate=1,grant=1)
        await self.until(lambda o:bool(o['valid']),grant=1)
        before=len(self.delivered)
        await self.cycle(ready=1,grant=1)
        assert self.delivered[before] == fresh[0]
        assert not self.predictor.payload(0x1000)
        # Nested target steering replaces the active window, including when
        # the old continuation still has accepted bus work to drain.
        a_branch, b_branch, b_target = 0x1100, 0x9004, 0xA000
        a_values = [(0x0085,2) if self.c and hwords == 1 else (0x13,4)]*(depth+6)
        b_values = [(0x0085,2) if self.c and (hwords == 1 or k%2) else (0x13,4) for k in range(depth+6)]
        await self.seed_prefix(a_branch,b_branch,a_values)
        await self.seed_prefix(b_branch,b_target,b_values)
        o=await self.visit(a_branch)
        assert o['valid'] and o['pc']==b_branch and o['predicted_next_pc']==b_target
        await self.cycle(ready=1,grant=1)
        o=await self.cycle(grant=1)
        assert o['valid'] and o['pc']==b_target
        # Privilege is live, rather than copied from the M-mode fill context.
        self.deny_user=True
        o=await self.cycle(ready=1,grant=1,priv_m=0)
        assert o['exception_valid'] and o['exception_cause']==1
        self.deny_user=False
        await self.cycle(flush=1,predictor_invalidate=1)
        for _ in range(12):
            o=await self.cycle(ready=1,grant=1)
            assert not o['valid'] and not o['pmp_valid']
        self.drop_objection()


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def idata(dut):
    await uvm_root().run_test('IdataTest')


class IdataLatencyTest(IdataTest):
    async def run_phase(self):
        self.raise_objection()
        self.response_latency=1
        await self.reset()
        depth=self.predictor.hwords//2
        if not depth or self.c:
            self.drop_objection(); return
        values=[(0x13,4)]*(depth+8)
        await self.seed_prefix(0x1000,0x8000,values)
        await self.cycle(redirect_valid=1,redirect_addr=0x1000,grant=1)
        await self.until(lambda o:bool(o['valid']),grant=1)
        branch=await self.cycle(ready=1,grant=1)
        assert branch['pc']==0x1000 and branch['predicted_next_pc']==0x8000
        times=[]
        for tick in range(1,depth+32):
            o=await self.cycle(ready=1,grant=1)
            if o['valid']: times.append(tick)
            if len(times)==depth+4: break
        assert times[:depth]==list(range(1,depth+1)), times
        assert times[depth]==max(4,depth+1), times
        self.drop_objection()


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def idata_latency(dut):
    await uvm_root().run_test('IdataLatencyTest')


class FreshFetchLatencyTest(IfStageTest):
    async def run_phase(self):
        self.raise_objection()
        self.response_latency = 1
        # No stale bus work and no target replay: test the actual cold refill.
        for target in ((0x8000,0x9002) if self.c else (0x8000,0x9000)):
            await self.reset()
            await self.cycle(redirect_valid=1,redirect_addr=target,fetch_enable=0,grant=1)
            for tick in range(1,5):
                o = await self.cycle(grant=1,ready=1)
                if tick==1:
                    assert o['imem_req'] and o['imem_addr']==target&~3
                assert bool(o['valid']) == (tick==4), (tick,o)
            assert self.delivered[-1][0] == target
        self.drop_objection()


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def fresh_fetch_latency(dut):
    await uvm_root().run_test('FreshFetchLatencyTest')
