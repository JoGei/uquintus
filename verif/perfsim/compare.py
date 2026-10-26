#!/usr/bin/env python3
"""Compare ETISS instruction streams and qualified timing windows with RTL."""
import argparse
import csv
import hashlib
import json
from itertools import zip_longest
from pathlib import Path
import struct
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sim/common'))
from benchmark_prediction import trace_records
from rvfi_trace import read_trace


def iss_records(path):
    with Path(path).open(newline='') as stream:
        for number, row in enumerate(csv.reader(stream), 1):
            if len(row) != 3:
                raise ValueError('malformed ETISS instruction trace')
            index, pc, instruction = map(int, row)
            if index != number or not 0 <= pc < 2**32 or pc & 1 or not 0 <= instruction < 2**32:
                raise ValueError('invalid ETISS trace index/address/encoding')
            yield pc, instruction


def compare_streams(iss, rtl):
    count = 0
    for count, (left, right) in enumerate(zip_longest(iss, rtl), 1):
        if left != right:
            raise ValueError(f'instruction {count}: ETISS {left}, RTL {right}')
    if not count:
        raise ValueError('empty instruction trace')
    return count


def memory_instruction(word):
    """Fast RTL traces read four bytes at PC, including the next C instruction.

    ETISS/RVFI record only the original instruction encoding, zero extended.
    Discard following bytes rather than comparing them as part of a 16-bit op.
    """
    return word if word & 3 == 3 else word & 0xffff


def through_marker(records, stop):
    """Counter formatting after stop may legitimately execute different paths."""
    for row in records:
        yield row
        if row[0] == stop:
            return
    raise ValueError('instruction trace did not reach the stop marker')


def cycle_error(estimate, actual):
    if any(type(x) is not int or x <= 0 for x in (estimate, actual)):
        raise ValueError('cycle counts must be positive integers')
    return dict(estimated_cycles=estimate, rtl_cycles=actual,
                signed_cycles=estimate-actual, absolute_cycles=abs(estimate-actual),
                relative_error=(estimate-actual)/actual,
                absolute_relative_error=abs(estimate-actual)/actual)


def stream_signature(records):
    digest = hashlib.sha256()
    count = 0
    for count, (pc, code) in enumerate(records, 1):
        digest.update(struct.pack('<II', pc, code))
    if not count:
        raise ValueError('empty instruction trace')
    return count, digest.hexdigest()


def compare(perfsim, rtl, stream_cache=None):
    perfsim, rtl = Path(perfsim).resolve(), Path(rtl).resolve()
    sim = json.loads((perfsim/'report.json').read_text())
    rtl_record = json.loads((rtl/('report.json' if (rtl/'report.json').is_file() else 'run.json')).read_text())
    if sim['kind'] != 'perfsim' or sim['status'] != 'passed' or rtl_record['status'] != 'passed':
        raise ValueError('comparison requires successful perfsim and RTL runs')
    if sim['configuration']['parameters'] != yaml.safe_load((rtl/'config.yml').read_text()):
        raise ValueError('hardware configurations differ')
    if sim['workload'] != rtl_record.get('workload', rtl_record.get('elf', {}).get('sha256')):
        raise ValueError('executable hashes differ')
    trace = perfsim/'trace.csv'
    if not trace.is_file():
        trace = Path(sim['shared_execution'])/'trace.csv'
    binary = (rtl/'retire.bin').is_file()
    rtl_trace = rtl/('retire.bin' if binary else 'rvfi.jsonl')
    if not binary:
        events = read_trace(rtl/'rvfi.jsonl')
        if any(e['type'] == 'interrupt' or e.get('rvfi_trap') for e in events):
            raise ValueError('initial comparison profile excludes traps/interrupts')
    if (rtl/'traps.csv').is_file():
        sim_traps=perfsim/'traps.csv'
        if not sim_traps.is_file():sim_traps=Path(sim['shared_execution'])/'traps.csv'
        if sim_traps.read_bytes()!=(rtl/'traps.csv').read_bytes():
            raise ValueError('synchronous trap PC/cause/tval sequences differ')
    stop = json.loads((perfsim/'workload.json').read_text())['stop']
    def streams():
        instructions = (((pc, memory_instruction(insn)) for _, pc, insn in trace_records(rtl_trace)) if binary else
                        ((e['rvfi_pc_rdata'], e['rvfi_insn']) for e in events if e['type']=='instruction'))
        iss = iss_records(trace)
        return (through_marker(iss, stop), through_marker(instructions, stop)) if stop else (iss, instructions)
    if stream_cache is None:
        count = compare_streams(*streams())
    else:
        # A batch shares one immutable ETISS stream. Hash its normalized prefix
        # once; each RTL stream is still read/checked in full. Cache lives only
        # in this invocation and is invalidated by file metadata/marker changes.
        signatures = []
        for path, records in zip((trace, rtl_trace), streams()):
            stat = path.stat()
            key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, stop)
            if key not in stream_cache:
                stream_cache[key] = stream_signature(records)
            signatures.append(stream_cache[key])
        count = signatures[0][0] if signatures[0]==signatures[1] else compare_streams(*streams())
    result = dict(status='passed', instruction_stream='exact PC/original-encoding match',
                  instructions=count, perfsim=str(perfsim), rtl=str(rtl),
                  model_status='uncalibrated',
                  scope=('Prefix through stop marker; excludes timing-dependent output after stop. '
                         if stop else 'Whole execution. ') +
                        'Instruction-stream comparison; does not compare all architectural effects.')
    if (rtl/'benchmark.json').is_file():
        bench = json.loads((rtl/'benchmark.json').read_text())
        memory = bench.get('memory', {})
        modeled = sim['context']['memory']
        if 'memory_environment' in bench:
            same_memory=bench['memory_environment']==sim['context'].get('memory_environment')
        else:
            from memory import load as load_memory
            same_memory=(memory.get('imem_latency')==modeled['imem_response_cycles'] and
                         memory.get('dmem_latency')==modeled['dmem_response_cycles'] and
                         (not sim['context'].get('memory_environment') or
                          sim['context']['memory_environment']==load_memory(imem=modeled['imem_response_cycles'],dmem=modeled['dmem_response_cycles'])))
        if (bench.get('status') != 'passed' or not same_memory or
                not sim['context']['measurement'].startswith('(start, stop]')):
            raise ValueError('timing comparison requires matching benchmark memory/window contracts')
        metrics = {m['name']: m['value'] for m in sim['metrics']}
        if metrics['instructions'] != bench['window']['retired']:
            raise ValueError('timing windows have different instruction counts')
        result['timing_error'] = cycle_error(metrics['estimated_cycles'], bench['window']['cycles'])
    (perfsim/'rtl-comparison.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('perfsim_run', type=Path)
    parser.add_argument('rtl_run', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(compare(args.perfsim_run, args.rtl_run), indent=2))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f'perfsim comparison: {error}\n')
