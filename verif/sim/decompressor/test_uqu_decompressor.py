"""Exhaustive RV32C expansion and real decoder/DE integration checks."""
from collections import Counter
import json
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from decode_model import decode
from decompressor_model import expand, immediate


class DecompressorTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = dict(ISA_F=0, ISA_A=0, ISA_ZIFENCEI=0, DEBUG=0)
        self.params.update(json.loads(os.environ['UQU_COMPONENT_PARAMS']))
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.hits = Counter()

    async def check(self, word, pc=0x1000, rs0=0, rs1=0, ready=1, permit=1):
        d = self.dut
        for name, value in dict(instr=word, pc=pc, rs0=rs0, rs1=rs1,
                                ready=ready, permit=permit).items():
            getattr(d, name+'_i').value = value & 0xFFFFFFFF
        await Timer(1, units='ns')
        expected, name = expand(word, self.params['ISA_C'])
        for signal, value in expected.items():
            assert int(getattr(d, signal+'_o').value) == value, (hex(word), name, signal, value)
        decoded, _ = decode(expected['instr'], self.params)
        for signal, value in decoded.items():
            assert int(getattr(d, 'dec_'+signal+'_o').value) == value, (hex(word), name, signal, value)
        if expected['compressed'] and not expected['illegal']:
            assert decoded['native']
            assert decoded['illegal'] == decoded['illegal_reg']
        self.hits[name] += 1
        return expected, decoded

    def value(self, signal):
        return int(getattr(self.dut, signal+'_o').value)


class DirectedTest(DecompressorTest):
    async def run_phase(self):
        self.raise_objection()
        known = {
            0x0001: 0x00000013, 0x0085: 0x00108093, 0x8082: 0x00008067,
            0x9082: 0x000080E7, 0x9002: 0x00100073, 0x85AA: 0x00A005B3,
            0x95AA: 0x00A585B3, 0x6141: 0x01010113, 0x1141: 0xFF010113,
            0x0040: 0x00410413, 0x4000: 0x00042403, 0xC000: 0x00842023,
            0x0002: 0x00001013, 0x8001: 0x00045413, 0x0805: 0x00180813,
        }
        for half, base in known.items():
            result, _ = await self.check(0xBEEF0000 | half)
            if self.params['ISA_C']:
                assert result['instr'] == base and not result['illegal'], (hex(half), hex(base))
        for half in (0, 0x4002, 0x6001, 0x8002, 0x1002, 0x9001, 0x9C01):
            result, _ = await self.check(0xABCD0000 | half)
            assert result['illegal'] == self.params['ISA_C']
        # FP transfer slots remain unsupported even when Zfinx is enabled.
        for quadrant in (0, 2):
            for group in (1, 3, 5, 7):
                result, _ = await self.check(group << 13 | 0x0840 | quadrant)
                assert result['illegal'] == self.params['ISA_C']
        self.drop_objection()


class ExhaustiveTest(DecompressorTest):
    async def run_phase(self):
        self.raise_objection()
        hints = 0
        for half in range(65536):
            word = (((half*31337) ^ 0xA55A) & 65535) << 16 | half
            result, _ = await self.check(word)
            hints += result['hint']
            # HINT expansions have no architectural integer-register effect.
            if result['hint']:
                op = result['instr']
                rd, rs1, rs2 = (op >> 7) & 31, (op >> 15) & 31, (op >> 20) & 31
                regs = [0]+[self.rng.getrandbits(32) for _ in range(31)]
                before = regs[:]
                if op & 127 == 0x37:
                    value = op & 0xFFFFF000
                elif op & 127 == 0x33:
                    value = (regs[rs1]+regs[rs2]) & 0xFFFFFFFF
                else:
                    funct3 = (op >> 12) & 7
                    signed_imm = (op >> 20)-(4096 if op >> 31 else 0)
                    if funct3 == 0:
                        value = (regs[rs1]+signed_imm) & 0xFFFFFFFF
                    elif funct3 == 1:
                        value = (regs[rs1] << rs2) & 0xFFFFFFFF
                    else:
                        assert funct3 == 5 and rs2 == 0
                        value = regs[rs1]
                if rd:
                    regs[rd] = value
                assert regs == before, (hex(half), hex(op))
        if self.params['ISA_C']:
            wanted = {'c.'+name for name in (
                'addi4spn lw sw nop addi jal j li addi16sp lui srli srai andi '
                'sub xor or and beqz bnez slli lwsp mv add jr jalr ebreak swsp').split()}
            assert wanted == self.hits.keys()-{'native', 'illegal'}
            assert hints == 362, hints
            assert self.hits['native'] == 16384
        else:
            assert self.hits == {'native': 65536} and hints == 0
        self.logger.info('Exhausted 65,536 halfwords; %d hints; coverage: %s', hints, dict(self.hits))
        self.drop_objection()


