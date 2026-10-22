#!/usr/bin/env python3
"""Bounded BPU characterization using existing benchmark and ORFS entry points.

This does not assign Greek profiles or perform general configuration search.
Every point keeps the base ISA/software/constraints fixed and varies only
counter capacity, target capacity, retained halfword capacity and, optionally,
compressed-instruction implementation.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import html
import itertools
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

import yaml

ROOT = Path(__file__).resolve().parents[4]
CAPACITIES = (2, 4, 8, 16)
HWORDS = (0, 2, 4, 8, 16)
C_VARIANTS = {
    'decompr-if': dict(MUA_C_IMPL='decompress', MUA_C_DECOMPRESS_STAGE='if'),
    'decompr-de': dict(MUA_C_IMPL='decompress', MUA_C_DECOMPRESS_STAGE='de'),
    'cdecode': dict(MUA_C_IMPL='decode_compressed', MUA_C_DECOMPRESS_STAGE='if'),
}


def compressed_variant(config):
    if not config['ISA_C']:
        return 'none'
    if config['MUA_C_IMPL'] == 'decode_compressed':
        return 'cdecode'
    return 'decompr-' + config['MUA_C_DECOMPRESS_STAGE']


def make_cases(base, points, prefix, variants=None):
    """Keep original IF point names reusable; other C implementations get suffixes."""
    if variants is not None:
        if not base['ISA_C']:
            raise ValueError('compressed implementation sweep requires ISA_C=1')
        if not variants or len(set(variants)) != len(variants) or any(v not in C_VARIANTS for v in variants):
            raise ValueError('compressed implementations must be nonempty, distinct supported choices')
    cases, expected = [], {}
    for variant in variants or [compressed_variant(base)]:
        for bp, btb, hwords in points:
            if not base['ISA_C'] and hwords % 2:
                raise ValueError('candidate payload halfwords must be even without C')
            suffix = {'decompr-de': '-cde', 'cdecode': '-cdecode'}.get(variant, '') if variants else ''
            name = f'{prefix}-b{bp}-t{btb}-h{hwords}{suffix}'
            config = dict(base, MUA_BP_ENTRIES=bp, MUA_BTB_ENTRIES=btb, MUA_BTB_IDATA_HWORDS=hwords)
            if variants:
                config.update(C_VARIANTS[variant])
            cases.append(dict(name=name, bp=bp, btb=btb, hwords=hwords, c_variant=variant))
            expected[name] = config
    return cases, expected


def ihp_candidates(cases, sky, prior=()):
    """Measure area/runtime endpoints and the matching H=0 point for each C kind."""
    promising = set(prior)
    for variant in {r.get('c_variant', 'base') for r in sky}:
        group = [r for r in sky if r.get('c_variant', 'base') == variant]
        fastest = min(group, key=lambda r: r['execution_time_ms'])
        promising.update((fastest['name'], min(group, key=lambda r: r['area_um2'])['name']))
        anchor = next((r for r in group if r['bp'] == fastest['bp'] and
                       r['btb'] == fastest['btb'] and r['hwords'] == 0), None)
        if anchor:
            promising.add(anchor['name'])
    return [c for c in cases if c['name'] in promising]


def candidate_points(path=None):
    """Read explicit (direction entries, target entries, payload halfwords) triples."""
    if path is None:
        return list(itertools.product(CAPACITIES, CAPACITIES, HWORDS))
    points = yaml.safe_load(path.read_text())
    if not isinstance(points, list) or not points:
        raise ValueError('candidates must be a nonempty YAML list of [bp, btb, hwords] triples')
    result = []
    for point in points:
        if (not isinstance(point, list) or len(point) != 3 or
                any(type(value) is not int for value in point)):
            raise ValueError('each candidate must contain exactly three integers: [bp, btb, hwords]')
        bp, btb, hwords = point
        if any(not 2 <= n <= 1024 or n & (n-1) for n in (bp, btb)):
            raise ValueError('candidate table capacities must be powers of two from 2 through 1024')
        if not 0 <= hwords <= 2048:
            raise ValueError('candidate payload halfwords must be from 0 through 2048')
        if tuple(point) in result:
            raise ValueError('duplicate candidate')
        result.append(tuple(point))
    return result


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def fresh(record):
    hashes = record.get('input_sha256', record.get('source_sha256', {}))
    return bool(hashes) and all((ROOT / p).is_file() and sha(ROOT / p) == digest
                               for p, digest in hashes.items())


def metrics(record):
    return {m['name']: m['value'] for m in record.get('metrics', [])}


def frontier(rows):
    """Local area/runtime frontier among successfully qualified placed points."""
    qualified = [r for r in rows if r.get('qualified')]
    return [r for r in qualified if not any(
        o['area_um2'] <= r['area_um2'] and o['execution_time_ms'] <= r['execution_time_ms'] and
        (o['area_um2'] < r['area_um2'] or o['execution_time_ms'] < r['execution_time_ms'])
        for o in qualified)]


def collect(case, benchmark, placement, platform):
    b, p = metrics(benchmark), metrics(placement)
    row = dict(name=case['name'], bp=case['bp'], btb=case['btb'], hwords=case['hwords'],
               c_variant=case.get('c_variant', 'base'),
               platform=platform, benchmark_status=benchmark.get('status', 'missing'),
               placement_status=placement.get('status', 'missing'),
               benchmark_report=case.get('benchmark'), placement_report=case.get(platform))
    row['qualified'] = row['benchmark_status'] == row['placement_status'] == 'passed'
    for output, source, key in (
            ('cycles', b, 'benchmark_cycles'), ('retired', b, 'benchmark_retired'),
            ('cpi', b, 'benchmark_cpi'), ('replay_rate_percent', b, 'bpu_idata_replay_rate'),
            ('btb_hit_rate_percent', b, 'bpu_btb_control_flow_hit_rate'),
            ('area_um2', p, 'cell_area'), ('t_min_ns', p, 'minimum_clock_period'),
            ('f_max_mhz', p, 'estimated_fmax'), ('setup_slack_ns', p, 'setup_worst_slack'),
            ('hold_slack_ns', p, 'hold_worst_slack')):
        if key in source:
            row[output] = source[key]
    path = placement.get('timing_paths', {}).get('full_max', {})
    if path.get('status') == 'timed':
        row['critical_startpoint'] = path['startpoint']
        row['critical_endpoint'] = path['endpoint']
    if 'reg_to_reg_setup_worst_slack' in p:
        row['internal_t_min_ns'] = placement['context']['clock_period_ns'] - p['reg_to_reg_setup_worst_slack']
    internal = placement.get('timing_paths', {}).get('reg_to_reg_max', {})
    if internal.get('status') == 'timed':
        row['internal_critical_startpoint'] = internal['startpoint']
        row['internal_critical_endpoint'] = internal['endpoint']
    if 'cycles' in row and 't_min_ns' in row:
        row['execution_time_ms'] = row['cycles'] * row['t_min_ns'] / 1e6
    for key in ('benchmark', platform):
        if case.get(key):
            record = benchmark if key == 'benchmark' else placement
            if record.get('detail') and record.get('status') != 'passed':
                row[key + '_detail'] = record['detail']
    return row


def relative(path, directory):
    return os.path.relpath(ROOT / path, directory)


def marker(row, x, y, color):
    radius = 6 if row['local_frontier'] else 4
    attrs = f'fill="none" stroke="{color}" stroke-width="2"'
    if not row['qualified']:
        attrs += ' stroke-dasharray="2,2"'
    title = html.escape(f"{row['name']}: {row.get('c_variant', 'base')}; "
                        f"{row['area_um2']:.0f} um2, {row['t_min_ns']:.3f} ns, "
                        f"{row['execution_time_ms']:.3f} ms; {row['placement_status']}")
    variant = row.get('c_variant', 'base')
    if variant == 'decompr-de':
        return (f'<rect x="{x-radius:.2f}" y="{y-radius:.2f}" width="{2*radius}" height="{2*radius}" '
                f'{attrs}><title>{title}</title></rect>')
    if variant == 'cdecode':
        return (f'<polygon points="{x:.2f},{y-radius:.2f} {x-radius:.2f},{y+radius:.2f} '
                f'{x+radius:.2f},{y+radius:.2f}" {attrs}><title>{title}</title></polygon>')
    return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius}" {attrs}><title>{title}</title></circle>'


def render(directory, manifest):
    payloads = sorted({c['hwords'] for c in manifest['cases']})
    palette = {0:'#737373', 2:'#a563bd', 4:'#df8417', 6:'#5d9c42', 8:'#168b9a', 16:'#db6279'}
    colors = {h:palette.get(h, f'hsl({i*137%360} 65% 45%)') for i,h in enumerate(payloads)}
    legend = ', '.join(f'<span style="color:{colors[h]}">{h}</span>' for h in payloads)
    rows = []
    for case in manifest['cases']:
        benchmark = json.loads((ROOT / case['benchmark']).read_text()) if case.get('benchmark') else {}
        for platform in manifest['platforms']:
            placement = json.loads((ROOT / case[platform]).read_text()) if case.get(platform) else {}
            if placement or platform == 'sky130hd':
                rows.append(collect(case, benchmark, placement, platform))
    for platform in manifest['platforms']:
        selected = {r['name'] for r in frontier([r for r in rows if r['platform'] == platform])}
        for row in rows:
            if row['platform'] == platform:
                row['local_frontier'] = row['name'] in selected
    write_json(directory / 'summary.json', dict(schema_version=1, context=manifest['context'], rows=rows))
    esc = html.escape
    bodies = []
    plots = []
    for platform in manifest['platforms']:
        selected = [r for r in rows if r['platform'] == platform]
        points = [r for r in selected if 'execution_time_ms' in r and 'area_um2' in r]
        if points:
            xmin, xmax = min(r['area_um2'] for r in points), max(r['area_um2'] for r in points)
            ymin, ymax = min(r['execution_time_ms'] for r in points), max(r['execution_time_ms'] for r in points)
            dx, dy = max(1, xmax-xmin), max(.001, ymax-ymin)
            def xy(row):
                return (70+620*(row['area_um2']-xmin)/dx, 330-260*(row['execution_time_ms']-ymin)/dy)
            shapes = []
            for row in points:
                x, y = xy(row)
                shapes.append(marker(row, x, y, colors[row['hwords']]))
            plots.append(f'<h2>{esc(platform)}</h2><p>Area versus estimated execution time; lower left is better. '
                         'Hover over points for configurations. Larger circles mark this experiment’s local frontier; '
                         f'dashed circles failed qualification. Payload halfwords: {legend}.</p>'
                         '<svg viewBox="0 0 760 405" role="img" aria-label="Area versus estimated execution time">'
                         '<path d="M60 40V340H710" fill="none" stroke="currentColor"/>'
                         f'<text x="65" y="365">{xmin:.0f}</text><text x="655" y="365">{xmax:.0f}</text>'
                         f'<text x="10" y="335">{ymin:.2f}</text><text x="10" y="75">{ymax:.2f}</text>'
                         '<text x="245" y="393">Placed cell area (µm²)</text>'
                         '<text x="65" y="25">Estimated workload time (ms)</text>' + ''.join(shapes) + '</svg>')
            frequencies = [r for r in points if 'f_max_mhz' in r]
            if frequencies:
                fmin, fmax = min(r['f_max_mhz'] for r in frequencies), max(r['f_max_mhz'] for r in frequencies)
                fdiff = max(.001, fmax-fmin)
                shapes = [marker(r, 70+620*(r['area_um2']-xmin)/dx,
                                 330-260*(r['f_max_mhz']-fmin)/fdiff, colors[r['hwords']]) for r in frequencies]
                plots.append(f'<h3>{esc(platform)} frequency</h3><p>Full constrained-path frequency estimate; '
                             'higher is better. Shapes identify compressed implementations as in the runtime plot.</p>'
                             '<svg viewBox="0 0 760 405" role="img" aria-label="Area versus estimated frequency">'
                             '<path d="M60 40V340H710" fill="none" stroke="currentColor"/>'
                             f'<text x="65" y="365">{xmin:.0f}</text><text x="655" y="365">{xmax:.0f}</text>'
                             f'<text x="10" y="335">{fmin:.2f}</text><text x="10" y="75">{fmax:.2f}</text>'
                             '<text x="245" y="393">Placed cell area (µm²)</text>'
                             '<text x="65" y="25">Estimated F_max (MHz)</text>' + ''.join(shapes) + '</svg>')
        body = []
        def value(row, key, digits=2):
            v = row.get(key)
            return '—' if v is None else f'{v:,.{digits}f}'
        references = {(r['bp'],r['btb'],r['hwords']):r for r in selected
                      if r['c_variant'] == 'decompr-if' and r['qualified']}
        for row in sorted(selected, key=lambda r:(r['bp'], r['btb'], r['hwords'], r['c_variant'])):
            critical = esc(row.get('critical_startpoint', '') + ' → ' + row.get('critical_endpoint', ''))
            ref = references.get((row['bp'],row['btb'],row['hwords']))
            change = (f"{100*(row['t_min_ns']/ref['t_min_ns']-1):+.2f}%"
                      if ref and row['qualified'] else '—')
            links = ' · '.join(f'<a href="{esc(relative(row[k], directory))}">{label}</a>'
                               for k,label in (('benchmark_report','benchmark'),('placement_report','placement'))
                               if row.get(k))
            body.append(f'<tr><td>{esc(row["name"])}{" ★" if row["local_frontier"] else ""}</td>'
                        f'<td>{esc(row["c_variant"])}</td><td>{value(row,"cycles",0)}</td>'
                        f'<td>{value(row,"cpi",3)}</td><td>{value(row,"replay_rate_percent")}</td>'
                        f'<td>{value(row,"area_um2",0)}</td><td title="{critical}">{value(row,"t_min_ns",3)}</td>'
                        f'<td>{value(row,"internal_t_min_ns",3)}</td><td>{change}</td>'
                        f'<td>{value(row,"f_max_mhz")}</td><td>{value(row,"execution_time_ms",3)}</td>'
                        f'<td>{esc(row["placement_status"])}</td><td>{links}</td></tr>')
        bodies.append(f'<h2>{esc(platform)} measurements</h2><table><thead><tr><th>Configuration</th>'
                      '<th>C implementation</th><th>Cycles</th><th>CPI</th><th>Replay %</th><th>Area µm²</th>'
                      '<th>T_min ns</th><th>Internal T_min ns</th><th>T_min vs IF</th><th>F_max MHz</th>'
                      '<th>Estimated ms</th><th>Placement</th><th>Evidence</th></tr></thead><tbody>' + ''.join(body) + '</tbody></table>')
    capacities = '/'.join(str(n) for n in sorted({c['bp'] for c in manifest['cases']}))
    targets = '/'.join(str(n) for n in sorted({c['btb'] for c in manifest['cases']}))
    hwords = '/'.join(str(n) for n in sorted({c['hwords'] for c in manifest['cases']}))
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>uqu BPU replay characterization</title><style>:root{color-scheme:light dark}body{font:16px system-ui;'
            'max-width:1200px;margin:2rem auto;padding:0 1rem}table{border-collapse:collapse;font-size:.85rem}'
            'td,th{padding:.5em;border:1px solid #888;text-align:right}td:first-child,th:first-child{text-align:left}'
            'svg{max-width:760px;width:100%}svg text{fill:currentColor;font-size:13px}</style>'
            f'<h1>BPU replay characterization</h1><p>{len(manifest["cases"])} fixed configurations: independent '
            f'{capacities}-entry direction and {targets}-entry target tables; payload halfwords {hwords}. '
            f'Same {esc(manifest["context"].get("isa_name", ""))} CoreMark performance ELF and one-cycle memories.</p>'
            f'<p>Standalone {manifest["context"]["clock_period_ns"]:g} ns target; reset arrival 0–1 ns; other I/O delays 4 ns. Timing uses placement-estimated RC '
            'and an ideal clock before CTS/routing. T_min includes all constrained paths, including I/O; hover over its table value for the critical endpoints. Estimated runtime = cycles × setup-derived T_min. '
            'This is neither a silicon operating-frequency guarantee nor global Pareto-profile selection. '
            'IHP rows are a selected subset, not its complete frontier.</p>'
            '<p>★ denotes the local area/runtime frontier among successfully qualified measured points. '
            'A failed point’s numbers are diagnostic and excluded from that frontier. '
            'Shapes: ○ decompression in IF (or original base), □ decompression in DE, △ direct compressed decoding. '
            'T_min vs IF compares the same table capacities and replay budget; positive means slower. '
            'Internal T_min shows register-to-register paths only and is diagnostic, not the runtime timing basis.</p>'
            f'<p><a href="summary.json">Machine-readable summary</a> · <a href="experiment.json">Experiment inputs</a> · '
            + ('<a href="audit.json">Evidence audit</a> · ' if (directory/'audit.json').is_file() else '') +
            f'<a href="{esc(os.path.relpath(ROOT/"build/report/index.html",directory))}">Project report</a></p>'
            + ''.join(plots+bodies) + '</html>')
    (directory / 'index.html').write_text(page)
    return rows


def execute(case, phase, args, directory, expected, elf_hash):
    name = case['name']
    record_dir = ROOT / 'build' / ('uquintus-' + name)
    target = 'verilator/benchmark/coremark/fast-performance-seed1-*/report.json' if phase == 'benchmark' else f'orfs_{phase}/impl-*/report.json'
    for path in sorted(record_dir.glob(target), key=lambda p:p.stat().st_mtime, reverse=True):
        record = json.loads(path.read_text())
        if record.get('configuration', {}).get('parameters') != expected or record.get('status') != 'passed':
            continue
        if phase == 'benchmark':
            memory = record.get('context', {}).get('memory', {})
            compatible = (record.get('workload') == elf_hash and record['context'].get('execution_mode') == 'fast' and
                          memory.get('imem_latency') == memory.get('dmem_latency') == 1 and
                          memory.get('grants') == memory.get('fence_ack') == 'immediate' and
                          record.get('selection') == 'coremark-performance')
        else:
            context = record['context']
            compatible = (context.get('clock_period_ns') == args.clock_period and
                          context.get('sdc_sha256') == sha(directory/'constraints.sdc') and
                          context.get('core_area_um') == [20.,20.,1220.,1220.] and
                          context.get('die_area_um') == [0.,0.,1240.,1240.] and context.get('place_density') == .65 and
                          f'NUM_CORES={args.jobs}' in record.get('command', []) and
                          bool(args.yosys and args.openroad) and
                          context.get('tools', {}).get('yosys_sha256') == sha(Path(args.yosys)) and
                          context.get('tools', {}).get('openroad_sha256') == sha(Path(args.openroad)))
        if compatible and fresh(record):
            return str(path.relative_to(ROOT)), True
    config = directory / 'config' / (name + '.yml')
    command = ['make', f'CONFIG={config}', f'PYTHON={sys.executable}', f'BENDER={args.bender}', f'JOBS={args.jobs}']
    if phase == 'benchmark':
        command += ['benchmark-run', f'ELF={args.elf}', 'BENCHMARK_PROFILE=performance', 'BENCHMARK_MODE=fast']
    else:
        command += ['impl', f'PLATFORM={phase}', f'CLOCK_PERIOD_NS={args.clock_period:g}',
                    'RESET_INPUT_DELAY_NS=', f'SDC={directory}/constraints.sdc',
                    f'ORFS_ROOT={args.orfs_root}', f'YOSYS_EXE={args.yosys}', f'OPENROAD_EXE={args.openroad}']
    # Separate invocations may characterize the same point concurrently.
    # Never parse another invocation's partially overwritten stdout log.
    log = directory / 'logs' / f'{name}-{phase}-{uuid4().hex[:12]}.log'
    with log.open('w') as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    artifacts = [line.partition('Artifacts: ')[2] for line in log.read_text().splitlines() if line.startswith('Artifacts: ')]
    if not artifacts:
        raise RuntimeError(f'{name}/{phase}: no flow artifact; inspect {log}')
    report = Path(artifacts[-1]) / 'report.json'
    if not report.is_file():
        raise RuntimeError(f'{name}/{phase}: missing report; inspect {log}')
    record = json.loads(report.read_text())
    if record.get('status') not in ('passed', 'failed'):
        raise RuntimeError(f'{name}/{phase}: incomplete report; inspect {log}')
    if result.returncode and record.get('status') != 'failed':
        raise RuntimeError(f'{name}/{phase}: incomplete failure evidence; inspect {log}')
    return str(report.relative_to(ROOT)), False


def audit(directory, manifest):
    """Check that joined measurements describe the same RTL and workload."""
    baseline_rtl = None
    baseline_memory = None
    baseline_retired = None
    platforms = {}
    checked = 0
    for case in manifest['cases']:
        if not case.get('benchmark'):
            raise ValueError(f'{case["name"]}: missing benchmark evidence')
        expected = yaml.safe_load((directory/'config'/f'{case['name']}.yml').read_text())
        for phase in ('benchmark', *manifest['platforms']):
            if not case.get(phase):
                continue
            record = json.loads((ROOT/case[phase]).read_text())
            if record['configuration']['parameters'] != expected:
                raise ValueError(f'{case["name"]}/{phase}: configuration mismatch')
            if record['status'] != 'passed':
                raise ValueError(f'{case["name"]}/{phase}: run did not qualify')
            inputs = record.get('input_sha256', record.get('source_sha256', {}))
            rtl = {p:h for p,h in inputs.items() if p.startswith('src/uquintus/')}
            if not rtl or (baseline_rtl is not None and rtl != baseline_rtl):
                raise ValueError(f'{case["name"]}/{phase}: RTL inputs differ across the matrix')
            baseline_rtl = rtl
            values = metrics(record)
            if phase == 'benchmark':
                if record['workload'] != manifest['context']['elf_sha256']:
                    raise ValueError('workload ELF mismatch')
                memory = record['context']['memory']
                retired = values['benchmark_retired']
                if ((baseline_memory is not None and memory != baseline_memory) or
                    (baseline_retired is not None and retired != baseline_retired)):
                    raise ValueError('memory schedule or retired workload differs')
                baseline_memory, baseline_retired = memory, retired
            else:
                context = record['context']
                if (context['clock_period_ns'] != manifest['context']['clock_period_ns'] or
                    context['sdc_sha256'] != manifest['context']['sdc_sha256']):
                    raise ValueError('implementation constraint profile differs')
                identity = dict(libraries=context['mapping_libraries'],
                                yosys=context['tools']['yosys_sha256'],
                                openroad=context['tools']['openroad_sha256'],
                                abc=context['tools']['abc_sha256'])
                if phase in platforms and platforms[phase] != identity:
                    raise ValueError('platform mapping library or tool changed')
                platforms[phase] = identity
                if (values['setup_worst_slack'] < 0 or values['hold_worst_slack'] < 0 or
                    any(values[name] != 0 for name in ('slew_violations','capacitance_violations',
                                                       'fanout_violations','placement_violations'))):
                    raise ValueError('placed timing, electrical or legality checks failed')
            checked += 1
    evidence = dict(schema_version=1,status='passed',checked_records=checked,
                    workload_sha256=manifest['context']['elf_sha256'],
                    retired_instructions=baseline_retired,rtl_sha256=baseline_rtl,
                    memory=baseline_memory,platforms=platforms)
    write_json(directory/'audit.json',evidence)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT/'build/investigations/bpu-replay-hwords')
    parser.add_argument('--base-config', type=Path, default=ROOT/'config/rv32i_bimodal_idata.yml')
    parser.add_argument('--candidates', type=Path, help='YAML list of selected [bp, btb, hwords] triples instead of the full matrix')
    parser.add_argument('--name-prefix', default='bpu', help='Prefix for generated configuration names')
    parser.add_argument('--c-variants', nargs='+', choices=tuple(C_VARIANTS),
                        help='Cross selected BPU points with compressed implementations; requires ISA_C=1')
    parser.add_argument('--bender', default=os.environ.get('BENDER','bender'))
    parser.add_argument('--orfs-root', default=os.environ.get('ORFS_ROOT',''))
    parser.add_argument('--yosys', default=os.environ.get('YOSYS_EXE',''))
    parser.add_argument('--openroad', default=os.environ.get('OPENROAD_EXE',''))
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--clock-period', type=float, default=40)
    parser.add_argument('--summary-only', action='store_true')
    parser.add_argument('--skip-ihp', action='store_true')
    parser.add_argument('--benchmark-only', action='store_true')
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if args.summary_only:
        render(directory, json.loads((directory/'experiment.json').read_text()))
        return
    if args.elf is None:
        parser.error('--elf is required when executing measurements')
    # Keep earlier measured IHP anchors visible when extending a matrix. Each
    # candidate is still revalidated through execute's normal cache checks.
    prior_path = directory/'experiment.json'
    prior = json.loads(prior_path.read_text()) if prior_path.is_file() else {}
    prior_ihp = {c['name'] for c in prior.get('cases', []) if c.get('ihp-sg13g2')}
    args.elf = args.elf.resolve()
    (directory/'audit.json').unlink(missing_ok=True)
    if args.jobs < 1 or args.workers < 1:
        parser.error('workers and jobs must be positive')
    if not math.isfinite(args.clock_period) or args.clock_period <= 0:
        parser.error('clock period must be finite and positive')
    if not re.fullmatch(r'[a-z][a-z0-9_-]*', args.name_prefix):
        parser.error('name prefix must start with a lowercase letter and contain only lowercase letters, digits, underscores or hyphens')
    try:
        points = candidate_points(args.candidates)
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.error(str(error))
    constraints = f"""# Standalone characterization: fixed I/O budgets across target periods.
