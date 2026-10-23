"""Diagnostic retirement traces and architectural-path prediction models.

Models describe history reuse and conflicts, not speculative RTL timing or CPI.
"""
import argparse
from collections import Counter, namedtuple
import hashlib
import json
from pathlib import Path
import struct
import html
from concurrent.futures import ProcessPoolExecutor, as_completed


MAGIC = b'UQUTRC01'
RECORD = struct.Struct('<III')


def trace_records(path):
    """Read bounded chunks; reject incomplete records and wrapped/repeated clocks."""
    previous = -1
    with Path(path).open('rb') as stream:
        if stream.read(8) != MAGIC:
            raise ValueError('invalid diagnostic retirement trace header')
        while chunk := stream.read(RECORD.size * 65536):
            if len(chunk) % RECORD.size:
                raise ValueError('truncated diagnostic retirement trace')
            for cycle, pc, instruction in RECORD.iter_unpack(chunk):
                if cycle <= previous or pc & 1:
                    raise ValueError('invalid retirement trace cycle/address')
                previous = cycle
                yield cycle, pc, instruction


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_trace(path, native):
    count, points = 0, {}
    for count, (cycle, pc, instruction) in enumerate(trace_records(path), 1):
        if cycle in (native['start']['cycle'], native['stop']['cycle']):
            points[cycle] = count
    if count != native['retired'] or any(points.get(native[name]['cycle']) != native[name]['retired']
                                         for name in ('start', 'stop')):
        raise ValueError('diagnostic retirement trace disagrees with native retirement/window counts')
    return dict(records=count, bytes=Path(path).stat().st_size, sha256=file_sha(path))


Event = namedtuple('Event', 'cycle pc kind taken target compressed')


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def control_flow(cycle, pc, instruction, next_pc):
    """Decode original RV32I/C bytes and infer outcomes from architectural next PC.

    A branch to its own fallthrough is ambiguous without a branch-result tap;
    reject it rather than inventing its taken state.
    """
    w = instruction
    compressed = w & 3 != 3
    length = 2 if compressed else 4
    kind, offset = None, None
    if not compressed:
        op = w & 127
        if op == 0x63:
            kind = 'conditional'
            offset = signed(((w >> 31) << 12) | ((w >> 7 & 1) << 11) |
                            ((w >> 25 & 63) << 5) | ((w >> 8 & 15) << 1), 13)
        elif op == 0x6f:
            kind = 'jal'
            offset = signed(((w >> 31) << 20) | ((w >> 12 & 255) << 12) |
                            ((w >> 20 & 1) << 11) | ((w >> 21 & 1023) << 1), 21)
        elif op == 0x67:
            kind = 'jalr'
    else:
        quadrant, funct = w & 3, w >> 13 & 7
        if quadrant == 1 and funct in (6, 7):
            kind = 'conditional'
            offset = signed(((w >> 12 & 1) << 8) | ((w >> 5 & 3) << 6) |
                            ((w >> 2 & 1) << 5) | ((w >> 10 & 3) << 3) |
                            ((w >> 3 & 3) << 1), 9)
        elif quadrant == 1 and funct in (1, 5):
            kind = 'jal'
            offset = signed(((w >> 12 & 1) << 11) | ((w >> 11 & 1) << 4) |
                            ((w >> 9 & 3) << 8) | ((w >> 8 & 1) << 10) |
                            ((w >> 7 & 1) << 6) | ((w >> 6 & 1) << 7) |
                            ((w >> 3 & 7) << 1) | ((w >> 2 & 1) << 5), 12)
        elif quadrant == 2 and funct == 4 and not (w >> 2 & 31) and w >> 7 & 31:
            kind = 'jalr'
    if kind is None:
        return None
    fallthrough = (pc + length) & 0xffffffff
    target = next_pc if offset is None else (pc + offset) & 0xffffffff
    if kind == 'conditional' and target == fallthrough:
        raise ValueError('cannot infer taken state for a branch to fallthrough')
    taken = kind != 'conditional' or next_pc != fallthrough
    if taken and next_pc != target:
        raise ValueError('retirement trace disagrees with encoded control-flow target')
    return Event(cycle, pc, kind, taken, target, compressed)


