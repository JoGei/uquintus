"""Late-C operand timing with real execution, hazard, memory and register blocks."""
import json
import os
import random
from collections import deque

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

MASK = 0xffffffff


class MacPipelineTest(uvm_test):
    def build_phase(self):
        self.d = cocotb.top
        self.p = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.rf = [0] * 32

    async def settle(self):
        await Timer(1, units='ns')

    async def edge(self):
        self.d.clk_i.value = 1
        await self.settle()
        self.d.clk_i.value = 0
        await self.settle()

    async def initialize(self):
        for name, value in dict(clk=0, rst_n=0, flush=0, seed_we=0, seed_addr=0,
                                seed_data=0, in_valid=0, in_mac=0, in_rs0=0,
                                in_rs1=0, in_rs2=0, in_rd=0, out_ready=1).items():
            getattr(self.d, 'rst_ni' if name == 'rst_n' else name+'_i').value = value
        await self.edge()
        self.d.rst_ni.value = 1
        self.rf = [0] + [self.rng.getrandbits(32) for _ in range(31)]
        for address in range(1, 32):
            self.d.seed_we_i.value = 1
            self.d.seed_addr_i.value = address
            self.d.seed_data_i.value = self.rf[address]
            await self.edge()
        self.d.seed_we_i.value = 0
        await self.settle()

    async def execute(self, tokens, stalls=False):
        expected = deque()
        issued = 0
        accepts, retires = [], []
        held = None
        for cycle in range(10000):
            valid = issued < len(tokens)
            self.d.in_valid_i.value = valid
            if valid:
                a, b, c, rd, mac = tokens[issued]
                for name, value in zip(('rs0', 'rs1', 'rs2', 'rd', 'mac'), (a,b,c,rd,mac)):
                    getattr(self.d, 'in_'+name+'_i').value = value
            ready = not stalls or self.rng.randrange(4) != 0
            self.d.out_ready_i.value = ready
            await self.settle()
            out_valid = int(self.d.out_valid_o.value)
            packet = (int(self.d.out_rd_o.value), int(self.d.out_data_o.value))
            if held is not None:
                assert out_valid and packet == held, ('unstable WB', cycle, packet, held)
            if out_valid:
                assert expected and packet == expected[0], (cycle, packet, list(expected))
                if ready:
                    expected.popleft()
                    retires.append(cycle)
            held = packet if out_valid and not ready else None
            if valid and int(self.d.in_ready_o.value):
                value = (self.rf[a] * self.rf[b] + (self.rf[c] if mac else 0)) & MASK
                expected.append((rd, value))
                if rd:
                    self.rf[rd] = value
                accepts.append(cycle)
                issued += 1
            await self.edge()
            if issued == len(tokens) and not expected:
                break
        else:
            raise AssertionError(('watchdog', issued, len(tokens), list(expected)))
        return accepts, retires


class RecurrenceTest(MacPipelineTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        assert self.p['MUA_MUL'] == 13
        accepts, retires = await self.execute([(1,2,3,3,1)]*128)
        if self.p['MUA_FORWARDING']:
            assert all(b-a == 1 for a,b in zip(accepts, accepts[1:])), accepts
            assert all(b-a == 1 for a,b in zip(retires, retires[1:])), retires
        self.logger.info('128 dependent MACs: issue span=%d clocks, retirement span=%d clocks',
                         accepts[-1]-accepts[0], retires[-1]-retires[0])
        self.drop_objection()


class HazardsTest(MacPipelineTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        # Dependencies through A/B must wait; late-C must never waive these.
        for tokens in ([(3,2,1,3,1)]*32, [(1,3,2,3,1)]*32, [(3,3,3,3,1)]*32):
            accepts, _ = await self.execute(tokens)
            assert all(b-a >= 2 for a,b in zip(accepts, accepts[1:])), accepts
        # Youngest writer wins across EX/MEM/WB; x0 never has pending intent.
        tokens = [(1,2,0,3,0), (4,5,0,3,0), (6,7,3,8,1), (1,2,8,8,1),
                  (3,8,8,0,1), (0,2,0,9,1), (9,8,3,9,0)]*16
        await self.execute(tokens)
        self.drop_objection()


class BackpressureTest(MacPipelineTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        tokens = [(1,2,3,3,1)]*64
        tokens += [(self.rng.randrange(32), self.rng.randrange(32), self.rng.randrange(32),
                    self.rng.randrange(32), self.rng.randrange(2)) for _ in range(1024)]
        await self.execute(tokens, stalls=True)
        self.drop_objection()


class FlushResetTest(MacPipelineTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        for reset in (False, True):
            # Two accepted operations occupy EX/MEM, before any WB retirement.
            self.d.in_valid_i.value = 1
            self.d.in_mac_i.value = 1
            self.d.in_rs0_i.value = 1
            self.d.in_rs1_i.value = 2
            self.d.in_rs2_i.value = 3
            self.d.in_rd_i.value = 4
            for _ in range(2):
                await self.settle()
                assert int(self.d.in_ready_o.value)
                await self.edge()
            if reset:
                self.d.rst_ni.value = 0
            else:
                self.d.flush_i.value = 1
            self.d.in_valid_i.value = 0
            await self.edge()
            self.d.rst_ni.value = 1
            self.d.flush_i.value = 0
            for _ in range(4):
                await self.settle()
                assert not int(self.d.out_valid_o.value)
                await self.edge()
            await self.execute([(1,2,3,3,1)]*8)
        self.drop_objection()


@cocotb.test()
async def recurrence(_dut):
    await uvm_root().run_test(RecurrenceTest)


@cocotb.test()
async def hazards(_dut):
    await uvm_root().run_test(HazardsTest)


@cocotb.test()
async def backpressure(_dut):
    await uvm_root().run_test(BackpressureTest)


@cocotb.test()
async def flush_reset(_dut):
    await uvm_root().run_test(FlushResetTest)
