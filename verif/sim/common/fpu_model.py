"""Scalar Zfinx oracle: exact rational arithmetic and one binary32 rounding.

Independent of CVFPU's implementation and latency. No host floating-point
arithmetic is used, including for fused operations and square root.
"""
from fractions import Fraction

MASK = 0xffffffff
SIGN = 0x80000000
QNAN = 0x7fc00000
NV, DZ, OF, UF, NX = 16, 8, 4, 2, 1
NAMES = ('fadd', 'fsub', 'fmul', 'fdiv', 'fsqrt', 'fmadd', 'fmsub', 'fnmsub',
         'fnmadd', 'fsgnj', 'fsgnjn', 'fsgnjx', 'fmin', 'fmax', 'feq', 'flt',
         'fle', 'fclass', 'fcvt_w_s', 'fcvt_wu_s', 'fcvt_s_w', 'fcvt_s_wu')


def is_nan(x):
    return (x & 0x7fffffff) > 0x7f800000


def is_snan(x):
    return is_nan(x) and not (x & 0x400000)


def is_inf(x):
    return (x & 0x7fffffff) == 0x7f800000


def is_zero(x):
    return not (x & 0x7fffffff)


def value(x):
    """Exact value of a finite binary32 encoding."""
    assert not is_nan(x) and not is_inf(x)
    exponent = (x >> 23) & 255
    significand = (x & 0x7fffff) | (0x800000 if exponent else 0)
    power = (exponent - 127 if exponent else -126) - 23
    magnitude = Fraction(significand << power) if power >= 0 else Fraction(significand, 1 << -power)
    return -magnitude if x & SIGN else magnitude


def rounded_integer(magnitude, negative, rm):
    whole, remainder = divmod(magnitude.numerator, magnitude.denominator)
    twice = remainder * 2
    increment = ((rm == 0 and (twice > magnitude.denominator or
                               (twice == magnitude.denominator and whole & 1))) or
                 (rm == 2 and negative and remainder != 0) or
                 (rm == 3 and not negative and remainder != 0) or
                 (rm == 4 and twice >= magnitude.denominator))
    return whole + int(increment), remainder != 0


def round_binary32(number, rm, zero_sign=0):
    if not number:
        return (SIGN if zero_sign else 0), 0
    negative = number < 0
    magnitude = abs(number)
    exponent = magnitude.numerator.bit_length() - magnitude.denominator.bit_length()
    power = Fraction(1 << exponent) if exponent >= 0 else Fraction(1, 1 << -exponent)
    if magnitude < power:
        exponent -= 1
    # IEEE tininess-after-rounding uses destination precision with an
    # unbounded exponent range. Inspecting the final encoded exponent would
    # incorrectly suppress UF for some results rounding to minimum normal.
    tiny = False
    if exponent < -126:
        unbounded, _ = rounded_integer(magnitude * (1 << (23 - exponent)), negative, rm)
        tiny = exponent + int(unbounded >= 1 << 24) < -126
    scale = 23 - max(exponent, -126)
    scaled = magnitude * (1 << scale) if scale >= 0 else magnitude / (1 << -scale)
    significand, inexact = rounded_integer(scaled, negative, rm)
    encoded_exponent = max(exponent, -126)
    if significand >= 1 << 24:
        significand >>= 1
        encoded_exponent += 1
    sign = SIGN if negative else 0
    if encoded_exponent > 127:
        infinity = rm in (0, 4) or (rm == 2 and negative) or (rm == 3 and not negative)
        return sign | (0x7f800000 if infinity else 0x7f7fffff), OF | NX
    bits = ((encoded_exponent + 127) << 23) + significand - (1 << 23) if significand >= 1 << 23 else significand
    return sign | bits, (NX | (UF if tiny else 0)) if inexact else 0


