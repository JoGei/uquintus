"""Shared byte-interval PMP permission oracle for standalone and integration tests."""

OFF, TOR, NA4, NAPOT = range(4)
LEGAL_PERMISSIONS = (0, 1, 3, 4, 5, 7)  # W without R is reserved.


def config(mode, permissions=7, locked=False):
    return (int(locked) << 7) | (mode << 3) | permissions


def napot(base, byte_count):
    assert byte_count >= 8 and byte_count & (byte_count - 1) == 0
    assert base % byte_count == 0
    return (base >> 2) | ((byte_count >> 3) - 1)


def region(configs, addresses, entry):
    mode = (configs[entry] >> 3) & 3
    if mode == OFF:
        return range(0)
    encoded = addresses[entry]
    if mode == TOR:
        return range(addresses[entry - 1] * 4 if entry else 0, encoded * 4)
    if mode == NA4:
        return range(encoded * 4, encoded * 4 + 4)
    trailing = 0
    while trailing < 32 and (encoded >> trailing) & 1:
        trailing += 1
    byte_count = 1 << (trailing + 3)
    base = (encoded * 4 // byte_count) * byte_count
    return range(base, base + byte_count)


def permitted(enabled, configs, addresses, address, size, access, machine):
    if not enabled:
        return True
    if size == 3 or access == 0 or address + (1 << size) > 1 << 32:
        return False
    touched = range(address, address + (1 << size))
    for entry, cfg in enumerate(configs):
        selected = region(configs, addresses, entry)
        membership = [byte in selected for byte in touched]
        if any(membership):
            return all(membership) and (
                (machine and not cfg & 0x80) or (cfg & access) == access)
    return bool(machine)
