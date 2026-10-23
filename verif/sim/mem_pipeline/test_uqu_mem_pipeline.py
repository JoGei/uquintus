"""Real MEM with parent registers, concurrent WB draining and a parent-owned PMP."""

from collections import deque
import json
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from mem_model import FIELDS, OUTPUTS, ByteMemory, local_exception, outcome, request, token

PAYLOAD = FIELDS + ('pc', 'rd')
RESULT = OUTPUTS + ('pc', 'instr', 'rd')


class PipelineTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.enabled = json.loads(os.environ['UQU_COMPONENT_PARAMS'])['ISA_PMP']
        self.memory = ByteMemory()
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))

    async def settle(self):
        await Timer(1, units='ns')

    async def edge(self):
        self.dut.clk_i.value = 1
        await Timer(1, units='ns')
        self.dut.clk_i.value = 0
        await self.settle()

    def drive(self, item):
        for field in PAYLOAD:
            getattr(self.dut, 'in_' + field + '_i').value = item[field]

    def outputs(self):
        return tuple(int(getattr(self.dut, 'out_' + field + '_o').value) for field in RESULT)

    def packet(self):
        return tuple(int(getattr(self.dut, 'dmem_' + field + '_o').value)
                     for field in ('we', 'addr', 'wdata', 'be'))

    def allowed(self, item):
        # Independent interval policy: one unlocked RW NAPOT at 1000..1fff.
        if not self.enabled:
            return True
        first = item['result']
        size = item['op'] % 4
        last = first + (1 << size) - 1
        if size == 3 or last >= 1 << 32:
            return False
        if first < 0x2000 and last >= 0x1000:
            return first >= 0x1000 and last < 0x2000
        return bool(item['priv_m'])

    def expected(self, item, error=False):
        return outcome(item, self.memory, self.allowed(item), error) + (item['pc'], item['instr'], item['rd'])

    async def initialize(self):
        d = self.dut
        self.drive(token())
        d.clk_i.value = 0
        d.rst_ni.value = 0
        d.flush_i.value = 0
        d.in_valid_i.value = 0
        d.out_ready_i.value = 0
        d.request_permit_i.value = 0
        d.pmpcfg_i.value = 0x1B
        d.pmpaddr_i.value = 0x5FF
        d.dmem_gnt_i.value = 0
        d.dmem_rvalid_i.value = 0
        d.dmem_rdata_i.value = 0
        d.dmem_err_i.value = 0
        await self.settle()
        await self.edge()
        d.rst_ni.value = 1
        await self.settle()
        assert int(d.in_ready_o.value) and not int(d.out_valid_o.value)

    async def stream(self, items, stalls=False):
        d = self.dut
        queue = deque()
        by_pc = {item['pc']: item for item in items}
        expected = {}
        seen_issues = set()
        sent = received = grants = 0
        job = held_output = held_bus = held_pc = None
        for cycle in range(100000):
            d.in_valid_i.value = int(sent < len(items) and (not stalls or self.rng.randrange(4) != 0))
            if sent < len(items):
                self.drive(items[sent])
            d.out_ready_i.value = self.rng.randrange(2) if stalls else 1
            d.request_permit_i.value = int(not stalls or self.rng.randrange(3) != 0)
            d.dmem_gnt_i.value = int(job is not None and not job['granted'] and job['grant_wait'] == 0)
            responding = job is not None and job['granted'] and job['response_wait'] == 0
            d.dmem_rvalid_i.value = int(responding)
            d.dmem_rdata_i.value = job['word'] if responding else self.rng.getrandbits(32)
            d.dmem_err_i.value = job['error'] if responding else self.rng.randrange(2)
            await self.settle()
            if held_output is not None:
                assert int(d.out_valid_o.value) and self.outputs() == held_output
            if held_pc is not None:
                assert int(d.mem_valid_o.value) and int(d.mem_pc_o.value) == held_pc
            if held_bus is not None:
                assert int(d.dmem_req_o.value) and self.packet() == held_bus
            if int(d.out_valid_o.value):
                assert queue and expected.get(queue[0]['pc']) is not None
                actual, reference = self.outputs(), expected[queue[0]['pc']]
                assert actual[1:] == reference[1:], (actual, reference)
                if not reference[3]:
                    assert actual[0] == reference[0], (actual, reference)
                if int(d.out_ready_i.value):
                    queue.popleft()
                    received += 1
            if int(d.in_valid_i.value) and int(d.in_ready_o.value):
                item = items[sent]
                queue.append(item)
                req = request(item, self.allowed(item))
                if not item['lsu'] or item['exception_valid'] or local_exception(req):
                    expected[item['pc']] = self.expected(item)
                sent += 1
            # Bus scheduling is independent of pipeline consumption. Freeze a
            # load's expected data at grant, before younger stores can change it.
            if job is not None:
                if not job['granted']:
                    if int(d.dmem_req_o.value):
                        self.memory.check_request(request(job['item']), self.packet())
                        if int(d.dmem_gnt_i.value):
                            job['word'] = self.memory.grant(request(job['item']), self.packet())
                            expected[job['item']['pc']] = self.expected(job['item'], job['error'])
                            job['granted'] = True
                            grants += 1
                        else:
                            job['grant_wait'] -= 1
                elif responding:
                    job = None
                else:
                    job['response_wait'] -= 1
            if int(d.dmem_req_o.value) and job is None:
                pc = int(d.mem_pc_o.value)
                item = by_pc[pc]
                assert item['lsu'] and not item['exception_valid'] and pc not in seen_issues
                seen_issues.add(pc)
                assert int(d.u_mem.pmp_allow_i.value) == self.allowed(item)
                assert not local_exception(request(item, self.allowed(item)))
                job = dict(item=item, granted=False, grant_wait=self.rng.randrange(5),
                           response_wait=self.rng.randrange(7), error=item.get('error', False))
            held_output = self.outputs() if int(d.out_valid_o.value) and not int(d.out_ready_i.value) else None
            held_pc = (int(d.mem_pc_o.value) if int(d.mem_valid_o.value) and not int(d.u_mem.ready_o.value) else None)
            held_bus = self.packet() if int(d.dmem_req_o.value) and not int(d.dmem_gnt_i.value) else None
            await self.edge()
            if received == len(items) and not int(d.out_valid_o.value) and not int(d.mem_valid_o.value):
                assert job is None and not int(d.lsu_busy_o.value)
                assert len(seen_issues) == grants
                assert grants == sum(item['lsu'] and not item['exception_valid'] and
                                     not local_exception(request(item, self.allowed(item))) for item in items)
                return cycle + 1
        raise AssertionError('pipeline did not drain')