def compare(a, b):
    """Order non-NaNs, treating both zero signs as equal."""
    if is_inf(a):
        return 0 if a == b else (-1 if a & SIGN else 1)
    if is_inf(b):
        return 1 if b & SIGN else -1
    av, bv = value(a), value(b)
    return (av > bv) - (av < bv)


def result(op, a, b=0, c=0, rm=0):
    """Return (32-bit result, architectural NV/DZ/OF/UF/NX flags)."""
    assert op in range(22) and rm in range(5)
    a, b, c = a & MASK, b & MASK, c & MASK
    if op in (9, 10, 11):
        sign = b & SIGN
        if op == 10:
            sign ^= SIGN
        elif op == 11:
            sign ^= a & SIGN
        return (a & ~SIGN) | sign, 0
    if op == 17:
        negative = bool(a & SIGN)
        if is_nan(a):
            index = 8 if is_snan(a) else 9
        elif is_inf(a):
            index = 0 if negative else 7
        elif is_zero(a):
            index = 3 if negative else 4
        elif not (a & 0x7f800000):
            index = 2 if negative else 5
        else:
            index = 1 if negative else 6
        return 1 << index, 0
    if op in (12, 13):
        flags = NV if is_snan(a) or is_snan(b) else 0
        if is_nan(a) or is_nan(b):
            return (QNAN if is_nan(a) and is_nan(b) else b if is_nan(a) else a), flags
        if is_zero(a) and is_zero(b):
            return ((a & b) if op == 13 else (a | b)), flags
        return (a if (compare(a, b) < 0) == (op == 12) else b), flags
    if op in (14, 15, 16):
        if is_nan(a) or is_nan(b):
            return 0, NV if op != 14 or is_snan(a) or is_snan(b) else 0
        order = compare(a, b)
        return int(order == 0 if op == 14 else order < 0 if op == 15 else order <= 0), 0
    if op in (18, 19):
        unsigned = op == 19
        low, high = (0, MASK) if unsigned else (-(1 << 31), (1 << 31) - 1)
        if is_nan(a) or is_inf(a):
            return (high if is_nan(a) or not (a & SIGN) else low) & MASK, NV
        number = value(a)
        integer, inexact = rounded_integer(abs(number), number < 0, rm)
        integer = -integer if number < 0 else integer
        if not low <= integer <= high:
            return min(high, max(low, integer)) & MASK, NV
        return integer & MASK, NX if inexact else 0
    if op in (20, 21):
        integer = a - (1 << 32) if op == 20 and a & SIGN else a
        return round_binary32(Fraction(integer), rm)

    operands = (a,) if op == 4 else (a, b, c) if op in range(5, 9) else (a, b)
    flags = NV if any(is_snan(x) for x in operands) else 0
    invalid_product = op in (2, 5, 6, 7, 8) and ((is_zero(a) and is_inf(b)) or (is_inf(a) and is_zero(b)))
    if any(is_nan(x) for x in operands):
        return QNAN, flags | (NV if invalid_product else 0)
    if op in (0, 1):
        if op == 1:
            b ^= SIGN
        if is_inf(a) and is_inf(b) and ((a ^ b) & SIGN):
            return QNAN, NV
        if is_inf(a) or is_inf(b):
            return a if is_inf(a) else b, 0
        number = value(a) + value(b)
        zero_sign = bool(a & SIGN) if is_zero(a) and is_zero(b) and not ((a ^ b) & SIGN) else rm == 2
        return round_binary32(number, rm, zero_sign)
    if op == 2:
        if invalid_product:
            return QNAN, NV
        sign = (a ^ b) & SIGN
        if is_inf(a) or is_inf(b):
            return sign | 0x7f800000, 0
        return round_binary32(value(a) * value(b), rm, sign)
    if op == 3:
        sign = (a ^ b) & SIGN
        if (is_zero(a) and is_zero(b)) or (is_inf(a) and is_inf(b)):
            return QNAN, NV
        if is_inf(a) or is_zero(b):
            return sign | 0x7f800000, DZ if is_zero(b) and not is_inf(a) else 0
        if is_inf(b):
            return sign, 0
        return round_binary32(value(a) / value(b), rm, sign)
    if op == 4:
        if a & SIGN and not is_zero(a):
            return QNAN, NV
        if is_zero(a) or is_inf(a):
            return a, 0
        target = value(a)
        low, high = 0, 0x7f7fffff
        while low < high:
            mid = (low + high + 1) // 2
            if value(mid) ** 2 <= target:
                low = mid
            else:
                high = mid - 1
        if value(low) ** 2 == target:
            return low, 0
        midpoint_squared = ((value(low) + value(low + 1)) / 2) ** 2
        increment = (rm == 3 or (rm in (0, 4) and
                     (target > midpoint_squared or (target == midpoint_squared and (rm == 4 or low & 1)))))
        return low + int(increment), NX
    # Fused multiply-add: retain the exact product before the single rounding.
    product_sign = ((a ^ b) & SIGN) ^ (SIGN if op in (7, 8) else 0)
    c ^= SIGN if op in (6, 8) else 0
    if invalid_product or ((is_inf(a) or is_inf(b)) and is_inf(c) and ((product_sign ^ c) & SIGN)):
        return QNAN, NV
    if is_inf(a) or is_inf(b):
        return product_sign | 0x7f800000, 0
    if is_inf(c):
        return c, 0
    product = value(a) * value(b) * (-1 if op in (7, 8) else 1)
    number = product + value(c)
    same_zero_sign = not product and is_zero(c) and not ((product_sign ^ c) & SIGN)
    return round_binary32(number, rm, bool(product_sign) if same_zero_sign else rm == 2)


