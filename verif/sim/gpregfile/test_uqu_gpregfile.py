"""Storage-contract tests; no assumptions about unwritten register values."""

import json
import os
import random

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test


class GpRegfileTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = json.loads(os.environ["UQU_COMPONENT_PARAMS"])
        self.num_regs = 16 if self.params["ISA_E"] else 32
        self.read_third = bool((self.params["ISA_M"] and self.params["MUA_MUL"] == 13) or self.params["ISA_ZFINX"] or
                               (self.params["XIF"] and self.params["XIF_NUM_RS"] == 3))
        self.write_second = bool(self.params["XIF"] and self.params["XIF_DUALWRITE"])
        self.model = [None] * self.num_regs
        self.model[0] = 0
        self.checks = 0

    def drive(self, name, value):
        getattr(self.dut, name).value = value

    async def settle(self):
        await Timer(1, units="ns")

    def check_reads(self):
        for port in range(3):
            address = int(getattr(self.dut, f"raddr{port}_i").value)
            if (port == 2 and not self.read_third) or address >= self.num_regs:
                expected = 0
            else:
                expected = self.model[address]
            if expected is not None:
                actual = int(getattr(self.dut, f"rdata{port}_o").value)
                assert actual == expected, (
                    f"read port {port}, x{address}: expected {expected:#010x}, "
                    f"got {actual:#010x}; params={self.params}")
                self.checks += 1

    def apply_writes(self, writes, reset):
        if reset:
            return
        # Apply lower priority port first, independently of the RTL storage.
        for port in (1, 0):
            enable, address, value = writes[port]
            if port == 1 and not self.write_second:
                continue
            if enable and 0 < address < self.num_regs:
                self.model[address] = value

    async def cycle(self, writes=((0, 0, 0), (0, 0, 0)), reads=(0, 0, 0), reset=False):
        self.drive("clk_i", 0)
        self.drive("rst_ni", int(not reset))
        for port, address in enumerate(reads):
            self.drive(f"raddr{port}_i", address)
        for port, (enable, address, value) in enumerate(writes):
            self.drive(f"we{port}_i", enable)
            self.drive(f"waddr{port}_i", address)
            self.drive(f"wdata{port}_i", value)
        await self.settle()
        self.check_reads()  # Live WB data must not bypass stored contents.
        self.drive("clk_i", 1)
        self.apply_writes(writes, reset)
        await self.settle()
        self.check_reads()
        # Adversarial high-phase changes must not act as extra writes. This
        # exercises the latch backend's captured-data/enables contract too.
        for port, (enable, address, value) in enumerate(writes):
            self.drive(f"we{port}_i", 1 - enable)
            self.drive(f"waddr{port}_i", (address + 1) % 32)
            self.drive(f"wdata{port}_i", value ^ 0xFFFFFFFF)
        await self.settle()
        self.check_reads()
        self.drive("clk_i", 0)
        await self.settle()
        self.check_reads()

    async def initialize(self):
        # Reset controls once; initialize storage explicitly, never via reset.
        await self.cycle(reset=True)
        for address in range(1, self.num_regs):
            await self.cycle(writes=((1, address, 0x10203040 ^ (address * 0x01010101)),
                                     (0, 0, 0)), reads=(address, address, address))

    async def sweep(self):
        # Addresses are combinational: scan every GPR without clock edges.
        for address in range(32):
            for port in range(3):
                self.drive(f"raddr{port}_i", (address + port) % 32)
            await self.settle()
            self.check_reads()


class DirectedTest(GpRegfileTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        await self.sweep()
        await self.cycle(writes=((1, 0, 0xFFFFFFFF), (1, 0, 0xDEADBEEF)))
        await self.cycle(writes=((1, 2, 0x12345678), (1, 3, 0x87654321)), reads=(2, 3, 2))
        # Either port may write without the other, when that port exists.
        await self.cycle(writes=((0, 4, 0), (1, 5, 0xA5A5A5A5)), reads=(4, 5, 5))
        # Defensive collision rule: primary write port wins.
        await self.cycle(writes=((1, 6, 0x11111111), (1, 6, 0x22222222)), reads=(6, 6, 6))
        # Source/destination aliases, simultaneous writes, and boundary GPRs.
        last = self.num_regs - 1
        await self.cycle(writes=((1, last - 1, 0x80000000), (1, last, 0x7FFFFFFF)),
                         reads=(last - 1, last, last))
        if self.num_regs == 16:
            for high in range(16, 32):
                await self.cycle(writes=((1, high, 0xBAD00000 + high),
                                         (1, high, 0xBAD10000 + high)),
                                 reads=(high, high - 16, high))
        # Reset suppresses writes on its sampled edge but preserves GPR data.
        await self.cycle(writes=((1, 2, 0), (1, 3, 0)), reads=(2, 3, 2), reset=True)
        await self.cycle(reads=(2, 3, 0))
        await self.sweep()
        self.logger.info("Directed storage checks: %d", self.checks)
        self.drop_objection()


class RandomizedTest(GpRegfileTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        rng = random.Random(int(os.environ["RANDOM_SEED"]))
        for _ in range(500):
            writes = [(rng.randrange(2), rng.randrange(32), rng.getrandbits(32))
                      for _ in range(2)]
            # Frequently exercise dependencies, aliases, and collisions.
            if rng.randrange(4) == 0:
                writes[1] = (1, writes[0][1], rng.getrandbits(32))
            reads = (writes[0][1], writes[1][1], rng.randrange(32))
            await self.cycle(writes=writes, reads=reads, reset=rng.randrange(25) == 0)
            if rng.randrange(16) == 0:
                await self.sweep()
        await self.sweep()
        self.logger.info("Randomized storage checks: %d", self.checks)
        self.drop_objection()


# Explicit cocotb entry points keep TESTCASE selection independent of pyuvm's
# decorator implementation; both entries run their test through pyuvm phases.
@cocotb.test(timeout_time=100, timeout_unit="us")
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test(timeout_time=100, timeout_unit="us")
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)
