"""Mask/match ISA oracle and architectural operand descriptions.

Encoding masks follow riscv/riscv-opcodes rv_i, rv32_i, rv_m, rv_f,
rv_zicsr, rv_zifencei and the canonical privileged/debug SYSTEM words.
The DUT's nested opcode decoder is deliberately not used as the oracle.
"""
from dataclasses import dataclass, field

MASK32 = (1 << 32)-1
SAFE = dict(rs_used=0, rs1=0, rs2=0, rs3=0, rd_we=0, rd=0, imm=0,
            fu=3, op=0, a_sel=2, b_sel=2, pass_link=0, branch=0, branch_op=0,
            lsu=0, mem_we=0, mem_op=0, wb_kind=0, system=0, serialize=0,
            csr_addr=0, csr_op=0, csr_imm=0, rm=0)


@dataclass
class Rule:
    name: str
    mask: int
    match: int
    props: dict = field(default_factory=dict)
    sources: int = 0
    writes: bool = False
    immediate: str = ''
    feature: str = ''
    rounding: bool = False


RULES = []


def rule(name, mask, match, sources=0, writes=False, immediate='', feature='', rounding=False, **props):
    RULES.append(Rule(name, mask, match, props, sources, writes, immediate, feature, rounding))


rule('lui', 0x7F, 0x37, writes=True, immediate='U', fu=0, b_sel=1)
rule('auipc', 0x7F, 0x17, writes=True, immediate='U', fu=0, a_sel=1, b_sel=1)
rule('jal', 0x7F, 0x6F, writes=True, immediate='J', pass_link=1, branch=2)
rule('jalr', 0x707F, 0x67, sources=1, writes=True, immediate='I', pass_link=1, branch=3)
for name, code in [('beq', 0), ('bne', 1), ('blt', 4), ('bge', 5), ('bltu', 6), ('bgeu', 7)]:
    rule(name, 0x707F, 0x63 | code << 12, sources=3, immediate='B', branch=1, branch_op=code)
for name, code in [('lb', 0), ('lh', 1), ('lw', 2), ('lbu', 4), ('lhu', 5)]:
    rule(name, 0x707F, 3 | code << 12, sources=1, writes=True, immediate='I',
         fu=0, a_sel=0, b_sel=1, lsu=1, mem_op=code)
for name, code in [('sb', 0), ('sh', 1), ('sw', 2)]:
    rule(name, 0x707F, 0x23 | code << 12, sources=3, immediate='S',
         fu=0, a_sel=0, b_sel=1, lsu=1, mem_we=1, mem_op=code)
for name, code in [('addi', 0), ('slti', 2), ('sltiu', 3), ('xori', 4), ('ori', 6), ('andi', 7)]:
    rule(name, 0x707F, 0x13 | code << 12, sources=1, writes=True, immediate='I',
         fu=0, a_sel=0, b_sel=1, op=code)
for name, match, code in [('slli', 0x1013, 1), ('srli', 0x5013, 5), ('srai', 0x40005013, 13)]:
    rule(name, 0xFE00707F, match, sources=1, writes=True, immediate='SHAMT',
         fu=0, a_sel=0, b_sel=1, op=code)
for name, code in [('add', 0), ('sll', 1), ('slt', 2), ('sltu', 3), ('xor', 4), ('srl', 5), ('or', 6), ('and', 7), ('sub', 8), ('sra', 13)]:
    rule(name, 0xFE00707F, 0x33 | (code & 7) << 12 | (0x40000000 if code & 8 else 0),
         sources=3, writes=True, fu=0, a_sel=0, b_sel=0, op=code)
for code, name in enumerate(('mul', 'mulh', 'mulhsu', 'mulhu', 'div', 'divu', 'rem', 'remu')):
    rule(name, 0xFE00707F, 0x02000033 | code << 12, sources=3, writes=True,
         feature='ISA_M', fu=1, a_sel=0, b_sel=0, op=code)
rule('fence', 0x707F, 0x0F, serialize=1, system=6)
rule('fence.i', 0x707F, 0x100F, feature='ISA_ZIFENCEI', serialize=1, system=7)
for name, match, sys, wb in [('ecall', 0x00000073, 1, 0), ('ebreak', 0x00100073, 2, 5),
                            ('mret', 0x30200073, 3, 2), ('dret', 0x7B200073, 4, 4),
                            ('wfi', 0x10500073, 5, 0)]:
    rule(name, MASK32, match, feature='DEBUG' if name == 'dret' else '',
         system=sys, wb_kind=wb, serialize=int(name != 'wfi'))
