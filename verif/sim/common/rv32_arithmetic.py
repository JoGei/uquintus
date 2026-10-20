"""Mathematical execution models shared by arithmetic component scoreboards."""

MASK = (1 << 32) - 1
# ALU funct3 with a normalized modifier bit for SUB/SRA.
ALU_OPS = {'add': 0, 'sll': 1, 'slt': 2, 'sltu': 3, 'xor': 4,
           'srl': 5, 'or': 6, 'and': 7, 'sub': 8, 'sra': 13}


def signed(value):
    return value - (1 << 32) if value & (1 << 31) else value


def alu_result(op, a, b):
    """RV32 results independent of RTL sharing, carry bits, or shift wiring."""
    amount = b % 32
    if op == ALU_OPS['add']:
        result = a + b
    elif op == ALU_OPS['sub']:
        result = a - b
    elif op == ALU_OPS['sll']:
        result = a << amount
    elif op == ALU_OPS['srl']:
        result = a >> amount
    elif op == ALU_OPS['sra']:
        result = signed(a) >> amount
    elif op == ALU_OPS['slt']:
        result = int(signed(a) < signed(b))
    elif op == ALU_OPS['sltu']:
        result = int(a < b)
    elif op == ALU_OPS['xor']:
        result = a ^ b
    elif op == ALU_OPS['or']:
        result = a | b
    elif op == ALU_OPS['and']:
        result = a & b
    else:
        result = 0
    return result & MASK


def muldiv_result(op, a, b):
    """RV32 M arithmetic independent of RTL iteration steps."""
    if op < 4:
        lhs = signed(a) if op in (1, 2) else a
        rhs = signed(b) if op == 1 else b
        product = lhs * rhs
        return (product if op == 0 else product >> 32) & MASK
    lhs, rhs = (signed(a), signed(b)) if op in (4, 6) else (a, b)
    if rhs == 0:
        return MASK if op < 6 else a
    quotient = abs(lhs) // abs(rhs)
    if (lhs < 0) != (rhs < 0):
        quotient = -quotient
    return (quotient if op < 6 else lhs - quotient * rhs) & MASK
