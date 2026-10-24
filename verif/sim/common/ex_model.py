"""External EX contract model shared by stage and parent-pipeline scoreboards."""

from fpu_model import result as fpu_result
from rv32_arithmetic import ALU_OPS, alu_result, muldiv_result

FU_ALU, FU_MULDIV, FU_FPU, FU_PASS = range(4)
MAC = 8


def assert_outcome(actual, expected):
    """Faulting instructions carry status/identity, not usable result data."""
    assert actual[2:] == expected[2:], (actual, expected)
    if not expected[4]:
        assert actual[:2] == expected[:2], (actual, expected)


def token(**updates):
    payload = dict(fu=FU_ALU, op=0, a=0, b=0, c=0, rm=0, pass_data=0,
                   store_data=0, instr=0x33, exception_valid=0,
                   exception_cause=0, exception_tval=0, pc=0x1000, rd=1)
    payload.update(updates)
    payload.setdefault('muldiv_a', payload['a'])
    payload.setdefault('muldiv_b', payload['b'])
    return payload


def outcome(payload, params):
    """Result/store/flags and precise exception payload, without unit timing state."""
    fu, op = payload['fu'], payload['op']
    if payload['exception_valid']:
        cause, tval = payload['exception_cause'], payload['exception_tval']
    elif ((fu == FU_ALU and op not in ALU_OPS.values()) or
          (fu == FU_MULDIV and (not params['ISA_M'] or (op not in range(8) and not (op == MAC and params['MUA_MUL'] in (13,))))) or
          (fu == FU_FPU and (not params['ISA_ZFINX'] or op not in range(22) or
              ((op <= 8 or op >= 18) and payload['rm'] > 4)))):
        cause, tval = 2, payload['instr']
    else:
        if fu == FU_FPU:
            value, flags = fpu_result(op, payload['a'], payload['b'], payload['c'], payload['rm'] if payload['rm'] < 5 else 0)
            return (value, payload['store_data'], 1, flags, 0, 0, 0)
        value = (alu_result(op, payload['a'], payload['b']) if fu == FU_ALU else
                 ((payload['muldiv_a'] * payload['muldiv_b'] + payload['c']) & 0xffffffff) if fu == FU_MULDIV and op == MAC else
                 muldiv_result(op, payload['muldiv_a'], payload['muldiv_b']) if fu == FU_MULDIV else
                 payload['pass_data'])
        return (value, payload['store_data'], 0, 0, 0, 0, 0)
    return (0, 0, 0, 0, 1, cause, tval)


def cycles(payload, params):
    if payload['fu'] == FU_FPU and not outcome(payload, params)[4]:
        return None  # Backend handshake defines completion, independently of operands.
    if outcome(payload, params)[4] or payload['fu'] != FU_MULDIV:
        return 1
    factor = params['MUA_MULDIV_ITERUNROLL']
    if payload['op'] == MAC:
        return 1
    if payload['op'] >= 4:
        return (2 + factor - 1) // factor + 32 // factor + 1
    return {2: 32 // factor, 3: 1, 13: 1}[params['MUA_MUL']]


def split_multiply(payload, params):
    return (params['ISA_M'] and params['MUA_MUL'] in (13,) and
            payload['fu'] == FU_MULDIV and (payload['op'] in range(4) or (params['MUA_MUL'] in (13,) and payload['op'] == MAC)))


def random_token(rng, index, params):
    fu = rng.choice([FU_ALU, FU_ALU, FU_MULDIV, FU_PASS, FU_FPU])
    op = rng.choice(list(ALU_OPS.values())) if fu == FU_ALU else rng.randrange(22) if fu == FU_FPU else rng.randrange(9 if params['MUA_MUL'] in (13,) else 8)
    return token(fu=fu, op=op, a=rng.getrandbits(32), b=rng.getrandbits(32),
                 muldiv_a=rng.getrandbits(32), muldiv_b=rng.getrandbits(32),
                 c=rng.getrandbits(32), rm=rng.randrange(8),
                 pass_data=rng.getrandbits(32), store_data=rng.getrandbits(32),
                 instr=rng.getrandbits(32), exception_valid=int(rng.randrange(16) == 0),
                 exception_cause=rng.randrange(16), exception_tval=rng.getrandbits(32),
                 pc=0x1000 + 4 * index, rd=rng.randrange(32))