def decode_instruction(instr):
    """Decode scalar Zfinx for the retirement oracle, without RTL controls."""
    opcode, funct, upper = instr & 127, (instr >> 12) & 7, instr >> 25
    if opcode in (0x43, 0x47, 0x4b, 0x4f):
        if (instr >> 25) & 3:
            raise ValueError('non-FP32 fused instruction')
        return (5 + (opcode - 0x43) // 4), 7, funct
    if opcode != 0x53:
        raise ValueError('not a scalar FP instruction')
    if upper in (0, 4, 8, 12):
        return upper // 4, 3, funct
    if upper == 0x2c and (instr >> 20) & 31 == 0:
        return 4, 1, funct
    if upper == 0x10 and funct < 3:
        return 9 + funct, 3, 0
    if upper == 0x14 and funct < 2:
        return 12 + funct, 3, 0
    if upper == 0x50 and funct < 3:
        return {2:14, 1:15, 0:16}[funct], 3, 0
    if upper == 0x70 and funct == 1 and (instr >> 20) & 31 == 0:
        return 17, 1, 0
    if upper in (0x60, 0x68) and (instr >> 20) & 31 < 2:
        return (18 if upper == 0x60 else 20) + ((instr >> 20) & 31), 1, funct
    raise ValueError('reserved scalar FP instruction')


def encode_instruction(op, rd, a, b=0, c=0, rm=0):
    """Encode native Zfinx test programs."""
    if op in range(5, 9):
        return c << 27 | b << 20 | a << 15 | rm << 12 | rd << 7 | (0x43 + 4*(op-5))
    if op < 4:
        upper, funct = 4*op, rm
    elif op == 4:
        upper, funct, b = 0x2c, rm, 0
    elif op in (9, 10, 11):
        upper, funct = 0x10, op-9
    elif op in (12, 13):
        upper, funct = 0x14, op-12
    elif op in (14, 15, 16):
        upper, funct = 0x50, {14:2,15:1,16:0}[op]
    elif op == 17:
        upper, funct, b = 0x70, 1, 0
    else:
        upper, funct, b = (0x60 if op < 20 else 0x68), rm, op & 1
    return upper << 25 | b << 20 | a << 15 | funct << 12 | rd << 7 | 0x53