set_units -time ns -capacitance pF
create_clock -name core_clk -period {args.clock_period:g} [get_ports clk_i]
set data_inputs [all_inputs -no_clocks]
set_input_delay 4 -clock core_clk $data_inputs
set_input_delay -min 0 -clock core_clk [get_ports rst_ni]
set_input_delay -max 1 -clock core_clk [get_ports rst_ni]
set_output_delay 4 -clock core_clk [all_outputs]
set_input_transition 0.1 $data_inputs
set_load 0.01 [all_outputs]
set_clock_uncertainty 0.1 [get_clocks core_clk]
"""
    (directory/'constraints.sdc').write_text(constraints)
    base = yaml.safe_load(args.base_config.read_text())
    try:
        cases, expected = make_cases(base, points, args.name_prefix, args.c_variants)
    except ValueError as error:
        parser.error(str(error))
    (directory/'config').mkdir(exist_ok=True)
    for name, config in expected.items():
        (directory/'config'/f'{name}.yml').write_text(yaml.safe_dump(config,sort_keys=False))
    (directory/'logs').mkdir(exist_ok=True)
    elf_hash = sha(args.elf)
    (directory/'measured-method.py.txt').write_bytes(Path(__file__).read_bytes())
    manifest = dict(schema_version=1,started_at=datetime.now(timezone.utc).isoformat(),
        context=dict(base_config=str(args.base_config),base_config_sha256=sha(args.base_config),
                     elf=str(args.elf),elf_sha256=elf_hash,
                     hwords=sorted({p[2] for p in points}),capacities=sorted({p[0] for p in points}),
                     target_capacities=sorted({p[1] for p in points}),
                     c_variants=sorted({c['c_variant'] for c in cases}),
                     candidates=str(args.candidates) if args.candidates else None,
                     candidates_sha256=sha(args.candidates) if args.candidates else None,
                     isa_name=('RV32' + ('E' if base['ISA_E'] else 'I') +
                               ('M' if base['ISA_M'] else '') + ('C' if base['ISA_C'] else '')),
                     clock_period_ns=args.clock_period,reset_max_ns=1,io_delay_ns=4,memory=dict(imem_latency=1,dmem_latency=1),
                     core_area_um=[20,20,1220,1220],place_density=.65,
                     method_sha256=sha(Path(__file__)),method_snapshot='measured-method.py.txt',
                     sdc_sha256=sha(directory/'constraints.sdc')),
        platforms=['sky130hd','ihp-sg13g2'],cases=cases,errors=[])
    def save():
        write_json(directory/'experiment.json',manifest)
        return render(directory, manifest)
    save()
    for phase in ('benchmark','sky130hd','ihp-sg13g2'):
        if args.benchmark_only and phase != 'benchmark':
            break
        selected = cases
        if phase == 'ihp-sg13g2':
            if args.skip_ihp:
                break
            sky = [r for r in save() if r['platform'] == 'sky130hd' and r['qualified']]
            selected = ihp_candidates(cases, sky, prior_ihp)
            manifest['ihp_selection'] = sorted(c['name'] for c in selected)
            print(f'IHP follow-up: {len(selected)} qualified Sky130 candidates',flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(execute,case,phase,args,directory,expected[case['name']],elf_hash):case
                       for case in selected}
            for index,future in enumerate(as_completed(pending),1):
                case = pending[future]
                try:
                    path,reused = future.result()
                    case[phase] = path
                    record = json.loads((ROOT/path).read_text())
                    print(f'{phase} {index}/{len(selected)} {case["name"]}: {record["status"]}' +
                          (' (reused)' if reused else ''),flush=True)
                except Exception as error:
                    manifest['errors'].append(str(error))
                    print(str(error),flush=True)
                save()
    manifest['finished_at'] = datetime.now(timezone.utc).isoformat()
    rows = save()
    if not manifest['errors']:
        audit(directory, manifest)
        render(directory, manifest)
    print('Summary: '+str(directory/'index.html'),flush=True)
    if manifest['errors'] or any((r['benchmark_status'] != 'passed' if args.benchmark_only else
                                  not r['qualified']) for r in rows):
        raise SystemExit('Some configurations did not qualify; inspect experiment and per-flow evidence')


if __name__ == '__main__':
    main()