def read_events(path):
    events, previous = [], None
    for row in trace_records(path):
        if previous is not None:
            event = control_flow(*previous, row[1])
            if event is not None:
                events.append(event)
        previous = row
    return events


class Predictor:
    """Tagged, direct-mapped BTB and independent tagged two-bit direction table.

    None capacity means an unlimited PC map. Training follows the architectural
    path. Prior taken-target presence is an opportunity, not an H6 payload model.
    """
    def __init__(self, bp_entries, btb_entries, compressed=True):
        for size in (bp_entries, btb_entries):
            if size is not None and (type(size) is not int or size < 2 or size & (size - 1)):
                raise ValueError('prediction capacity must be a power of two >=2, or None')
        self.bp_entries, self.btb_entries = bp_entries, btb_entries
        self.offset = 1 if compressed else 2
        self.btb, self.bht = {}, {}

    def step(self, event, counters=None):
        pc, target, taken = event.pc, event.target, event.taken
        conditional = event.kind == 'conditional'
        ti = pc if self.btb_entries is None else (pc >> self.offset) & (self.btb_entries - 1)
        di = pc if self.bp_entries is None else (pc >> self.offset) & (self.bp_entries - 1)
        old_target, old_direction = self.btb.get(ti), self.bht.get(di)
        target_hit = old_target is not None and old_target[0] == pc
        direction_hit = old_direction is not None and old_direction[0] == pc
        direction = direction_hit and old_direction[1] >= 2
        predicts_taken = target_hit and (not old_target[2] or direction)
        correct_target = target_hit and old_target[1] == target
        if counters is not None:
            counters['control_flow'] += 1
            counters['taken'] += int(taken)
            counters['btb_hits'] += int(target_hit)
            counters['conditional_branches'] += int(conditional)
            counters['direction_errors'] += int(conditional and direction != taken)
            counters['next_pc_errors'] += int(not ((predicts_taken and taken and correct_target) or
                                                  (not predicts_taken and not taken)))
            counters['correct_taken_predictions'] += int(predicts_taken and taken and correct_target)
            counters['prior_target_opportunities'] += int(predicts_taken and taken and correct_target and old_target[3])
        self.btb[ti] = (pc, target, conditional, taken or (correct_target and old_target[3]))
        if conditional:
            count = old_direction[1] if direction_hit else None
            self.bht[di] = (pc, (2 if taken else 1) if count is None else
                           min(3, max(0, count + (1 if taken else -1))))
        else:
            # The RTL invalidates this indexed direction slot even on a tag miss.
            self.bht.pop(di, None)


def derived(counters):
    result = dict(counters)
    cf, conditional = result.get('control_flow', 0), result.get('conditional_branches', 0)
    result['btb_hit_percent'] = 100 * result.get('btb_hits', 0) / cf if cf else None
    result['next_pc_accuracy_percent'] = 100 * (cf - result.get('next_pc_errors', 0)) / cf if cf else None
    result['direction_accuracy_percent'] = (100 * (conditional - result.get('direction_errors', 0)) /
                                             conditional if conditional else None)
    return result


def simulate(events, start, stop, capacities=(16, 64, 256, 1024, None), compressed=True):
    cases = [(size, size) for size in capacities]
    if 16 in capacities and None in capacities:
        cases += [(16, None), (None, 16)]
    models = {(bp, btb, state): (Predictor(bp, btb, compressed), Counter())
              for bp, btb in cases for state in ('warm', 'window_cold')}
    for event in events:
        if event.cycle > stop:
            break
        measured = start < event.cycle <= stop
        for (_, _, state), (model, counts) in models.items():
            if state == 'warm' or measured:
                model.step(event, counts if measured else None)
    return [dict(bp_entries=bp, btb_entries=btb, state=state, **derived(counts))
            for (bp, btb, state), (_, counts) in models.items()]


