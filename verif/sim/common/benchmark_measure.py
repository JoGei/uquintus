"""ELF-bound benchmark windows and strict cycle-only CoreMark validation."""
import re


def software_compatible(built, selected):
    """Reuse identical machine code across microarchitecture experiments."""
    return ({k: v for k, v in built.items() if not k.startswith('MUA_')} ==
            {k: v for k, v in selected.items() if not k.startswith('MUA_')})


def marker_addresses(image):
    addresses = []
    for name in ('uqu_bench_start', 'uqu_bench_stop'):
        address = image.symbols.get(name)
        if address is None or address & 1 or not any(
                s.flags & 1 and s.address <= address and address + 4 <= s.address + s.size
                for s in image.segments):
            raise ValueError(f'benchmark needs executable marker {name}')
        instruction = sum(image.memory_byte(address + n) << (8*n) for n in range(4))
        # CSRRS rd,mcycle,x0: no counter writes and no inhibit changes.
        if instruction & 0xfffff07f != 0xb0002073 or not (instruction >> 7 & 31):
            raise ValueError(f'{name} must label a read of mcycle')
        addresses.append(address)
    if addresses[0] == addresses[1]:
        raise ValueError('benchmark markers must be distinct')
    return addresses


class BenchmarkWindow:
    def __init__(self, image):
        self.start_pc, self.stop_pc = marker_addresses(image)
        self.start = self.stop = None

    def retire(self, pc, cycle, retired, value, inhibited):
        if self.start is not None and self.stop is None and inhibited:
            raise ValueError('benchmark counters must remain enabled')
        if pc not in (self.start_pc, self.stop_pc):
            return
        if inhibited:
            raise ValueError('benchmark counters must remain enabled')
        point = dict(cycle=cycle, retired=retired, mcycle_low=value)
        if pc == self.start_pc:
            if self.start is not None or self.stop is not None:
                raise ValueError('benchmark start marker repeated')
            self.start = point
        else:
            if self.start is None or self.stop is not None:
                raise ValueError('benchmark stop marker out of order or repeated')
            self.stop = point

    def finish(self):
        if self.start is None or self.stop is None:
            raise ValueError('benchmark window incomplete')
        cycles = self.stop['cycle'] - self.start['cycle']
        retired = self.stop['retired'] - self.start['retired']
        if not 0 < cycles < 2**32 or retired <= 0:
            raise ValueError('invalid benchmark duration')
        if (self.stop['mcycle_low'] - self.start['mcycle_low']) & 0xffffffff != cycles:
            raise ValueError('software cycle delta disagrees with observed RTL cycles')
        return dict(start=self.start, stop=self.stop, cycles=cycles, retired=retired,
                    cpi=cycles / retired,
                    definition='retirement edges (start, stop]; includes timer call overhead')


def coremark_result(text, profile, iterations, cycles):
    expected = {'performance': ('e9f5', 'e714', '1fd7', '8e3a'),
                'validation': ('18f2', 'e3c1', '0747', '8d84')}[profile]
    fields = {}
    for name, expression in {
        'seedcrc': r'^seedcrc\s+: 0x([0-9a-f]{4})$',
        'crclist': r'^\[0\]crclist\s+: 0x([0-9a-f]{4})$',
        'crcmatrix': r'^\[0\]crcmatrix\s+: 0x([0-9a-f]{4})$',
        'crcstate': r'^\[0\]crcstate\s+: 0x([0-9a-f]{4})$',
        'crcfinal': r'^\[0\]crcfinal\s+: 0x([0-9a-f]{4})$',
        'iterations': r'^Iterations\s+: ([0-9]+)$',
        'ticks': r'^Total ticks\s+: ([0-9]+)$',
        'size': r'^CoreMark Size\s+: ([0-9]+)$',
    }.items():
        values = re.findall(expression, text, re.M)
        if len(values) != 1:
            raise ValueError(f'CoreMark missing/duplicate output: {name}')
        fields[name] = values[0]
    if tuple(fields[k] for k in ('seedcrc', 'crclist', 'crcmatrix', 'crcstate')) != expected:
        raise ValueError('CoreMark CRC validation failed')
    if int(fields['iterations']) != iterations or int(fields['ticks']) != cycles or int(fields['size']) != 666:
        raise ValueError('CoreMark workload/timing differs from the requested measurement')
    warning = 'ERROR! Must execute for at least 10 secs for a valid result!'
    if (text.count(warning) != 1 or text.count('Errors detected') != 1 or
            any('ERROR' in line for line in text.replace(warning, '').splitlines()) or
            'Cannot validate' in text or 'Correct operation validated' in text):
        raise ValueError('unexpected CoreMark diagnostic (only the cycle-only duration warning is allowed)')
    return dict(profile=profile, iterations=iterations, crc=fields,
                validation='passed', official_score=False,
                duration_warning=warning, cycles_per_iteration=cycles / iterations)


def read_log(image, memory):
    for name in ('uqu_bench_log', 'uqu_bench_log_size', 'uqu_bench_log_overflow'):
        if name not in image.symbols:
            raise ValueError(f'benchmark missing RAM log symbol {name}')
    def word(name):
        address = image.symbols[name]
        return sum(memory.get(address+n, 0) << (8*n) for n in range(4))
    size = word('uqu_bench_log_size')
    if word('uqu_bench_log_overflow') or not 0 < size < 4096:
        raise ValueError('benchmark RAM log overflow/empty/unsupported format')
    return bytes(memory.get(image.symbols['uqu_bench_log'] + n, 0)
                 for n in range(size)).decode('ascii')