class PassthroughTest(DecompressorTest):
    async def run_phase(self):
        self.raise_objection()
        for _ in range(4096):
            word = self.rng.getrandbits(32)
            if self.params['ISA_C']:
                word |= 3
            result, _ = await self.check(word)
            assert result == dict(instr=word, original_instr=word, compressed=0, illegal=0, hint=0)
        for half in (0, 1, 0x9082, 0xFFFF, 0x6141, 0xC001, 0x0805):
            reference = None
            for high in (0, 1, 0x8000, 0xFFFF, 0x1234):
                result, _ = await self.check(high << 16 | half)
                if self.params['ISA_C'] and half & 3 != 3:
                    if reference is not None:
                        assert result == reference
                    reference = result
        self.drop_objection()


class IntegrationTest(DecompressorTest):
    async def run_phase(self):
        self.raise_objection()
        # The leaf never validates or changes a native 32-bit instruction.
        await self.check(0x000000EF, pc=0x1000)
        assert self.value('de_pass_data') == 0x1004
        if not self.params['ISA_C']:
            await self.check(0x9002)
            assert self.value('de_exception_valid') and self.value('de_exception_tval') == 0x9002
            self.drop_objection()
            return
        for half in (0x2001, 0x9082):
            for pc in (0x1002, 0xFFFFFFFE):
                await self.check(half, pc=pc, rs0=0x2003)
                assert self.value('de_pass_data') == (pc+2) & 0xFFFFFFFF
                assert self.value('de_branch_resolve') and self.value('de_branch_taken')
                target = pc if half == 0x2001 else 0x2002
                assert self.value('de_next_pc') == target
                assert not self.value('de_exception_valid')
        # Every encoded branch displacement, taken and not taken, including wrap.
        for group in (6, 7):
            for bits in range(256):
                half = group << 13 | 1 | sum(
                    ((bits >> index) & 1) << position
                    for index, position in enumerate((2, 3, 4, 5, 6, 10, 11, 12)))
                offset = immediate(half, 'branch', True)
                for source in (0, 1):
                    await self.check(half, pc=0xFFFFFFFE, rs0=source)
                    taken = (source == 0) == (group == 6)
                    assert self.value('de_branch_taken') == taken
                    assert self.value('de_next_pc') == (0xFFFFFFFE+(offset if taken else 2)) & 0xFFFFFFFF
        # The expander has no handshake; DE controls when a redirect is used.
        for ready, permit in ((0, 1), (1, 0), (0, 0), (1, 1)):
            await self.check(0x9082, ready=ready, permit=permit, rs0=0x2001)
            assert self.value('de_branch_resolve') == (ready & permit)
        for half in (0, 0x4002, 0x6001, 0x8002, 0x1002, 0x2000, 0xE002):
            await self.check(0xBEEF0000 | half)
            assert self.value('de_exception_valid') and self.value('de_exception_cause') == 2
            assert self.value('de_exception_tval') == half
        # RV32E legality remains in DE; register fields survive hint expansion.
        for half in (0x0805, 0x0801, 0x0842, 0xC042):
            result, _ = await self.check(0xABCD0000 | half)
            assert not result['illegal']
            assert self.value('de_exception_valid') == self.params['ISA_E']
            if self.params['ISA_E']:
                assert self.value('de_exception_tval') == half
        await self.check(0x9002)
        assert not self.value('de_exception_valid')  # EBREAK is a serialized WB token.
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def exhaustive(_dut):
    await uvm_root().run_test(ExhaustiveTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def passthrough(_dut):
    await uvm_root().run_test(PassthroughTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def integration(_dut):
    await uvm_root().run_test(IntegrationTest)