def kernel_repetitions(path, events, native, repeats):
    """Locate nsichneu's outer loop from its observed backward conditional.

    Actual intervals are (retirement before loop target, loop-tail retirement].
    The first warmup visit is kernel-cold, with real startup state retained.
    """
    start, stop = native['start']['cycle'], native['stop']['cycle']
    backward = [e for e in events if start < e.cycle <= stop and
                e.kind == 'conditional' and e.target < e.pc]
    visits = Counter(e.pc for e in backward)
    taken = Counter(e.pc for e in backward if e.taken)
    # Many code-layout back edges are visited every repetition but never taken.
    # The outer loop repeats its back edge and exits on the final invocation.
    candidates = [pc for pc, count in visits.items()
                  if count == repeats and taken[pc] == repeats - 1]
    if len(candidates) != 1:
        raise ValueError('cannot uniquely locate nsichneu outer-loop boundary')
    tail = candidates[0]
    target = next(e.target for e in events if e.pc == tail)
    phases, active, previous_cycle, ordinal = [], None, None, 0
    for cycle, pc, instruction in trace_records(path):
        ordinal += 1
        if pc == target:
            if active is not None or previous_cycle is None:
                raise ValueError('overlapping/incomplete outer-loop interval')
            active = dict(index=len(phases), first_cycle=cycle, start_cycle=previous_cycle,
                          entry_gap_cycles=cycle - previous_cycle,
                          first_retirement=ordinal, timed=start < cycle <= stop)
        if pc == tail and active is not None:
            active.update(stop_cycle=cycle, cycles=cycle - active['start_cycle'],
                          retired=ordinal - active['first_retirement'] + 1)
            active['cpi'] = active['cycles'] / active['retired']
            phases.append(active)
            active = None
        previous_cycle = cycle
    timed = [p for p in phases if p['timed']]
    warmup = [p for p in phases if not p['timed'] and p['stop_cycle'] < start]
    if len(timed) != repeats or len(warmup) != 1 or active is not None:
        raise ValueError('kernel intervals disagree with declared repetitions/warmup')
    if len({p['retired'] for p in phases}) != 1:
        raise ValueError('kernel repetitions perform different instruction counts')
    middle = timed[1:-1]
    measured = dict(boot_first_kernel=warmup[0], first_timed_kernel=timed[0], last_timed_kernel=timed[-1],
        steady_middle=dict(repetitions=len(middle), total_cycles=sum(p['cycles'] for p in middle),
                           total_retired=sum(p['retired'] for p in middle),
                           total_entry_gap_cycles=sum(p['entry_gap_cycles'] for p in middle)))
    measured['steady_middle']['cpi'] = (measured['steady_middle']['total_cycles'] /
                                        measured['steady_middle']['total_retired'])
    # Explicitly empty models at first timed-kernel entry. Unlike the measured
    # warmup/steady figures, these predict outcomes only, never hypothetical CPI.
    models = {n: Predictor(n, n) for n in (16, 64, 256, 1024, None)}
    counts = {(n, phase): Counter() for n in models for phase in ('first', 'steady_middle', 'last')}
    for event in events:
        if not timed[0]['start_cycle'] < event.cycle <= timed[-1]['stop_cycle']:
            continue
        phase = ('first' if event.cycle <= timed[0]['stop_cycle'] else
                 'last' if event.cycle > timed[-1]['start_cycle'] else 'steady_middle')
        for n, model in models.items():
            model.step(event, counts[n, phase])
    return dict(loop_target=hex(target), loop_tail=hex(tail),
        interval='retirement edges (instruction before loop target, loop-tail branch]',
        cold_scope='boot-first kernel uses actual startup predictor state; empty-state models reset at first timed-kernel entry',
        measured=measured, repetitions=phases,
        empty_at_first_timed_models=[dict(entries=n, phase=phase, **derived(c))
                                     for (n, phase), c in counts.items()])


