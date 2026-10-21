"""Native decode controls, immediate layouts and rejected encodings; no clock."""
import json
import os
import random

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

from decode_model import RULES, MASK32, decode


class DecodeTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.checks = 0
        self.hits = set()

    async def check(self, word):
        word &= MASK32
        self.dut.instr_i.value = word
        await Timer(1, units='ns')
        expected, name = decode(word, self.params)
        for signal, value in expected.items():
            actual = int(getattr(self.dut, signal+'_o').value)
            assert actual == value, (hex(word), name, signal, actual, value, self.params)
        if name and not expected['illegal']:
            self.hits.add(name)
        self.checks += 1
        return expected

    def report(self):
        self.logger.info('%d words checked; %d legal instruction variants hit', self.checks, len(self.hits))


class DirectedTest(DecodeTest):
    async def run_phase(self):
        self.raise_objection()
        for r in RULES:
            free = MASK32 ^ r.mask
            # Every rule, x0 and E boundary, plus ignored encoding fields.
            for registers in (0, 1, 15, 16, 31):
                payload = (registers << 7) | (registers << 15) | (registers << 20) | (registers << 27)
                await self.check(r.match | (payload & free))
            for bit in range(32):
                await self.check(r.match ^ (1 << bit))
            for _ in range(24):
                await self.check(r.match | (self.rng.getrandbits(32) & free))
        # Independent semantic assertions for easy-to-confuse operand fields.
        addi = await self.check(0x40008093)  # addi x1,x1,1024; bit30 must not select SUB.
        assert addi['op'] == 0 and addi['imm'] == 1024 and addi['fu'] == 0
        for f3 in (0, 2, 3, 4, 6, 7):
            r = await self.check(0xFFF08093 | (f3 << 12))
            assert r['imm'] == MASK32  # SLTIU also sign extends its immediate.
        for shift in (0, 1, 15, 16, 31):
            r = await self.check(0x4000D093 | (shift << 20))
            assert r['imm'] == shift and r['op'] == 13 and r['rs_used'] == 1
        # CSR immediate 31 is not x31. Fence's rd/rs1 fields are ignored.
        r = await self.check(0x340FD0F3)
        assert not r['illegal'] and r['csr_imm'] and not r['rs_used'] and r['imm'] == 31
        r = await self.check(0xFFFFFFFF & ~0x707F | 0x0F)
        assert not r['illegal'] and not r['rs_used'] and not r['rd_we'] and r['serialize']
        # Raw 16-bit instructions/long encodings are not expanded here.
        for word in (0, 1, 0x9002, 0xFFFFFFFF, 0x0000001F, 0x0000003F):
            assert (await self.check(word))['illegal']
        # Zfinx excludes floating loads/stores and both FMV transfer encodings.
        for word in (0x00002087, 0x00102027, 0xE0000053, 0xF0000053):
            assert (await self.check(word))['illegal']
        # Unary/convert selectors are not rs2 reads; fused rs3 really is a GPR.
        for r in RULES:
            if not r.feature or self.params[r.feature]:
                await self.check(r.match)
        wanted = {r.name for r in RULES if not r.feature or self.params[r.feature]}
        assert self.hits == wanted, wanted-self.hits
        self.report()
        self.drop_objection()


class EncodingsTest(DecodeTest):
    async def run_phase(self):
        self.raise_objection()
        # Full funct7/funct3 space for instruction families that reserve fields.
        for opcode in (0x03, 0x23, 0x13, 0x33, 0x63, 0x53, 0x73, 0x0F):
            for f7 in range(128):
                for f3 in range(8):
                    await self.check(f7 << 25 | 2 << 20 | 1 << 15 | f3 << 12 | 3 << 7 | opcode)
        # Every opcode/funct3 plus all unary/conversion subcodes and FP formats/rm.
        for opcode in range(128):
            for f3 in range(8):
                await self.check(0xA5A00000 | 1 << 15 | f3 << 12 | 3 << 7 | opcode)
        for f7 in (0x2C, 0x60, 0x68, 0x70, 0x78):
            for subcode in range(32):
                for f3 in range(8):
                    await self.check(f7 << 25 | subcode << 20 | 1 << 15 | f3 << 12 | 3 << 7 | 0x53)
        for opcode in (0x43, 0x47, 0x4B, 0x4F):
            for fmt in range(4):
                for rm in range(8):
                    for rs3 in (0, 15, 16, 31):
                        await self.check(rs3 << 27 | fmt << 25 | 2 << 20 | 1 << 15 | rm << 12 | 3 << 7 | opcode)
        # Exhaust each immediate layout (sign/boundary bits), excluding register fields.
        for kind in ('I', 'S', 'B', 'U', 'J'):
            r = next(r for r in RULES if r.immediate == kind)
            for bit in range(32):
                free = MASK32 ^ r.mask
                await self.check(r.match | ((1 << bit) & free))
                await self.check(r.match | ((MASK32 ^ (1 << bit)) & free))
        self.report()
        self.drop_objection()


class RandomizedTest(DecodeTest):
    async def run_phase(self):
        self.raise_objection()
        for n in range(32768):
            if n % 2:
                rule = self.rng.choice(RULES)
                word = rule.match | (self.rng.getrandbits(32) & (MASK32 ^ rule.mask))
                if n % 8 == 1:
                    word ^= 1 << self.rng.randrange(32)
            else:
                word = self.rng.getrandbits(32)
            await self.check(word)
        self.report()
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def encodings(_dut):
    await uvm_root().run_test(EncodingsTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)
