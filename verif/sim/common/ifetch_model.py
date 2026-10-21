"""Instruction-word outcomes, independent of the request engine's control FSM."""

MASK = (1 << 32)-1


def word_address(address):
    return address & (MASK ^ 3)


def completion(address, data=0, denied=False, error=False):
    failed = bool(denied or error)
    return word_address(address), 0 if failed else data & MASK, int(failed)
