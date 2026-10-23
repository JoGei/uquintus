"""DE/EX dependency correctness and temporal retention with independent modelling."""

import itertools
import json
import os
import random

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

from hazard_model import HazardModel, defaults


class HazardTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.p = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.model = HazardModel(self.p)
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.checks = 0

    async def compare(self, i):
        expected = self.model.outputs(i)
        for name, value in expected.items():
            if name in ('de_rs0', 'de_rs1', 'de_rs2', 'ex_rs0', 'ex_rs1', 'ex_rs2'):
                consumer, slot = name[:2], int(name[-1])
                if not expected[consumer+'_rs_ready'] & (1 << slot):
                    continue  # Unready candidate data has no architectural value.
            actual = int(getattr(self.dut, name+'_o').value)
            assert actual == value, (name, actual, value, i, self.model.retained, self.p)
        self.checks += 1
        return expected

    async def check(self, values=None, edge=False, **changes):
        i = dict(defaults() if values is None else values, **changes)
        self.dut.clk_i.value = 0
        for name, value in i.items():
            port = 'rst_ni' if name == 'rst_n' else name+'_i'
            getattr(self.dut, port).value = value
        await Timer(1, units='ns')
        before = await self.compare(i)
        if edge:
            self.dut.clk_i.value = 1
            self.model.edge(i)
            await Timer(1, units='ns')
            await self.compare(i)
        return before

    async def reset(self):
        await self.check(rst_n=0, edge=True)

    def report(self):
        self.logger.info('%d checked observations, params=%s', self.checks, self.p)