def analyze_run(arguments):
    directory, capacities = arguments
    directory = Path(directory)
    record = json.loads((directory / 'report.json').read_text())
    native = json.loads((directory / 'native.json').read_text())
    evidence = json.loads((directory / 'benchmark.json').read_text())
    if record['status'] != 'passed' or native['status'] != 'passed' or evidence['status'] != 'passed':
        raise ValueError('prediction diagnostics require a passing benchmark run')
    trace = record.get('diagnostic_retirement_trace', {})
    actual_trace = validate_trace(directory / 'retire.bin', native)
    if any(trace.get(k) != v for k, v in actual_trace.items()):
        raise ValueError('retirement trace metadata changed after capture')
    events = read_events(directory / 'retire.bin')
    start, stop = native['start']['cycle'], native['stop']['cycle']
    measured = [e for e in events if start < e.cycle <= stop]
    observed = evidence['bpu_statistics']['counts']
    expected = dict(conditional_branches=sum(e.kind == 'conditional' for e in measured),
                    direct_jumps=sum(e.kind == 'jal' for e in measured),
                    indirect_jumps=sum(e.kind == 'jalr' for e in measured),
                    taken_conditional_branches=sum(e.kind == 'conditional' and e.taken for e in measured),
                    compressed_control_flow=sum(e.compressed for e in measured))
    if any(observed[k] != v for k, v in expected.items()):
        raise ValueError('trace decoding disagrees with measured architectural control-flow mix')
    parameters = record['configuration']['parameters']
    models = simulate(events, start, stop, capacities, bool(parameters['ISA_C']))
    matched = next((m for m in models if m['state'] == 'warm' and
                    m['bp_entries'] == parameters['MUA_BP_ENTRIES'] and
                    m['btb_entries'] == parameters['MUA_BTB_ENTRIES']), None)
    agreement = None if matched is None else {
        key: dict(model=matched[key], rtl=observed[rtl], delta=matched[key] - observed[rtl])
        for key, rtl in [('btb_hits', 'btb_control_flow_hits'), ('direction_errors', 'direction_mispredictions'),
                         ('next_pc_errors', 'control_flow_mispredictions')]}
    result = dict(schema_version=1, status='passed', analyzer_source_sha256=file_sha(__file__),
        profile=record['context']['benchmark']['profile'],
        report=str(directory / 'report.json'), elf_sha256=record['workload'], trace=actual_trace,
        parameters=parameters, measured_window=evidence['window'],
        measured_bpu=evidence['bpu_statistics'], models=models, model_rtl_deltas=agreement,
        scope='retired-path online prediction models; no speculative training, actual H6 fill or counterfactual CPI',
        unique_control_sites=len({e.pc for e in measured}))
    if result['profile'] == 'nsichneu':
        b = record['context']['benchmark']
        result['kernel_phases'] = kernel_repetitions(directory / 'retire.bin', events, native,
                                                      b['local_scale_factor'] * b['workload_scale'])
    return result


