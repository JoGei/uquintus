"""Embench-IoT workload manifest validation; shared execution lives in benchmark.py."""
import re

import yaml

from pinned_archive import load_lock


def settings(port, name):
    data = yaml.safe_load((port / 'config.yml').read_text())
    fields = {'schema_version', 'name', 'validator', 'sources', 'port_sources',
              'compiler_flags', 'defines', 'profiles', 'libraries', 'memory', 'max_cycles'}
    if (not isinstance(data, dict) or set(data) != fields or data['schema_version'] != 2 or
            data['name'] != name or data['validator'] != 'embench'):
        raise ValueError('invalid Embench configuration/schema/validator')
    if (data['defines'] != {'CPU_MHZ': 1, 'WARMUP_HEAT': 1} or
            data['sources'] != ['support/beebsc.c'] or data['port_sources'] != ['uqu_port.c'] or
            data['libraries'] != ['m', 'c', 'gcc']):
        raise ValueError('Embench requires the pinned workload scale, warmup and real runtime libraries')
    if (not isinstance(data['compiler_flags'], list) or not data['compiler_flags'] or
            any(not isinstance(p, str) or not p.startswith('-') for p in data['compiler_flags'])):
        raise ValueError('compiler_flags must be a list of compiler options')
    if not isinstance(data['profiles'], dict) or not data['profiles']:
        raise ValueError('Embench needs an explicit workload manifest')
    for profile, workload in data['profiles'].items():
        if (not re.fullmatch(r'[a-z][a-z0-9-]*', profile) or not isinstance(workload, dict) or
                set(workload) != {'sources', 'arithmetic', 'local_scale_factor'} or
                workload['arithmetic'] not in ('integer', 'software_float') or
                type(workload['local_scale_factor']) is not int or workload['local_scale_factor'] < 1 or
                not isinstance(workload['sources'], list) or not workload['sources'] or
                any(not isinstance(p, str) or not re.fullmatch(
                    r'src/' + re.escape(profile) + r'/[a-zA-Z0-9_-]+\.c', p)
                    for p in workload['sources'])):
            raise ValueError('invalid Embench workload sources/arithmetic/scale')
    if (not isinstance(data['memory'], dict) or set(data['memory']) != {'imem_latency', 'dmem_latency'} or
            any(type(v) is not int or not 1 <= v <= 1000000 for v in data['memory'].values())):
        raise ValueError('memory latencies must be positive integer cycles')
    if type(data['max_cycles']) is not int or not 0 < data['max_cycles'] < 2**32:
        raise ValueError('benchmark max_cycles must fit the cycle-only 32-bit timer')
    lock = load_lock(port / 'lock.json')
    if lock['name'] != 'embench-iot':
        raise ValueError('Embench lock name differs from configuration')
    return port, data, lock


def verify_manifest(source, data):
    """Do not silently omit a benchmark, translation unit, or changed repeat count."""
    actual = {p.name for p in (source / 'src').iterdir() if p.is_dir()}
    if actual != set(data['profiles']):
        raise ValueError('Embench manifest must cover every pinned upstream workload')
    for name, workload in data['profiles'].items():
        actual = sorted(p.relative_to(source).as_posix() for p in (source / 'src' / name).glob('*.c'))
        scales = [int(v) for p in actual for v in re.findall(
            r'#define LOCAL_SCALE_FACTOR\s+(\d+)', (source / p).read_text())]
        if actual != workload['sources'] or scales != [workload['local_scale_factor']]:
            raise ValueError('Embench manifest differs from pinned sources or scale: ' + name)