class DirectedTest(HazardTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        # An unavailable youngest producer still selects candidate data; only
        # readiness changes. Do not route response/fault qualification into the
        # operand word and then through downstream arithmetic.
        for stage in ('ex', 'mem', 'wb'):
            for available, forwardable in itertools.product(range(2), repeat=2):
                i = defaults()
                i.update({stage+'_pending': 1, stage+'_rd0': 1,
                          stage+'_result_available': available,
                          stage+'_result_forwardable': forwardable,
                          stage+'_result': 0xA5C03F17})
                await self.check(i)
                for consumer in ('de', 'ex'):
                    if stage == 'ex' and consumer == 'ex':
                        continue
                    if self.model.route(stage, consumer):
                        assert int(getattr(self.dut, consumer+'_rs0_o').value) == 0xA5C03F17
        # Occupancy, pending intent and both result qualifications are separate.
        # Every producer targets all source slots in turn, including x0/E bounds.
        for stage in ('ex', 'mem', 'wb'):
            for slot in range(3):
                for address in (0, 1, 15, 16, 31):
                    for valid, pending, available, forwardable in itertools.product(range(2), repeat=4):
                        await self.check(**{
                            'de_rs'+str(slot)+'_addr': address,
                            'ex_rs'+str(slot)+'_addr': address,
                            stage+'_valid': valid, stage+'_pending': pending,
                            stage+'_rd0': address, stage+'_result_available': available,
                            stage+'_result_forwardable': forwardable,
                            stage+'_result': 0xA5000000+slot,
                        })
        # All same-register writer combinations; unavailable younger results
        # must never expose an older result or the stale GPR value.
        for pending_mask, available_mask, permitted_mask in itertools.product(range(8), repeat=3):
            i = defaults()
            for n, stage in enumerate(('ex', 'mem', 'wb')):
                i.update({stage+'_rd0': 1, stage+'_pending': pending_mask >> n & 1,
                          stage+'_result_available': available_mask >> n & 1,
                          stage+'_result_forwardable': permitted_mask >> n & 1,
                          stage+'_result': 0xABC00000+n})
            await self.check(i)
        # A paired secondary is a dependency but never a bypass source.
        for stage in ('ex', 'mem', 'wb'):
            i = defaults()
            i.update({stage+'_pending': 3, stage+'_rd0': 2, stage+'_rd1': 3,
                      stage+'_result_available': 1, stage+'_result_forwardable': 1,
                      stage+'_result': 0xC0FFEE,
                      'de_rs0_addr': 2, 'de_rs1_addr': 3,
                      'ex_rs0_addr': 2, 'ex_rs1_addr': 3})
            r = await self.check(i)
            if self.model.dual:
                assert not r['de_rs_ready'] & 2 and not r['de_rs_ex_guaranteed'] & 2
            # Ignore enables/addresses naming x0 even on malicious descriptors.
            await self.check(i, de_rs0_addr=0, ex_rs0_addr=0,
                             **{stage+'_rd0': 0, stage+'_rd1': 0})
        # Already-captured EX operands are authoritative and never overwritten
        # by unrelated/current producers; absent capture is never a GPR reread.
        for captured, used in itertools.product(range(8), repeat=2):
            await self.check(ex_rs_captured=captured, ex_rs_used=used,
                             mem_pending=1, mem_rd0=1,
                             mem_result_available=1, mem_result_forwardable=1,
                             mem_result=0xBAD)
        await self.check(de_valid=0, ex_valid=0)
        await self.check(de_rs_used=0, ex_rs_used=0, de_rs_need_now=7)
        self.report()
        self.drop_objection()


class GuaranteesTest(HazardTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        for stage in ('ex', 'mem', 'wb'):
            for move, now, available, permitted in itertools.product(range(2), repeat=4):
                i = defaults()
                i.update({stage+'_pending': 1, stage+'_rd0': 1,
                          stage+'_advance': move, stage+'_result_available': available,
                          stage+'_result_forwardable': permitted, stage+'_result': 0x4242,
                          'de_rs_need_now': now})
                r = await self.check(i)
                if now or not available or not permitted:
                    assert not r['de_rs_ex_guaranteed'] & 1
        # Adjacent ADD -> SUB: follow a promised value into MEM and resolve it
        # in EX, with stale DE bits intentionally left in the consumer payload.
        i = defaults()
        i.update(ex_pending=1, ex_rd0=1, ex_result_available=1,
                 ex_result_forwardable=1, ex_result=0xBEEF, ex_advance=1)
        r = await self.check(i)
        if r['de_rs_ex_guaranteed'] & 1:
            following = defaults()
            following.update(mem_pending=1, mem_rd0=1, mem_result_available=1,
                             mem_result_forwardable=1, mem_result=0xBEEF)
            r2 = await self.check(following)
            assert r2['ex_rs_ready'] & 1 and r2['ex_rs0'] == 0xBEEF
        # MEM staying versus moving to WB requires a different enabled route.
        for advance in (0, 1):
            i = defaults()
            i.update(mem_pending=1, mem_rd0=1, mem_result_available=1,
                     mem_result_forwardable=1, mem_result=0x1234, mem_advance=advance)
            r = await self.check(i)
            if r['de_rs_ex_guaranteed'] & 1:
                future = 'wb' if advance else 'mem'
                r2 = await self.check(**{future+'_pending': 1, future+'_rd0': 1,
                    future+'_result_available': 1, future+'_result_forwardable': 1,
                    future+'_result': 0x1234})
                assert r2['ex_rs_ready'] & 1 and r2['ex_rs0'] == 0x1234
        # Address-only load and unavailable offload: no readiness or guarantee.
        r = await self.check(mem_pending=1, mem_rd0=1, mem_result=0xDEADBEEF,
                             mem_result_available=0, mem_result_forwardable=1, mem_advance=1)
        assert not (r['de_rs_ready'] | r['de_rs_ex_guaranteed'] | r['ex_rs_ready']) & 1
        self.report()
        self.drop_objection()


class LifecycleTest(HazardTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        # Wait for x2 while x1 passes through WB; capture may happen while DE
        # does not advance. Model RF is updated only after the write edge.
        held = defaults()
        held.update(wb_pending=1, wb_rd0=1, wb_result_available=1,
                    wb_result_forwardable=1, wb_result=0x7777,
                    mem_pending=1, mem_rd0=2)
        await self.check(held, edge=True)
        retired = dict(held, wb_pending=0, wb_valid=0, de_rs0=0x7777)
        await self.check(retired, edge=True)
        completed = dict(retired, mem_result_available=1, mem_result_forwardable=1,
                         mem_result=0x8888)
        await self.check(completed, edge=True)
        # Explicit clear must preserve current outputs before transfer, then
        # prevent old values from leaking into the replacement slot.
        await self.check(completed, de_clear=1, edge=True)
        await self.check(de_rs0=0x9999, de_rs1=0xAAAA, edge=True)
        await self.check(de_valid=0, edge=True)
        await self.check(de_rs0=0xBBBB, edge=True)
        await self.check(rst_n=0, edge=True)
        await self.check(de_rs0=0xCCCC)
        # A transient EX value can be retained across a disabled MEM route.
        transient = defaults()
        transient.update(ex_pending=1, ex_rd0=1, ex_result_available=1,
                         ex_result_forwardable=1, ex_result=0x12345678,
                         mem_pending=1, mem_rd0=2)
        await self.check(transient, edge=True)
        gap = defaults()
        gap.update(mem_pending=1, mem_rd0=1, mem_result_available=0,
                   mem_result_forwardable=0)
        r = await self.check(gap)
        if self.p['MUA_FORWARDING'] and self.p['MUA_FORWARD_EX_TO_DE']:
            assert bool(r['de_rs_ready'] & 1) == bool(self.p['MUA_DE_OPERAND_RETENTION'])
        # Stale data with only a future guarantee must never enter retention.
        await self.reset()
        promise = defaults()
        promise.update(ex_pending=1, ex_rd0=1, ex_result_available=1,
                       ex_result_forwardable=1, ex_result=0xF00D, ex_advance=1)
        await self.check(promise, edge=True)
        if not self.p['MUA_FORWARD_EX_TO_DE']:
            blocked = dict(promise, ex_result_available=0)
            r = await self.check(blocked)
            assert not r['de_rs_ready'] & 1
        self.report()
        self.drop_objection()


class RandomizedTest(HazardTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        # Source identities stay fixed for a token's lifetime. Arbitrary
        # producer readiness/movement and slot replacement stress retained state.
        for _ in range(500):
            await self.check(de_clear=1, edge=True)
            i = defaults()
            for consumer in ('de', 'ex'):
                i[consumer+'_rs_used'] = self.rng.randrange(8)
                for n in range(3):
                    i[consumer+'_rs'+str(n)+'_addr'] = self.rng.randrange(32)
                    i[consumer+'_rs'+str(n)] = self.rng.getrandbits(32)
            i['de_rs_need_now'] = self.rng.randrange(8) & i['de_rs_used']
            i['ex_rs_captured'] = self.rng.randrange(8)
            for _cycle in range(8):
                for stage in ('ex', 'mem', 'wb'):
                    i[stage+'_valid'] = self.rng.randrange(2)
                    i[stage+'_pending'] = self.rng.randrange(4)
                    # Bias toward matching consumers and overlapping writers.
                    addresses = [i[c+'_rs'+str(n)+'_addr'] for c in ('de', 'ex') for n in range(3)]
                    i[stage+'_rd0'] = self.rng.choice(addresses)
                    i[stage+'_rd1'] = self.rng.choice(addresses)
                    i[stage+'_result_available'] = self.rng.randrange(2)
                    i[stage+'_result_forwardable'] = self.rng.randrange(2)
                    i[stage+'_advance'] = self.rng.randrange(2)
                    i[stage+'_result'] = self.rng.getrandbits(32)
                await self.check(i, edge=True)
        self.report()
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def guarantees(_dut):
    await uvm_root().run_test(GuaranteesTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def lifecycle(_dut):
    await uvm_root().run_test(LifecycleTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)