def write_diagnostic_report(output, suite_path, results, capacities):
    """Portable diagnostic page, deliberately separate from standard benchmark metrics."""
    output.mkdir(parents=True, exist_ok=True)
    summary = dict(schema_version=1, status='passed', suite=str(suite_path), capacities=capacities,
        analyzer_source_sha256=file_sha(__file__),
        scope='architectural-path prediction diagnostics; standard RTL benchmark windows remain unchanged', results=results)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    columns = ''.join(f'<th>{n if n is not None else "Unlimited"}</th>' for n in capacities)
    rows = []
    for result in results:
        cells = []
        for n in capacities:
            model = next(m for m in result['models'] if m['state'] == 'warm' and
                         m['bp_entries'] == m['btb_entries'] == n)
            cells.append(f'<td>{model["next_pc_accuracy_percent"]:.3f}%</td>')
        name = html.escape(result['profile'])
        rows.append(f'<tr><th><a href="{name}.json">{name}</a></th>{"".join(cells)}</tr>')
        (output / (result['profile'] + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    nsichneu = next((r for r in results if 'kernel_phases' in r), None)
    phase_html = ''
    if nsichneu:
        measured = nsichneu['kernel_phases']['measured']
        entries = [('First kernel visit after boot', measured['boot_first_kernel']),
                   ('First timed repetition (after warmup)', measured['first_timed_kernel']),
                   ('Steady middle repetitions', measured['steady_middle']),
                   ('Last timed repetition', measured['last_timed_kernel'])]
        phase_rows = ''.join(f'<tr><th>{label}</th><td>{value["cpi"]:.6f}</td></tr>' for label, value in entries)
        phase_html = f'''<h2>nsichneu: measured kernel phases</h2>
<p>The first kernel visit is the untimed warmup after real startup, not a forced
global predictor reset. Intervals run from retirement before the loop target
through the loop-tail branch, including the incoming transition. The first entry
has a {measured['boot_first_kernel']['entry_gap_cycles']}-cycle retirement gap;
the steady middle averages
{measured['steady_middle']['total_entry_gap_cycles'] / measured['steady_middle']['repetitions']:.2f}
cycles at entry. Account for this boundary difference before interpreting CPI
differences as predictor warmup. The last repetition has a different loop-exit outcome.</p>
<table><tr><th>Phase</th><th>Measured RTL CPI</th></tr>{phase_rows}</table>'''
        comparisons = []
        phase_models = nsichneu['kernel_phases']['empty_at_first_timed_models']
        for n in dict.fromkeys(m['entries'] for m in phase_models):
            phase_cells = []
            for phase in ('first', 'steady_middle', 'last'):
                model = next(m for m in phase_models if m['entries'] == n and m['phase'] == phase)
                phase_cells.append(f'<td>{model["next_pc_accuracy_percent"]:.3f}%</td>')
            comparisons.append(f'<tr><th>{n if n is not None else "Unlimited"}</th>{"".join(phase_cells)}</tr>')
        phase_html += f'''<h2>nsichneu: empty model at first kernel entry</h2>
<p>Modeled next-PC accuracy, training online across the 1,231 timed kernel
repetitions. Every table starts empty for the first pass. This exposes the
repeated-path benefit that whole-window averages amortize.</p>
<table><tr><th>Direction / target entries</th><th>First pass</th><th>Steady middle</th><th>Final pass</th></tr>
{''.join(comparisons)}</table>'''
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Embench prediction diagnostics</title>
<style>:root{{color-scheme:light dark}}body{{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:1rem}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}th,td{{padding:.5rem;border:1px solid #888;text-align:right}}th:first-child{{text-align:left}}</style>
<h1>Embench prediction diagnostics</h1><p>Standard warmed benchmark windows are unchanged.
This table shows <strong>modeled next-PC accuracy</strong> on the retired path, with normal startup/warmup retained.
Each column uses that many tagged direct-mapped direction and target entries.
Unlimited is a history-storage upper bound, not an implementable configuration recommendation.</p>
<p>The models omit speculative training, actual H6 data capture and fetch timing.
They do not estimate counterfactual cycles, area or frequency. Per-workload JSON
includes a separate empty-at-timer-entry model and differences from measured RTL at its real capacity.</p>
<table><tr><th>Workload</th>{columns}</tr>{''.join(rows)}</table>{phase_html}
<p><a href="summary.json">Complete diagnostic evidence</a></p></html>'''
    (output / 'index.html').write_text(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True, help='trace-enabled execution suite-results.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--capacities', default='16,64,256,1024,unlimited')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    capacities = [None if n == 'unlimited' else int(n) for n in args.capacities.split(',')]
    if not capacities or len(set(capacities)) != len(capacities) or args.jobs < 1:
        raise ValueError('capacities must be distinct and jobs must be positive')
    for n in capacities:
        Predictor(n, n)
    suite = json.loads(args.suite.read_text())
    if suite['status'] != 'passed' or not suite.get('diagnostic_retirement_trace'):
        raise ValueError('suite requires successful diagnostic retirement traces')
    if len(suite['results']) != len(suite['requested']) or any(r['status'] != 'passed' for r in suite['results']):
        raise ValueError('diagnostic selection has missing or failed workloads')
    results = {}
    args.output.mkdir(parents=True, exist_ok=True)
    state = dict(schema_version=1, status='running', suite=str(args.suite.resolve()), capacities=capacities)
    def status_page():
        (args.output / 'summary.json').write_text(json.dumps(state, indent=2) + '\n')
        (args.output / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Prediction diagnostics</title>'
            '<h1>Prediction diagnostics: ' + html.escape(state['status']) + '</h1>'
            '<p>Complete results are unavailable. See <a href="summary.json">status and failure details</a>.</p>')
    status_page()
    try:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            pending = {pool.submit(analyze_run, (r['directory'], capacities)): r['profile'] for r in suite['results']}
            for future in as_completed(pending):
                name = pending[future]
                result = future.result()
                results[name] = result
                (args.output / (name + '.json')).write_text(json.dumps(result, indent=2) + '\n')
                print('PASS: prediction diagnostics:', name, flush=True)
    except Exception as error:
        state.update(status='failed', detail=str(error), completed=list(results))
        status_page()
        raise
    write_diagnostic_report(args.output, args.suite.resolve(), [results[n] for n in suite['requested']], capacities)
    print('Diagnostic report:', args.output / 'index.html')


if __name__ == '__main__':
    main()
