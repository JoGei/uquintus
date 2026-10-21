"""Combinational branch semantics and decoder integration; no clock or predictor."""
import json
import os
import random

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

MASK = (1 << 32)-1
DEFAULT = dict(branch=0, branch_op=0, pc=0x1000, imm=0, rs1=0, rs2=0, compressed=0)
OUTPUTS = ('taken', 'target', 'next_pc', 'link', 'illegal', 'misaligned')


def signed(value):
    return value if value < 1 << 31 else value-(1 << 32)


def reference(i, c_enabled):
    kind, op = i['branch'], i['branch_op']
    compare = {0: i['rs1'] == i['rs2'], 1: i['rs1'] != i['rs2'],
               4: signed(i['rs1']) < signed(i['rs2']), 5: signed(i['rs1']) >= signed(i['rs2']),
               6: i['rs1'] < i['rs2'], 7: i['rs1'] >= i['rs2']}
    illegal = bool((kind == 1 and op not in compare) or (i['compressed'] and not c_enabled))
    if illegal:
        return dict(taken=0, target=0, next_pc=i['pc'], link=0, illegal=1, misaligned=0)
    fallthrough = (i['pc'] + (2 if i['compressed'] else 4)) & MASK
    target = ((i['rs1'] if kind == 3 else i['pc']) + signed(i['imm'])) & MASK
    if kind == 3:
        target -= target % 2
    taken = kind in (2, 3) or (kind == 1 and compare[op])
    misaligned = taken and target % (2 if c_enabled else 4) != 0
    return dict(taken=int(taken), target=target if kind else 0,
                next_pc=i['pc'] if misaligned else target if taken else fallthrough,
                link=fallthrough if kind in (2, 3) and not misaligned else 0,
                illegal=0, misaligned=int(misaligned))


def encode_b(op, offset):
    e = offset & 0x1FFF
    return ((e >> 12) << 31 | ((e >> 5) & 63) << 25 | 2 << 20 | 1 << 15 |
            op << 12 | ((e >> 1) & 15) << 8 | ((e >> 11) & 1) << 7 | 0x63)


def encode_j(offset, rd=1):
    e = offset & 0x1FFFFF
    return ((e >> 20) << 31 | ((e >> 1) & 1023) << 21 | ((e >> 11) & 1) << 20 |
            ((e >> 12) & 255) << 12 | rd << 7 | 0x6F)


class BranchTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.c = json.loads(os.environ['UQU_COMPONENT_PARAMS'])['ISA_C']
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.checks = 0

    async def check(self, decoded=None, instr=0x13, **values):
        i = dict(DEFAULT, **values)
        for name, value in i.items():
            getattr(self.dut, name+'_i').value = value
        self.dut.instr_i.value = instr
        await Timer(1, units='ns')
        expected = reference(i, self.c)
        for name in OUTPUTS:
            actual = int(getattr(self.dut, name+'_o').value)
            assert actual == expected[name], (name, actual, expected, i, self.c)
        if decoded is not None:
            kind, op, immediate, illegal = decoded
            controls = dict(dec_branch=kind, dec_branch_op=op, dec_imm=immediate & MASK,
                            dec_illegal=illegal, dec_pass_link=int(kind in (2, 3)))
            for name, value in controls.items():
                assert int(getattr(self.dut, name+'_o').value) == value, (name, hex(instr), value)
            expected_decode = reference(dict(i, branch=kind, branch_op=op, imm=immediate & MASK), self.c)
            for name, value in expected_decode.items():
                port = 'dec_control_illegal_o' if name == 'illegal' else 'dec_'+name+'_o'
                actual = int(getattr(self.dut, port).value)
                assert actual == value, (port, actual, value, i, decoded, hex(instr))
        self.checks += 1
        return expected

    def report(self, name):
        self.logger.info('%s: %d branch vectors checked (ISA_C=%d)', name, self.checks, self.c)


