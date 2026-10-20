"""Byte-addressed memory and instruction-level expectations shared by LSU/MEM."""

MASK = (1 << 32) - 1


def access(**updates):
    fields = dict(we=0, op=2, addr=0x1000, wdata=0, instr=0x00002083, access_fault=0)
    fields.update(updates)
    return fields


def local_exception(req):
    if req['op'] not in ((0, 1, 2) if req['we'] else (0, 1, 2, 4, 5)):
        return 2, req['instr']
    size = 1 << (req['op'] % 4)
    if req['addr'] % size:
        return (6 if req['we'] else 4), req['addr']
    if req['access_fault']:
        return (7 if req['we'] else 5), req['addr']
    return None


class ByteMemory:
    def __init__(self):
        self.bytes = {}
        self.grants = 0

    def read_byte(self, addr):
        return self.bytes.get(addr, ((addr * 73) ^ (addr >> 3) ^ 0xA5) & 255)

    def word(self, base):
        return sum(self.read_byte(base + lane) << (8 * lane) for lane in range(4))

    def seed(self, base, value):
        for lane in range(4):
            self.bytes[base + lane] = (value >> (8 * lane)) & 255

    def check_request(self, req, packet):
        we, addr, data, be = packet
        base = req['addr'] - req['addr'] % 4
        size = 1 << (req['op'] % 4)
        lanes = set(range(req['addr'] % 4, req['addr'] % 4 + size))
        assert we == req['we'] and addr == base, (req, packet)
        assert be == sum(1 << lane for lane in lanes), (req, packet)
        if we:
            for byte, lane in enumerate(sorted(lanes)):
                assert (data >> (8 * lane)) & 255 == (req['wdata'] >> (8 * byte)) & 255
        else:
            assert data == 0

    def grant(self, req, packet):
        self.check_request(req, packet)
        self.grants += 1
        we, base, data, be = packet
        if we:
            # Model writes at grant, including killed/error transactions. The
            # LSU must never assume cancellation can undo external effects.
            for lane in range(4):
                if be & (1 << lane):
                    self.bytes[base + lane] = (data >> (8 * lane)) & 255
        return self.word(base)

    def result(self, req, error=False):
        fault = local_exception(req)
        if not fault and error:
            fault = (7 if req['we'] else 5), req['addr']
        if fault:
            return 0, 1, fault[0], fault[1]
        value = 0
        if not req['we']:
            size = 1 << (req['op'] % 4)
            value = sum(self.read_byte(req['addr'] + byte) << (8 * byte)
                        for byte in range(size))
            if req['op'] < 4 and value & (1 << (8 * size - 1)):
                value -= 1 << (8 * size)
        return value & MASK, 0, 0, 0