for code, name in [(1, 'csrrw'), (2, 'csrrs'), (3, 'csrrc'), (5, 'csrrwi'), (6, 'csrrsi'), (7, 'csrrci')]:
    rule(name, 0x707F, 0x73 | code << 12, sources=0 if code & 4 else 1, writes=True,
         immediate='ZIMM' if code & 4 else '', wb_kind=1, serialize=1, csr_op=code, csr_imm=int(bool(code & 4)))
for name, match, op in [('fmadd.s', 0x43, 5), ('fmsub.s', 0x47, 6), ('fnmsub.s', 0x4B, 7), ('fnmadd.s', 0x4F, 8)]:
    rule(name, 0x0600007F, match, sources=7, writes=True, feature='ISA_ZFINX', rounding=True,
         fu=2, a_sel=0, b_sel=0, op=op)
for name, match, op in [('fadd.s', 0x00000053, 0), ('fsub.s', 0x08000053, 1),
                        ('fmul.s', 0x10000053, 2), ('fdiv.s', 0x18000053, 3)]:
    rule(name, 0xFE00007F, match, sources=3, writes=True, feature='ISA_ZFINX', rounding=True,
         fu=2, a_sel=0, b_sel=0, op=op)
rule('fsqrt.s', 0xFFF0007F, 0x58000053, sources=1, writes=True, feature='ISA_ZFINX',
     rounding=True, fu=2, a_sel=0, b_sel=0, op=4)
for name, match, op in [('fsgnj.s', 0x20000053, 9), ('fsgnjn.s', 0x20001053, 10),
                        ('fsgnjx.s', 0x20002053, 11), ('fmin.s', 0x28000053, 12),
                        ('fmax.s', 0x28001053, 13), ('feq.s', 0xA0002053, 14),
                        ('flt.s', 0xA0001053, 15), ('fle.s', 0xA0000053, 16)]:
    rule(name, 0xFE00707F, match, sources=3, writes=True, feature='ISA_ZFINX',
         fu=2, a_sel=0, b_sel=0, op=op)
rule('fclass.s', 0xFFF0707F, 0xE0001053, sources=1, writes=True, feature='ISA_ZFINX',
     fu=2, a_sel=0, b_sel=0, op=17)
for name, match, op in [('fcvt.w.s', 0xC0000053, 18), ('fcvt.wu.s', 0xC0100053, 19),
                        ('fcvt.s.w', 0xD0000053, 20), ('fcvt.s.wu', 0xD0100053, 21)]:
    rule(name, 0xFFF0007F, match, sources=1, writes=True, feature='ISA_ZFINX', rounding=True,
         fu=2, a_sel=0, b_sel=0, op=op)


def sext(value, width):
    return (value - (1 << width) if value & (1 << (width-1)) else value) & MASK32


def immediate(word, kind):
    if kind == 'I': return sext(word >> 20, 12)
    if kind == 'S': return sext((word >> 25 << 5) | ((word >> 7) & 31), 12)
    if kind == 'B': return sext(((word >> 31) << 12) | (((word >> 7) & 1) << 11) |
                               (((word >> 25) & 63) << 5) | (((word >> 8) & 15) << 1), 13)
    if kind == 'U': return word & 0xFFFFF000
    if kind == 'J': return sext(((word >> 31) << 20) | (((word >> 12) & 255) << 12) |
                               (((word >> 20) & 1) << 11) | (((word >> 21) & 1023) << 1), 21)
    if kind == 'SHAMT': return (word >> 20) & 31
    if kind == 'ZIMM': return (word >> 15) & 31
    return 0


def decode(word, params):
    candidates = [r for r in RULES if word & r.mask == r.match and
                  (not r.feature or params[r.feature]) and
                  (not r.rounding or (word >> 12) & 7 in (0, 1, 2, 3, 4, 7))]
    assert len(candidates) <= 1, (hex(word), candidates)
    result = dict(SAFE, native=0, illegal=1, illegal_reg=0)
    if not candidates:
        return result, None
    r = candidates[0]
    sources = [(word >> shift) & 31 for shift in (15, 20, 27)]
    rd = (word >> 7) & 31
    bad = params['ISA_E'] and ((r.writes and rd >= 16) or
                               any(r.sources & (1 << n) and reg >= 16 for n, reg in enumerate(sources)))
    result.update(native=1, illegal=int(bool(bad)), illegal_reg=int(bool(bad)))
    if not bad:
        result.update(r.props)
        result.update(rs_used=r.sources, rd_we=int(r.writes), rd=rd if r.writes else 0,
                      imm=immediate(word, r.immediate))
        result.update({f'rs{n+1}': reg if r.sources & (1 << n) else 0 for n, reg in enumerate(sources)})
        if r.rounding:
            result['rm'] = (word >> 12) & 7
        if result['wb_kind'] == 1:
            result['csr_addr'] = word >> 20
    return result, r.name