class DirectedTest(BranchTest):
    async def run_phase(self):
        self.raise_objection()
        edge = (0, 1, 2, 0x7FFFFFFE, 0x7FFFFFFF, 0x80000000, 0x80000001, 0xFFFFFFFE, MASK)
        for a in edge:
            for b in edge:
                for op in range(8):
                    for offset in (4, MASK-3):
                        await self.check(branch=1, branch_op=op, rs1=a, rs2=b, imm=offset)
        # Signed and unsigned ordering must disagree across the sign boundary.
        assert (await self.check(branch=1, branch_op=4, rs1=MASK, rs2=1, imm=4))['taken']
        assert not (await self.check(branch=1, branch_op=6, rs1=MASK, rs2=1, imm=4))['taken']
        for kind in (0, 2, 3):
            for op in range(8):  # Conditional funct3 is irrelevant to these kinds.
                for pc in (0, 0x1000, 0x7FFFFFFC, 0xFFFFFFFC):
                    for offset in (0, 4, MASK-3, 0x80000000, 0x7FFFFFFF):
                        await self.check(branch=kind, branch_op=op, pc=pc, imm=offset, rs1=MASK, rs2=0xDEADBEEF)
        r = await self.check(branch=3, rs1=MASK, imm=1, pc=0xFFFFFFFC)
        assert r['target'] == r['next_pc'] == r['link'] == 0 and not r['misaligned']
        # Repeated evaluation while DE is held is a level, not a redirect event.
        before = await self.check(branch=2, imm=16)
        for _ in range(8):
            assert (await self.check(branch=2, imm=16)) == before
        self.report('Directed')
        self.drop_objection()


class AlignmentTest(BranchTest):
    async def run_phase(self):
        self.raise_objection()
        for compressed in (0, 1):
            for pc in (0, 2, 0x1000, 0xFFFFFFFE):
                for target in range(16):
                    for kind in (0, 1, 2, 3):
                        for taken in (0, 1):
                            r = await self.check(branch=kind, branch_op=0, pc=pc,
                                imm=(target-pc) & MASK, rs1=pc if kind == 3 else 0,
                                rs2=0 if taken else 1, compressed=compressed)
                            if compressed and not self.c:
                                assert r['illegal'] and not r['misaligned'] and not r['link']
        # A non-taken branch cannot fault because its unused target is misaligned.
        r = await self.check(branch=1, branch_op=0, rs1=1, rs2=2, imm=3)
        assert not r['misaligned'] and r['next_pc'] == 0x1004
        # Clear JALR bit 0 before checking IALIGN; bit 1 is preserved.
        for low in range(4):
            r = await self.check(branch=3, rs1=0x2000+low)
            assert r['target'] == 0x2000+(low & 2)
            assert bool(r['misaligned']) == bool(not self.c and low & 2)
        if self.c:
            r = await self.check(branch=3, rs1=0x2002, pc=0x1002, compressed=1)
            assert r['link'] == 0x1004 and r['next_pc'] == 0x2002
            r = await self.check(branch=2, pc=0x1002, imm=4, compressed=0)
            assert r['link'] == 0x1006  # A 32-bit instruction at a halfword PC.
        self.report('Alignment')
        self.drop_objection()


class RandomizedTest(BranchTest):
    async def run_phase(self):
        self.raise_objection()
        for _ in range(32768):
            await self.check(branch=self.rng.randrange(4), branch_op=self.rng.randrange(8),
                pc=self.rng.getrandbits(32), imm=self.rng.getrandbits(32),
                rs1=self.rng.getrandbits(32), rs2=self.rng.getrandbits(32), compressed=self.rng.randrange(2))
        self.report('Randomized')
        self.drop_objection()


class DecoderTest(BranchTest):
    async def run_phase(self):
        self.raise_objection()
        lengths = (0, 1) if self.c else (0,)
        for compressed in lengths:
            for pc in (0, 2 if self.c else 4, 0x1000, 0xFFFFFFFC):
                for op in range(8):
                    for offset in (-4096, -2, 0, 2, 4, 4094):
                        good = op not in (2, 3)
                        for equal in (0, 1):
                            await self.check(instr=encode_b(op, offset),
                                decoded=(1, op, offset, 0) if good else (0, 0, 0, 1),
                                pc=pc, rs1=MASK, rs2=MASK if equal else 1, compressed=compressed)
                for offset in (-1048576, -2048, -2, 0, 2, 2046, 1048574):
                    for rd in (0, 1, 31):
                        await self.check(instr=encode_j(offset, rd), decoded=(2, 0, offset, 0),
                                         pc=pc, compressed=compressed)
                for offset in (-2048, -1, 0, 1, 2, 2047):
                    for base in (0, 1, 0x2002, MASK):
                        instruction = (offset & 4095) << 20 | 1 << 15 | 1 << 7 | 0x67
                        await self.check(instr=instruction, decoded=(3, 0, offset, 0),
                                         pc=pc, rs1=base, compressed=compressed)
        # Native non-control instructions produce sequential flow, not a redirect.
        for instruction in (0x13, 0x00000037, 0x00002003, 0x00002023, 0x30200073):
            await self.check(instr=instruction, decoded=(0, 0, 0, 0))
        self.report('Decoder integration')
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def alignment(_dut):
    await uvm_root().run_test(AlignmentTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def decoder(_dut):
    await uvm_root().run_test(DecoderTest)
