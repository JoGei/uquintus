"""RV32C oracle using immediate bit-position maps and assembly-level operands."""

FIELDS = {
    'ci': (2, 3, 4, 5, 6, 12),
    'spn': (None, None, 6, 5, 11, 12, 7, 8, 9, 10),
    'word': (None, None, 6, 10, 11, 12, 5),
    'sp': (None, None, None, None, 6, 2, 5, 3, 4, 12),
    'jump': (None, 3, 4, 5, 11, 2, 7, 6, 9, 10, 8, 12),
    'branch': (None, 3, 4, 10, 11, 2, 5, 6, 12),
    'lwsp': (None, None, 4, 5, 6, 12, 2, 3),
    'swsp': (None, None, 9, 10, 11, 12, 7, 8),
}


def immediate(c, field, signed=False):
    positions = FIELDS[field]
    value = sum(((c >> source) & 1) << dest for dest, source in enumerate(positions)
                if source is not None)
    return value-(1 << len(positions)) if signed and value >> (len(positions)-1) else value


def assemble(op, rd=0, rs1=0, rs2=0, imm=0):
    if op in ('addi', 'andi', 'slli', 'srli', 'srai', 'lw', 'jalr'):
        codes = {'addi': (0x13,0), 'andi': (0x13,7), 'slli': (0x13,1),
                 'srli': (0x13,5), 'srai': (0x13,5), 'lw': (3,2), 'jalr': (0x67,0)}
        opcode, funct3 = codes[op]
        imm = imm | 0x400 if op == 'srai' else imm
        return (imm & 4095) << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode
    if op in ('add', 'sub', 'xor', 'or', 'and'):
        return ((0x20 if op == 'sub' else 0) << 25 | rs2 << 20 | rs1 << 15 |
                {'add':0,'sub':0,'xor':4,'or':6,'and':7}[op] << 12 | rd << 7 | 0x33)
    if op == 'lui':
        return (imm & 0xFFFFF000) | rd << 7 | 0x37
    if op == 'jal':
        value = imm & 0x1FFFFF
        return ((value >> 20) << 31 | ((value >> 1) & 1023) << 21 |
                ((value >> 11) & 1) << 20 | ((value >> 12) & 255) << 12 | rd << 7 | 0x6F)
    if op in ('beq', 'bne'):
        value = imm & 8191
        return ((value >> 12) << 31 | ((value >> 5) & 63) << 25 | rs2 << 20 |
                rs1 << 15 | int(op == 'bne') << 12 | ((value >> 1) & 15) << 8 |
                ((value >> 11) & 1) << 7 | 0x63)
    if op == 'sw':
        value = imm & 4095
        return (value >> 5 << 25 | rs2 << 20 | rs1 << 15 | 2 << 12 | (value & 31) << 7 | 0x23)
    if op == 'ebreak':
        return 0x00100073
    raise AssertionError(op)


def compressed(c):
    """Return mnemonic, expansion, HINT; None means unsupported/reserved."""
    q, group = c & 3, c >> 13
    rd, rs2 = (c >> 7) & 31, (c >> 2) & 31
    base, small = 8+((c >> 7) & 7), 8+((c >> 2) & 7)
    ci = immediate(c, 'ci', signed=True)
    high = bool(c & 0x1000)
    if (q,group) == (0,0):
        offset = immediate(c, 'spn')
        return ('c.addi4spn', assemble('addi',rd=small,rs1=2,imm=offset),False) if offset else None
    if q == 0 and group in (2,6):
        op = 'lw' if group == 2 else 'sw'
        return 'c.'+op, assemble(op,rd=small,rs1=base,rs2=small,imm=immediate(c,'word')),False
    if q == 1:
        if group == 0:
            return ('c.nop' if rd == 0 and ci == 0 else 'c.addi',
                    assemble('addi',rd=rd,rs1=rd,imm=ci), (rd == 0) != (ci == 0))
        if group in (1,5):
            return ('c.jal' if group == 1 else 'c.j',
                    assemble('jal',rd=int(group == 1),imm=immediate(c,'jump',True)),False)
        if group == 2:
            return 'c.li',assemble('addi',rd=rd,imm=ci),rd == 0
        if group == 3:
            if rd == 2:
                offset = immediate(c,'sp',True)
                return ('c.addi16sp',assemble('addi',rd=2,rs1=2,imm=offset),False) if offset else None
            return ('c.lui',assemble('lui',rd=rd,imm=ci*4096),rd == 0) if ci else None
        if group == 4:
            kind = (c >> 10) & 3
            if kind == 2:
                return 'c.andi',assemble('andi',rd=base,rs1=base,imm=ci),False
            if high:
                return None
            if kind in (0,1):
                op = ('srli','srai')[kind]
                return 'c.'+op,assemble(op,rd=base,rs1=base,imm=rs2),rs2 == 0
            op = ('sub','xor','or','and')[(c >> 5) & 3]
            return 'c.'+op,assemble(op,rd=base,rs1=base,rs2=small),False
        if group in (6,7):
            op = 'beq' if group == 6 else 'bne'
            return 'c.'+op+'z',assemble(op,rs1=base,imm=immediate(c,'branch',True)),False
    if q == 2:
        if group == 0:
            return None if high else ('c.slli',assemble('slli',rd=rd,rs1=rd,imm=rs2),rd == 0 or rs2 == 0)
        if group == 2:
            return ('c.lwsp',assemble('lw',rd=rd,rs1=2,imm=immediate(c,'lwsp')),False) if rd else None
        if group == 4:
            if rs2:
                return ('c.add' if high else 'c.mv',assemble('add',rd=rd,rs1=rd if high else 0,rs2=rs2),rd == 0)
            if rd:
                return ('c.jalr' if high else 'c.jr',assemble('jalr',rd=int(high),rs1=rd),False)
            return ('c.ebreak',assemble('ebreak'),False) if high else None
        if group == 6:
            return 'c.swsp',assemble('sw',rs1=2,rs2=rs2,imm=immediate(c,'swsp')),False
    return None


def expand(word, enabled):
    if not enabled or word & 3 == 3:
        return dict(instr=word,original_instr=word,compressed=0,illegal=0,hint=0), 'native'
    c = word & 0xFFFF
    entry = compressed(c)
    return (dict(instr=entry[1] if entry else 0, original_instr=c,
                 compressed=1,illegal=int(entry is None),hint=int(bool(entry and entry[2]))),
            entry[0] if entry else 'illegal')
