"""Units, coverage and waveform-window checks for workload power evidence."""
import gzip
import math
import re


def check_activity_clock(log):
    if re.search(r'STA-145[023]\b|clock .*?(?:has no vcd transitions|vcd period .*?differs from SDC)', log, re.I):
        raise ValueError('OpenSTA activity clock does not match the constrained clock; see opensta.log')


def annotation(text, minimum=0.99):
    rows = re.findall(r'^(vcd|saif|input|unannotated)\s+(\d+)\s*$', text, re.M)
    counts = {name: int(value) for name, value in rows}
    if len(rows) != len(counts): raise ValueError('duplicate activity annotation counts')
    return activity_coverage(counts, minimum)


def activity_coverage(counts, minimum=0.99):
    if ('unannotated' not in counts or set(counts) - {'vcd', 'saif', 'input', 'unannotated'} or
            any(type(n) is not int or n < 0 for n in counts.values())):
        raise ValueError('invalid activity pin counts')
    measured = counts.get('vcd', 0)
    total = sum(counts.values())
    fraction = measured / total if total else 0
    if not 0 < minimum <= 1 or not total or fraction < minimum:
        raise ValueError(f'insufficient measured pin activity: {measured}/{total} ({fraction:.2%}); require {minimum:.2%}')
    return dict(counts=counts, measured_pin_fraction=fraction, minimum=minimum)


def energy(power, cycles, retired, period_ns):
    values = power['Total']
    for field in ('internal', 'switching', 'leakage', 'total'):
        if not isinstance(values[field], (int, float)) or not math.isfinite(values[field]) or values[field] < 0:
            raise ValueError('invalid OpenSTA power: ' + field)
    if (type(cycles) is not int or type(retired) is not int or
            not all(math.isfinite(n) and n > 0 for n in (cycles, retired, period_ns))):
        raise ValueError('energy requires a nonempty measured window and positive period')
    internal, switching, leakage = (values[n] for n in ('internal', 'switching', 'leakage'))
    dynamic = internal + switching
    if not math.isclose(values['total'], dynamic + leakage, rel_tol=1e-5, abs_tol=1e-15):
        raise ValueError('inconsistent OpenSTA total power')
    seconds = cycles * period_ns * 1e-9
    return dict(internal_power_w=internal, switching_power_w=switching,
                dynamic_power_w=dynamic, leakage_power_w=leakage, total_power_w=values['total'],
                duration_s=seconds, dynamic_energy_j=dynamic * seconds,
                leakage_energy_j=leakage * seconds, total_energy_j=values['total'] * seconds,
                dynamic_energy_per_instruction_j=dynamic * seconds / retired)


def vcd_window(path):
    first, last, tail = None, None, b''
    with gzip.open(path, 'rb') as stream:
        header = stream.read(65536)
        timescale = bool(re.search(rb'\$timescale\s+1\s*ps\s+\$end', header))
        chunk = header
        while chunk:
            block = tail + chunk
            split = block.rfind(b'\n') + 1
            for match in re.finditer(rb'^#(\d+)\s*$', block[:split], re.M):
                last = int(match[1])
                if first is None: first = last
            tail = block[split:]
            chunk = stream.read(4 * 1024 * 1024)
    if tail or not timescale:
        raise ValueError('invalid or truncated activity VCD, or unsupported timescale')
    return first, last