class StreamTest(PipelineTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        items = [token(result=i*17, pc=0x8000+4*i, rd=i%32,
                       instr=0x10000000+i, fflags_valid=i%2, fflags=i%32) for i in range(64)]
        elapsed = await self.stream(items)
        assert elapsed == len(items)+2, elapsed
        items = []
        for i in range(512):
            item = token(lsu=int(i%4 != 0), we=self.rng.randrange(2),
                         op=self.rng.choice((0, 1, 2, 4, 5, 7)),
                         result=self.rng.choice((0x1000, 0x1FFC, 0x2000, 0x3000))+self.rng.randrange(4),
                         store_data=self.rng.getrandbits(32), pc=0xA000+4*i,
                         rd=self.rng.randrange(32), instr=self.rng.getrandbits(32),
                         priv_m=self.rng.randrange(2), fflags_valid=self.rng.randrange(2),
                         fflags=self.rng.randrange(32), exception_valid=int(i%29 == 0),
                         exception_cause=2, exception_tval=self.rng.getrandbits(32),
                         error=self.rng.randrange(8) == 0)
            items.append(item)
        await self.stream(items, stalls=True)
        self.logger.info('MEM parent pipeline: 64 consecutive pass tokens and 512 randomized tokens, PMP=%d', self.enabled)
        self.drop_objection()


class DrainFlushTest(PipelineTest):
    async def step(self, **inputs):
        for name, value in inputs.items():
            getattr(self.dut, name).value = value
        await self.settle()
        snapshot = (int(self.dut.out_valid_o.value), self.outputs())
        await self.edge()
        return snapshot

    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        d = self.dut
        older = token(lsu=1, result=0x1000, pc=0x8000)
        victim = token(lsu=1, we=1, result=0x1004, pc=0x8004)
        self.drive(older)
        await self.step(in_valid_i=1, out_ready_i=1, request_permit_i=1)
        self.drive(victim)
        await self.settle()
        assert int(d.dmem_req_o.value)
        word = self.memory.grant(request(older), self.packet())
        await self.step(dmem_gnt_i=1)  # Older load now waits in WB; younger in MEM.
        await self.step(in_valid_i=0, dmem_gnt_i=0)
        assert not int(d.out_valid_o.value) and not int(d.dmem_req_o.value)
        await self.step(flush_i=1)  # Flush only the younger MEM instruction.
        assert not int(d.mem_valid_o.value) and int(d.lsu_busy_o.value)
        snap = await self.step(flush_i=0, dmem_rvalid_i=1, dmem_rdata_i=word)
        assert snap == (1, self.expected(older))
        await self.step(dmem_rvalid_i=0)
        assert not int(d.lsu_busy_o.value) and not int(d.out_valid_o.value)
        # A request already presented before flush must finish its bus handshake.
        self.drive(victim)
        await self.step(in_valid_i=1)
        await self.step(in_valid_i=0)  # Capture the request waiting for grant.
        saved = self.packet()
        await self.step(flush_i=1)
        assert int(d.dmem_req_o.value) and self.packet() == saved
        await self.step(flush_i=0, dmem_gnt_i=1)
        await self.step(dmem_gnt_i=0, dmem_rvalid_i=1, dmem_err_i=1)
        await self.step(dmem_rvalid_i=0, dmem_err_i=0)
        assert not int(d.out_valid_o.value) and not int(d.lsu_busy_o.value)
        await self.stream([token(result=0xABCDEF01, pc=0xC000)])
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def pipeline(_dut):
    await uvm_root().run_test(StreamTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def drain_flush(_dut):
    await uvm_root().run_test(DrainFlushTest)


class TurnoverTest(PipelineTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        d = self.dut
        items = [token(lsu=1, we=n%2, result=0x1000+4*n,
                       store_data=0x12340000+n, pc=0x9000+4*n) for n in range(24)]
        sent = retired = 0
        pending = None
        expected = deque()
        grant_cycles = []
        for cycle in range(64):
            d.in_valid_i.value = int(sent < len(items))
            if sent < len(items):
                self.drive(items[sent])
            d.out_ready_i.value = 1
            d.request_permit_i.value = 1
            d.dmem_gnt_i.value = 1
            d.dmem_rvalid_i.value = int(pending is not None)
            d.dmem_rdata_i.value = pending if pending is not None else 0
            await self.settle()
            if int(d.out_valid_o.value):
                assert expected and self.outputs() == expected.popleft()
                retired += 1
            pending = None
            if int(d.dmem_req_o.value):
                item = items[len(grant_cycles)]
                pending = self.memory.grant(request(item), self.packet())
                expected.append(self.expected(item))
                grant_cycles.append(cycle)
            if int(d.in_valid_i.value) and int(d.in_ready_o.value):
                sent += 1
            await self.edge()
            if retired == len(items):
                break
        assert sent == retired == len(items)
        assert grant_cycles == list(range(1, len(items)+1)), grant_cycles
        assert cycle+1 == len(items)+2  # Same throughput as pass-through tokens.
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def turnover(_dut):
    await uvm_root().run_test(TurnoverTest)
