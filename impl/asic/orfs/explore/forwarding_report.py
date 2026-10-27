#!/usr/bin/env python3
"""Combine forwarding ladders into a static, interactive Pareto report.

Different ISA ELFs are permitted; workload, compiler policy, memory and physical
constraints must match. Failed/incomplete measurements never enter a frontier.
"""
import argparse
import csv
import html
import importlib.util
import json
import math
import os
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location('forwarding_power_measure', ROOT/'verif/sim/common/power_measure.py')
power_measure = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(power_measure)


def library_conditions(libraries):
    """Read nominal Liberty conditions, never infer voltage from technology."""
    result = []
    for name in libraries:
        path = Path(name)
        header = ''
        if path.is_file():
            with path.open() as stream:
                header = stream.read(65536)
        entry = dict(library=path.name)
        for key in ('nom_voltage', 'nom_temperature'):
            match = re.search(r'\b'+key+r'\s*:\s*([-+\d.eE]+)\s*;', header)
            if match:
                entry[key] = float(match[1])
        result.append(entry)
    return result


def power_results(implementation, impl_path, benchmark, output):
    """Select the latest successful measured run for this exact physical point."""
    for path in sorted(impl_path.parent.glob('power-*/report.json'), reverse=True):
        record = json.loads(path.read_text())
        if record.get('kind') != 'power' or record.get('status') != 'passed':
            continue
        context = record['context']
        measured = json.loads((path.parent/'power.json').read_text())
        window = measured['benchmark_window']
        benchmark_metrics = {m['name']: m['value'] for m in benchmark['metrics']}
        if (record['configuration'] != implementation['configuration'] or
                record['implementation'] != str(impl_path.relative_to(ROOT)) or
                record['workload'] != benchmark['workload'] or
                context['platform'] != implementation['context']['platform'] or
                context['libraries'] != implementation['context']['mapping_libraries'] or
                context['memory'] != benchmark['context']['memory'] or
                context['benchmark'] != benchmark['context']['benchmark'] or
                context['stage'] != 'placed_pre_cts' or
                not context.get('timing_qualified') or
                context['clock_model'] != 'ideal_pre_cts' or
                context['sta_interconnect'] != 'placement_estimated' or
                context['activity'] != 'zero_delay_gate_vcd' or
                context['clock_period_ns'] != implementation['context']['clock_period_ns'] or
                context['clock_period_ns'] != measured['clock_period_ns'] or
                context['benchmark_window'] != window or
                measured.get('status') != 'passed' or
                window['cycles'] != benchmark_metrics['benchmark_cycles'] or
                window['retired'] != benchmark_metrics['benchmark_retired'] or
                context['activity_duration_ps'] != window['cycles'] * measured['clock_period_ns'] * 1000):
            raise ValueError('power evidence does not match its physical point/workload/window: '+str(path))
        coverage = power_measure.activity_coverage(measured['coverage']['counts'], context['coverage_minimum'])
        if measured['coverage'] != coverage or context['activity_coverage'] != coverage:
            raise ValueError('inconsistent power activity coverage')
        metrics = power_measure.energy(measured['power'], window['cycles'], window['retired'], measured['clock_period_ns'])
        reported = {m['name']: m['value'] for m in record['metrics']}
        if any(not math.isclose(metrics[k], source.get(k, math.nan), rel_tol=1e-10, abs_tol=1e-18)
               for k in metrics for source in (measured['metrics'], reported)):
            raise ValueError('inconsistent power/energy metrics')
        return dict(metrics=metrics, coverage=coverage, window=window,
            period_ns=measured['clock_period_ns'], libraries=library_conditions(context['libraries']),
            report=os.path.relpath(path, output),
            evidence=os.path.relpath(path.parent/'power.json', output),
            activity_report=os.path.relpath(ROOT/record['benchmark_report'], output),
            detail=record.get('detail'), recovery=record.get('recovery'))
    return None


def implementation_results(record, record_path, output):
    """Keep mapped and repaired observations separate, using exact STA data."""
    directory = record_path.parent
    stages = {}
    for stage in ('mapped_preplacement', 'placed_pre_cts'):
        timing_file = directory / 'timing' / stage / 'summary.json'
        metrics_file = directory / 'mapped_metrics.json' if stage == 'mapped_preplacement' else record_path
        if not timing_file.is_file() or not metrics_file.is_file():
            stages[stage] = dict(available=False)
            continue
        timing = json.loads(timing_file.read_text())
        if timing.get('stage') != stage:
            raise ValueError('implementation timing stage does not match its directory')
        raw = json.loads(metrics_file.read_text())
        metrics = {m['name']: m['value'] for m in (raw if isinstance(raw, list) else raw.get('metrics', []))}
        if 'cell_area' not in metrics:
            stages[stage] = dict(available=False)
            continue
        # mapped_metrics.json also contains rounded ORFS timing; use the retained
        # scoped STA summary for both stages rather than mixing those sources.
        metrics.update(timing['metrics'])
        stages[stage] = dict(available=True, metrics=metrics,
            logical_cells=metrics['cell_count'] - metrics.get('physical_only_count', 0),
            critical_path=timing['paths']['full_max'],
            capture_paths={region: timing['paths'].get('stage_'+region+'_max', {})
                           for region in ('IF', 'DE', 'EX', 'MEM', 'WB', 'CORE')},
            evidence={})
        evidence = stages[stage]['evidence']
        files = dict(timing_summary=timing_file, critical_path=timing_file.with_name('full_max.rpt'),
                     metrics=metrics_file)
        if stage == 'placed_pre_cts':
            files.update(netlist=directory/'physical/uqu_placed.v',
                         def_file=directory/'physical/uqu_placed.def',
                         cell_inventory=directory/'physical/cells.json',
                         placement_checks=directory/'physical/placement_violations.txt')
        suffix = '/1_synth.odb' if stage == 'mapped_preplacement' else '/3_6_place_repair_timing.odb'
        checkpoints = [directory/p for p in record.get('artifacts', []) if p.endswith(suffix)]
        if len(checkpoints) > 1:
            raise ValueError('ambiguous implementation checkpoint')
        if checkpoints:
            files['checkpoint'] = checkpoints[0]
        if stage == 'mapped_preplacement':
            netlists = [directory/p for p in record.get('artifacts', []) if p.endswith('/1_2_yosys.v')]
            if len(netlists) == 1:
                files['netlist'] = netlists[0]
        for key, path in files.items():
            if path.is_file():
                evidence[key] = os.path.relpath(path, output)
    return stages


def frontier(rows, y='execution_time_ms', maximize=False):
    points = [r for r in rows if r.get('qualified') and all(
        isinstance(r.get(k), (int, float)) and math.isfinite(r[k]) and r[k] > 0
        for k in ('area_um2', y))]
    def value(r):
        return -r[y] if maximize else r[y]
    return [r for r in points if not any(
        o['platform'] == r['platform'] and o['area_um2'] <= r['area_um2'] and value(o) <= value(r) and
        (o['area_um2'] < r['area_um2'] or value(o) < value(r)) for o in points)]


def benchmark_policy(record):
    context = record['context']
    benchmark = dict(context['benchmark'])
    # The compiler's software arithmetic library may differ across ISA targets.
    benchmark.pop('runtime_sha256', None)
    return dict(benchmark=benchmark, **{key: context[key] for key in (
        'memory', 'execution_mode', 'validation_scope', 'family', 'version',
        'abi', 'suite_revision', 'measurement')})


def physical_policy(record):
    context = record['context']
    return {key: context[key] for key in (
        'clock_period_ns', 'sdc_sha256', 'core_area_um', 'die_area_um',
        'place_density', 'mapping_libraries')} | dict(tools={
            key: context['tools'][key] for key in ('yosys_sha256', 'openroad_sha256', 'abc_sha256')})


def collect(directories, output, include_power=True):
    if len(set(directories)) != len(directories):
        raise ValueError('duplicate study directories')
    rows, studies = [], []
    common_benchmark, common_constraints, common_rtl, common_geometry = None, None, None, None
    platforms = {}
    for directory in directories:
        summary = json.loads((directory / 'summary.json').read_text())
        experiment = json.loads((directory / 'experiment.json').read_text())
        constraints = {k: summary['context'][k] for k in ('clock_period_ns', 'sdc_sha256')}
        if common_constraints is not None and common_constraints != constraints:
            raise ValueError('cannot merge different clock/SDC characterization contexts')
        common_constraints = constraints
        first = experiment['cases'][0]
        config = yaml.safe_load((directory / 'config' / (first['name'] + '.yml')).read_text())
        isa = ('RV32E' if config['ISA_E'] else 'RV32I') + ('M' if config['ISA_M'] else '') + ('C' if config['ISA_C'] else '')
        audit = directory / 'audit.json'
        audit_record = json.loads(audit.read_text()) if audit.is_file() else {}
        audited = (audit_record.get('status') == 'passed' and
                   set(audit_record.get('platforms', {})) == set(experiment.get('platforms', [])) and
                   audit_record.get('checked_records') == len(experiment['cases'])*(1+len(experiment.get('platforms', []))))
        studies.append(dict(isa=isa, configuration=config, context=summary['context'],
                            audited=audited,
                            report=os.path.relpath(directory / 'index.html', output),
                            audit=os.path.relpath(audit, output) if audit.is_file() else None))
        for source in summary['rows']:
            row = dict(source, isa=isa, study=len(studies)-1)
            row['id'] = f'{len(studies)-1}:{row["platform"]}:{row["name"]}'
            for key in ('benchmark_report', 'placement_report'):
                path = row.get(key)
                if not path:
                    continue
                record = json.loads((ROOT / path).read_text())
                inputs = record.get('input_sha256', record.get('source_sha256', {}))
                rtl = {p: digest for p, digest in inputs.items() if p.startswith('src/uquintus/')}
                if record.get('status') == 'passed' and not rtl:
                    raise ValueError('passed record is missing RTL input identities')
                if rtl:
                    if common_rtl is not None and common_rtl != rtl:
                        raise ValueError('cannot merge different RTL source snapshots')
                    common_rtl = rtl
                if key == 'benchmark_report':
                    policy = benchmark_policy(record)
                    if common_benchmark is not None and common_benchmark != policy:
                        raise ValueError('cannot merge different workload/compiler/memory policies')
                    common_benchmark = policy
                elif record.get('context', {}).get('mapping_libraries'):
                    policy = physical_policy(record)
                    geometry = {k: policy[k] for k in ('core_area_um','die_area_um','place_density')}
                    if common_geometry is not None and common_geometry != geometry:
                        raise ValueError('cannot merge different floorplan/density profiles')
                    common_geometry = geometry
                    if row['platform'] in platforms and platforms[row['platform']] != policy:
                        raise ValueError('cannot merge different physical contexts on the same platform')
                    platforms[row['platform']] = policy
                if key == 'placement_report':
                    row['implementation'] = implementation_results(record, ROOT / path, output)
                    benchmark = json.loads((ROOT/source['benchmark_report']).read_text())
                    row['power'] = power_results(record, ROOT/path, benchmark, output) if include_power else None
                row[key] = os.path.relpath(ROOT / path, output)
            rows.append(row)
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('duplicate study rows')
    selected = {r['id'] for r in frontier(rows)}
    for row in rows:
        row['combined_frontier'] = row['id'] in selected
    return dict(schema_version=1, studies=studies, rows=rows,
                benchmark_policy=common_benchmark, physical_contexts=platforms,
                constraints=common_constraints, rtl_sha256=common_rtl)


PHYSICAL_COLUMNS = (
    ('mapped_area_um2', 'Mapped area µm²', 'mapped_preplacement', 'cell_area', 0),
    ('repaired_area_um2', 'Repaired area µm²', 'placed_pre_cts', 'cell_area', 0),
    ('repaired_lef_area_um2', 'Total LEF cell area µm²', 'placed_pre_cts', 'lef_cell_area', 0),
    ('mapped_logic_cells', 'Mapped logic cells', 'mapped_preplacement', 'logical_cells', 0),
    ('repaired_logic_cells', 'Repaired logic cells', 'placed_pre_cts', 'logical_cells', 0),
    ('physical_only_cells', 'Physical-only cells', 'placed_pre_cts', 'physical_only_count', 0),
    ('mapped_buffers', 'Mapped buffers', 'mapped_preplacement', 'buffer_count', 0),
    ('repaired_buffers', 'Repaired buffers', 'placed_pre_cts', 'buffer_count', 0),
    ('mapped_buffer_area_um2', 'Mapped buffer area µm²', 'mapped_preplacement', 'buffer_area', 0),
    ('repaired_buffer_area_um2', 'Repaired buffer area µm²', 'placed_pre_cts', 'buffer_area', 0),
    ('mapped_fmax_mhz', 'Mapped Fmax MHz', 'mapped_preplacement', 'estimated_fmax', 2),
    ('repaired_fmax_mhz', 'Repaired Fmax MHz', 'placed_pre_cts', 'estimated_fmax', 2),
    ('repaired_tmin_ns', 'Repaired Tmin ns', 'placed_pre_cts', 'minimum_clock_period', 3),
    ('setup_slack_ns', 'Setup slack ns', 'placed_pre_cts', 'setup_worst_slack', 3),
    ('hold_slack_ns', 'Hold slack ns', 'placed_pre_cts', 'hold_worst_slack', 3),
    ('setup_tns_ns', 'Setup TNS ns', 'placed_pre_cts', 'setup_total_negative_slack', 3),
    ('slew_violations', 'Slew violations', 'placed_pre_cts', 'slew_violations', 0),
    ('capacitance_violations', 'Cap violations', 'placed_pre_cts', 'capacitance_violations', 0),
    ('fanout_violations', 'Fanout violations', 'placed_pre_cts', 'fanout_violations', 0),
    ('placement_violations', 'Placement violations', 'placed_pre_cts', 'placement_violations', 0),
)


def physical_rows(data):
    rows = []
    for row in data['rows']:
        result = {key: row[key] for key in ('isa', 'name', 'step', 'platform')}
        for key, _, stage, metric, _ in PHYSICAL_COLUMNS:
            record = row.get('implementation', {}).get(stage, {})
            result[key] = record.get('logical_cells') if metric == 'logical_cells' else record.get('metrics', {}).get(metric)
        for stage in ('mapped_preplacement', 'placed_pre_cts'):
            path = row.get('implementation', {}).get(stage, {}).get('critical_path', {})
            result[stage+'_startpoint'] = path.get('startpoint', '')
            result[stage+'_endpoint'] = path.get('endpoint', '')
        rows.append(result)
    return rows


def physical_html(data):
    esc = html.escape
    rows = physical_rows(data)
    def number(value, digits):
        return '—' if value is None else f'{value:,.{digits}f}'
    columns = ''.join('<th>'+esc(label)+'</th>' for _, label, *_ in PHYSICAL_COLUMNS)
    body, capture = [], []
    for source, row in zip(data['rows'], rows):
        stages = source.get('implementation', {})
        links = []
        for stage, prefix in (('mapped_preplacement', 'mapped'), ('placed_pre_cts', 'repaired')):
            evidence = stages.get(stage, {}).get('evidence', {})
            for key, label in (('netlist', 'Verilog'), ('checkpoint', 'ODB'), ('def_file', 'DEF'),
                               ('timing_summary', 'STA'), ('critical_path', 'critical path'),
                               ('cell_inventory', 'cells')):
                if key in evidence:
                    links.append(f'<a href="{esc(evidence[key])}">{prefix} {label}</a>')
        body.append(f'<tr><td>{esc(row["platform"])}</td><td>{esc(row["isa"])}</td><td>F{row["step"]}</td>' +
                    ''.join(f'<td>{number(row[key], digits)}</td>' for key, _, _, _, digits in PHYSICAL_COLUMNS) +
                    '<td>'+' · '.join(links)+'</td></tr>')
        cells = []
        for region in ('IF', 'DE', 'EX', 'MEM', 'WB', 'CORE'):
            path = stages.get('placed_pre_cts', {}).get('capture_paths', {}).get(region, {})
            title = path.get('startpoint', '')+' → '+path.get('endpoint', '')
            cells.append(f'<td title="{esc(title)}">{number(path.get("slack_ns"), 3)}</td>')
        capture.append(f'<tr><td>{esc(row["platform"])}</td><td>{esc(row["isa"])}</td><td>F{row["step"]}</td>'+''.join(cells)+'</tr>')
    target = data['constraints']['clock_period_ns']
    geometry = []
    for platform, context in data.get('physical_contexts', {}).items():
        die, core = context['die_area_um'], context['core_area_um']
        geometry.append(f'{esc(platform)}: die {die[2]-die[0]:g} × {die[3]-die[1]:g} µm; '
                        f'core {core[2]-core[0]:g} × {core[3]-core[1]:g} µm; '
                        f'target placement density {context["place_density"]:g}.')
    return (f'<section id="implementation"><h2>Synthesis and post-repair placement</h2>'
        f'<p>Fixed characterization clock: {target:g} ns. The Pareto plot uses repaired-placement area and timing. '
        'Mapped synthesis is an unplaced estimate. Repair results are from ORFS '
        '<code>place_repair_timing</code>, with ideal clocks and placement-estimated RC, before CTS and routing. '
        'They are not post-route/signoff results or a frequency-search measurement.</p>'
        '<p>Logic-cell counts exclude physical-only cells; mapped counts and repaired logic counts have the same scope. '
        'Liberty cell area includes logic and buffers; total LEF area also includes physical-only masters. '
        'These cell areas differ from the fixed core/die area. '
        'All detailed tables list every point, independently of plot filters. Larger setup/hold slack is better; '
        'TNS and violation counts should be zero.</p><p>'+' '.join(geometry)+'</p>'
        '<p><a href="synthesis-layout.csv">Download CSV</a> · <a href="synthesis-layout.md">Markdown table</a></p>'
        '<div class="scroll"><table><thead><tr><th>Platform</th><th>ISA</th><th>Step</th>'+columns+'<th>Retained artifacts</th>'
        '</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'
        '<h3>Post-repair capture-region setup slack (ns)</h3>'
        '<p>Each column groups paths by receiving-stage registers; the launch may be in another stage or at a port. '
        'These are capture-group slacks, not isolated stage delays. Hover for the critical endpoints.</p>'
        '<div class="scroll"><table><thead><tr><th>Platform</th><th>ISA</th><th>Step</th>'+
        ''.join('<th>'+r+'</th>' for r in ('IF','DE','EX','MEM','WB','CORE'))+
        '</tr></thead><tbody>'+''.join(capture)+'</tbody></table></div></section>')


def write_physical_exports(data, output):
    rows = physical_rows(data)
    with (output/'synthesis-layout.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ['isa','name','step','platform'])
        writer.writeheader()
        writer.writerows(rows)
    columns = PHYSICAL_COLUMNS
    lines = ['# Synthesis and repaired-placement results', '',
        f'Fixed target: {data["constraints"]["clock_period_ns"]:g} ns. Repaired placement is before CTS/routing, with ideal clocks and estimated wire RC.', '',
        'Logic-cell counts exclude physical-only cells. Cell areas are Liberty logic/buffer areas. Frequencies are STA-derived estimates. Setup/hold slack is measured at the fixed target, not at estimated Fmax.', '',
        '| Platform | ISA | Step | '+' | '.join(c[1] for c in columns)+' |',
        '|---|---|---|'+'|'.join('---:' for _ in columns)+'|']
    for row in rows:
        values = ['—' if row[key] is None else f'{row[key]:,.{digits}f}' for key, _, _, _, digits in columns]
        lines.append(f'| {row["platform"]} | {row["isa"]} | F{row["step"]} | '+' | '.join(values)+' |')
    lines += ['', '[Interactive report and artifact links](index.html#implementation).', '']
    (output/'synthesis-layout.md').write_text('\n'.join(lines))


def platform_comparisons(data):
    baseline = {(r['isa'], r['name']): r for r in data['rows'] if r['platform'] == 'sky130hd'}
    pairs = []
    for row in data['rows']:
        sky = baseline.get((row['isa'], row['name']))
        if row['platform'] == 'sky130hd' or not sky or not row['qualified'] or not sky['qualified']:
            continue
        pair = dict(isa=row['isa'], step=row['step'], platform=row['platform'], baseline='sky130hd')
        for key in ('area_um2', 'f_max_mhz', 'execution_time_ms'):
            pair['sky_'+key], pair['candidate_'+key] = sky[key], row[key]
            pair[key+'_change_percent'] = 100*(row[key]/sky[key]-1)
        pairs.append(pair)
    return pairs


def progress_html(data):
    parts=[]
    for platform in dict.fromkeys(r['platform'] for r in data['rows']):
        rows=[r for r in data['rows'] if r['platform']==platform]
        counts={}
        for row in rows:
            status='passed' if row.get('qualified') else row.get('placement_status','missing')
            counts[status]=counts.get(status,0)+1
        parts.append(html.escape(platform)+': '+', '.join(f'{n} {html.escape(s)}' for s,n in counts.items()))
    return ('<p><strong>Study progress:</strong> '+'; '.join(parts)+'. '
            '<a href="index.html">Reload measurements</a>. Running and queued points enter the plot after qualification.</p>')


def comparison_html(data, output):
    pairs = platform_comparisons(data)
    if not pairs:
        return ''
    with (output/'platform-comparison.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(pairs[0]))
        writer.writeheader(); writer.writerows(pairs)
    body = []
    for p in pairs:
        body.append(f'<tr><td>{html.escape(p["platform"])}</td><td>{p["isa"]}</td><td>F{p["step"]}</td>'+''.join(
            f'<td>{p["sky_"+key]:,.{digits}f}</td><td>{p["candidate_"+key]:,.{digits}f}</td>'
            f'<td>{p[key+"_change_percent"]:+.1f}%</td>'
            for key, digits in (('area_um2', 0), ('f_max_mhz', 2), ('execution_time_ms', 3)))+'</tr>')
    return ('<section id="comparison"><h2>Matched configurations versus Sky130 HD</h2>'
        '<p>Both backends use the same functional hardware, per-ISA ELF, memory schedule, clock constraint and floorplan. '
        'Cycles and CPI are shared RTL observations. Different cell libraries, supply voltages and RC models apply; '
        'these are backend comparisons, not an isolated process-node comparison. Negative area/time change and positive frequency change are improvements. '
        'Pareto fronts are computed separately per platform.</p><p><a href="platform-comparison.csv">Download comparison CSV</a></p>'
        '<div class="scroll"><table><thead><tr><th>Backend</th><th>ISA</th><th>Step</th>'
        '<th>Sky area µm²</th><th>Backend area µm²</th><th>Δ area</th>'
        '<th>Sky Fmax MHz</th><th>Backend Fmax MHz</th><th>Δ Fmax</th>'
        '<th>Sky time ms</th><th>Backend time ms</th><th>Δ time</th></tr></thead><tbody>'+
        ''.join(body)+'</tbody></table></div></section>')


def power_html(data, output):
    rows, body, notes = [], [], []
    for row in data['rows']:
        power = row.get('power')
        if not power:
            continue
        metrics, window = power['metrics'], power['window']
        conditions = '; '.join(c['library'] +
            (f' ({c["nom_voltage"]:g} V, {c["nom_temperature"]:g} °C)'
             if 'nom_voltage' in c and 'nom_temperature' in c else '') for c in power['libraries'])
        entry = dict(platform=row['platform'], isa=row['isa'], step=row['step'], libraries=conditions,
            clock_period_ns=power['period_ns'], cycles=window['cycles'], retired=window['retired'],
            duration_ms=metrics['duration_s']*1000, dynamic_mw=metrics['dynamic_power_w']*1000,
            leakage_uw=metrics['leakage_power_w']*1e6, total_mw=metrics['total_power_w']*1000,
            dynamic_energy_uj=metrics['dynamic_energy_j']*1e6, total_energy_uj=metrics['total_energy_j']*1e6,
            dynamic_nj_per_instruction=metrics['dynamic_energy_per_instruction_j']*1e9,
            measured_pins_percent=power['coverage']['measured_pin_fraction']*100,
            report=power['report'])
        rows.append(entry)
        body.append('<tr>'+''.join(f'<td>{html.escape(str(entry[k]))}</td>' for k in ('platform','isa'))+
            f'<td>F{entry["step"]}</td>'+
            f'<td>{html.escape(conditions)}</td>'+
            ''.join(f'<td>{entry[k]:,.{digits}f}</td>' for k, digits in (
                ('clock_period_ns',0),('cycles',0),('retired',0),('duration_ms',3),('dynamic_mw',3),
                ('leakage_uw',3),('total_mw',3),('dynamic_energy_uj',3),('total_energy_uj',3),
                ('dynamic_nj_per_instruction',3),('measured_pins_percent',2)))+
            f'<td><a href="{html.escape(power["report"])}">record</a> · '
            f'<a href="{html.escape(power["evidence"])}">power</a> · '
            f'<a href="{html.escape(power["activity_report"])}">gate execution</a></td></tr>')
        if power.get('detail') or power.get('recovery'):
            notes.append(f'<p>{html.escape(row["platform"])} F{row["step"]}: '
                f'{html.escape(power.get("detail") or "Recovered run; see record for retained execution evidence.")}</p>')
    if not rows:
        return ''
    with (output/'energy.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    return ('<section id="energy"><h2>Measured-activity power and energy</h2>'
        '<p>Only the listed configurations have energy measurements. OpenSTA uses the repaired-placement database, '
        'placement-estimated net RC and a separate mapped-cell waveform per backend. The CRC-checked RTL execution '
        'drives a gate shadow whose memory and fence outputs are checked against RTL. '
        'Each waveform covers the exact benchmark retirement window at the listed clock, rather than estimated Fmax. '
        'Dynamic power = internal + switching; energy = power × cycles × clock period.</p>'
        '<p>Activity is zero-delay, two-state and sampled at settled low/high clock phases. Clocks are ideal; '
        'clock-tree implementation, delay glitches, external memories and SoC power are excluded. Library voltage/corner differences are retained; '
        'these estimates do not establish silicon energy or a voltage-normalized technology advantage.</p>'
        '<p><a href="energy.csv">Download energy CSV</a></p><div class="scroll"><table><thead><tr>'
        '<th>Platform</th><th>ISA</th><th>Step</th><th>Library / nominal conditions</th><th>Period ns</th>'
        '<th>Cycles</th><th>Instructions</th><th>Window ms</th><th>Dynamic mW</th><th>Leakage µW</th>'
        '<th>Total mW</th><th>Dynamic µJ</th><th>Total µJ</th><th>Dynamic nJ/instruction</th>'
        '<th>Measured pins %</th><th>Evidence</th></tr></thead><tbody>'+''.join(body)+
        '</tbody></table></div>'+''.join(notes)+'</section>')


PAGE = r'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>uqu forwarding Pareto study</title>
<style>
:root{color-scheme:light dark}body{font:16px system-ui;max-width:1350px;margin:2rem auto;padding:0 1rem}
table{border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:.9rem}td,th{padding:.5rem;border-bottom:1px solid GrayText;text-align:right}
td:first-child,td:nth-child(3),th:first-child,th:nth-child(3){text-align:left}fieldset{display:inline-block;margin:.5rem;padding:.6rem;border:1px solid GrayText}
svg{width:100%;max-height:600px}svg text{fill:currentColor;font-size:13px}a{color:LinkText}.scroll{overflow-x:auto}
.front td{font-weight:700}.legend{display:flex;gap:1rem;flex-wrap:wrap}.legend span{border:2px solid;padding:.3rem .5rem}
</style>
<h1>Forwarding Pareto study</h1>
@PROGRESS@
<p>Six cumulative steps per ISA: none → WB→DE → WB→EX → MEM→EX → MEM→DE → EX→DE.
Per-ISA arithmetic and frontend settings are listed below. An ISA without M uses software arithmetic.</p>
<p>The same CoreMark workload is compiled separately for each ISA. CPI and retired counts describe different instruction streams across ISAs;
estimated workload time is the cross-ISA performance comparison. Each ladder is order-dependent, not an exhaustive search.</p>
<p>Repaired placement before CTS/routing on each selected backend, ideal clocks and estimated wire RC.
Tmin = characterization period − worst signed setup slack; Fmax = 1000/Tmin.
Estimated workload time = measured RTL cycles × Tmin. These are placement estimates, not routed or silicon frequency guarantees.</p>
<p id="context"></p><p><a href="summary.json">Combined data and input identities</a> · <a href="#comparison">Backend comparison</a> · <a href="#implementation">Synthesis / repaired layout</a> · <a href="#energy">Power / energy</a> · <a href="@REPORT@">Project report</a></p>
<div id="studies"></div>
<fieldset><legend>Visible ISAs</legend><div id="isas"></div></fieldset>
<fieldset><legend>Objective</legend><select id="metric">
<option value="execution_time_ms">Estimated execution time (ms), minimize</option>
<option value="f_max_mhz">Estimated Fmax (MHz), maximize</option>
<option value="cycles">RTL workload cycles, minimize</option>
<option value="cpi">RTL CPI, minimize (different ISA streams)</option></select></fieldset>
<fieldset><legend>Platform</legend><select id="platform"></select></fieldset>
<p class="legend"><span style="border-color:#278cca">○ RV32IMC</span><span style="border-color:#c178bb">□ RV32IC</span>
<span style="border-style:dashed">Dashed line: Pareto front among visible qualified points</span>
<span>Thick outline / bold row: frontier</span></p>
<p>Point outlines: solid for Sky130 HD, dashed for IHP SG13G2. Each backend has its own Pareto front.</p>
<p>Passed means both CRC/timer-checked RTL execution and placement/timing/electrical checks passed at the recorded target.
Failed or missing points remain in the table and are excluded from the frontier. Hover over points for details. F0…F5 identify forwarding steps.</p>
<svg id="plot" viewBox="0 0 1000 500" role="img" aria-label="Forwarding area and performance Pareto plot"></svg>
<p id="status"></p><div class="scroll"><table><thead><tr><th>Platform</th><th>ISA</th><th>Step</th><th>Enabled paths</th><th>Benchmark / placement</th>
<th>Cycles</th><th>CPI</th><th>Area (µm²)</th><th>Fmax (MHz)</th><th>Tmin (ns)</th><th>Est. time (ms)</th><th>Frontier</th><th>Evidence</th></tr></thead><tbody id="rows"></tbody></table></div>
@IMPLEMENTATION@
@COMPARISON@
@ENERGY@
<script id="data" type="application/json">@DATA@</script>
<script>
const data=JSON.parse(document.getElementById('data').textContent), byId=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const isas=[...new Set(data.rows.map(r=>r.isa))], colors={RV32IMC:'#278cca',RV32IC:'#c178bb'};
byId('context').textContent=`Common target: ${data.constraints.clock_period_ns} ns; reset arrival 0–1 ns, other I/O delays 4 ns. Independent memories grant immediately and respond next cycle.`;
byId('studies').innerHTML=data.studies.map(s=>{const c=s.configuration;return `<p><a href="${esc(s.report)}">${esc(s.isa)} ladder</a> · ${s.audited?`<a href="${esc(s.audit)}">input audit passed</a>`:'input audit pending'}<br>${c.ISA_M?`MUL=${esc(c.MUA_MUL)}, DIV=${esc(c.MUA_DIV)}, iterative unroll=${c.MUA_MULDIV_ITERUNROLL}`:'M hardware disabled'}; BP=${esc(c.MUA_BRANCH_PREDICTOR)}/${c.MUA_BP_ENTRIES}, BTB=${c.MUA_BTB_ENTRIES}, replay=${c.MUA_BTB_IDATA_HWORDS} halfwords; compressed handling=${esc(c.MUA_C_IMPL)}/${esc(c.MUA_C_DECOMPRESS_STAGE)}; retention=${c.MUA_DE_OPERAND_RETENTION}, redirect bypass=${esc(c.MUA_REDIRECT_BYPASS)}.</p>`}).join('');
byId('isas').innerHTML=isas.map(s=>`<label><input type="checkbox" value="${esc(s)}" checked> ${esc(s)}</label> `).join('');
byId('platform').innerHTML='<option value="">All backends</option>'+[...new Set(data.rows.map(r=>r.platform))].map(s=>`<option>${esc(s)}</option>`).join('');
const fmt=(x,n=2)=>Number.isFinite(x)?x.toLocaleString(undefined,{maximumFractionDigits:n,minimumFractionDigits:n}):'—';
function node(tag,attrs={},text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e;}
function render(){
 const enabled=new Set([...byId('isas').querySelectorAll('input:checked')].map(e=>e.value)),metric=byId('metric').value,maximize=metric==='f_max_mhz';
 const rows=data.rows.filter(r=>enabled.has(r.isa)&&(!byId('platform').value||r.platform===byId('platform').value));
 const pts=rows.filter(r=>r.qualified&&Number.isFinite(r.area_um2)&&r.area_um2>0&&Number.isFinite(r[metric])&&r[metric]>0);
 const cost=r=>maximize?-r[metric]:r[metric];
 const front=pts.filter(r=>!pts.some(o=>o.platform===r.platform&&o.area_um2<=r.area_um2&&cost(o)<=cost(r)&&(o.area_um2<r.area_um2||cost(o)<cost(r))));
 const ids=new Set(front.map(r=>r.id)),svg=byId('plot');svg.replaceChildren();
 if(pts.length){
  let xmin=Math.min(...pts.map(r=>r.area_um2)),xmax=Math.max(...pts.map(r=>r.area_um2)),ymin=Math.min(...pts.map(r=>r[metric])),ymax=Math.max(...pts.map(r=>r[metric]));
  const dx=Math.max(1,(xmax-xmin)*.1),dy=Math.max(.001,(ymax-ymin)*.15);xmin-=dx;xmax+=dx;ymin=Math.max(0,ymin-dy);ymax+=dy;
  const x=r=>100+820*(r.area_um2-xmin)/(xmax-xmin),y=r=>420-350*(r[metric]-ymin)/(ymax-ymin);
  for(let i=0;i<=5;i++){const xp=100+i*164,yp=420-i*70;
   svg.append(node('path',{d:`M${xp} 70V420 M100 ${yp}H920`,stroke:'currentColor',opacity:'.15',fill:'none'}));
   svg.append(node('text',{x:xp,y:445,'text-anchor':'middle'},fmt(xmin+i*(xmax-xmin)/5,0)));
   svg.append(node('text',{x:90,y:yp+4,'text-anchor':'end'},fmt(ymin+i*(ymax-ymin)/5,metric==='cycles'?0:2)));}
  svg.append(node('text',{x:500,y:485,'text-anchor':'middle'},'Placed cell area (µm²): lower is better'));
  svg.append(node('text',{x:100,y:35},byId('metric').selectedOptions[0].textContent));
  for(const platform of new Set(front.map(r=>r.platform))){
   const ordered=front.filter(r=>r.platform===platform).sort((a,b)=>a.area_um2-b.area_um2);
   if(ordered.length>1)svg.append(node('polyline',{points:ordered.map(r=>`${x(r)},${y(r)}`).join(' '),stroke:'currentColor','stroke-dasharray':'6 5',fill:'none'}));}
  const labelBoxes=[];
  for(const r of pts){const attrs={stroke:colors[r.isa]||'currentColor',fill:'none','stroke-width':ids.has(r.id)?3.5:1.5};
   if(r.platform==='ihp-sg13g2')attrs['stroke-dasharray']='3 2';
   const point=r.isa==='RV32IC'?node('rect',{...attrs,x:x(r)-6,y:y(r)-6,width:12,height:12}):node('circle',{...attrs,cx:x(r),cy:y(r),r:6});
   point.append(node('title',{},`${r.platform} ${r.isa} F${r.step}: ${r.paths.join(' + ')||'none'}\nCPI ${fmt(r.cpi,3)}, area ${fmt(r.area_um2,0)} µm², Fmax ${fmt(r.f_max_mhz)} MHz, time ${fmt(r.execution_time_ms,3)} ms${ids.has(r.id)?'\nPareto frontier':''}${r.critical_startpoint?`\nCritical path: ${r.critical_startpoint} → ${r.critical_endpoint}`:''}`));
   svg.append(point);
   const label=`${!byId('platform').value?(r.platform==='sky130hd'?'Sky ':'IHP '):''}${r.isa==='RV32IC'?'IC':'IMC'} F${r.step}`,width=label.length*8;
   for(const [ox,oy]of [[10,-9],[10,20],[-width-10,-9],[-width-10,20],[10,-25]]){
    const lx=Math.max(100,Math.min(920-width,x(r)+ox)),ly=Math.max(60,Math.min(420,y(r)+oy));
    const box={left:lx,right:lx+width,top:ly-13,bottom:ly+3};
    if(labelBoxes.some(b=>box.left<b.right+3&&box.right>b.left-3&&box.top<b.bottom+2&&box.bottom>b.top-2))continue;
    labelBoxes.push(box);svg.append(node('text',{x:lx,y:ly},label));break;
   }}
 }
 byId('status').textContent=`${pts.length} qualified points; ${front.length} on the visible per-backend Pareto fronts. Equal-cost points are retained.`;
 byId('rows').innerHTML=rows.map(r=>`<tr class="${ids.has(r.id)?'front':''}"><td>${esc(r.platform)}</td><td>${esc(r.isa)}</td><td>F${r.step}</td><td>${esc(r.paths.join(' + ')||'none')}</td><td>${esc(r.benchmark_status)} / ${esc(r.placement_status)}</td><td>${fmt(r.cycles,0)}</td><td>${fmt(r.cpi,3)}</td><td>${fmt(r.area_um2,0)}</td><td>${fmt(r.f_max_mhz)}</td><td title="${esc(`${r.critical_startpoint||'pending'} → ${r.critical_endpoint||''}`)}">${fmt(r.t_min_ns,3)}</td><td>${fmt(r.execution_time_ms,3)}</td><td>${ids.has(r.id)?'yes':'—'}</td><td>${['benchmark_report','placement_report'].filter(k=>r[k]).map(k=>`<a href="${esc(r[k])}">${k==='benchmark_report'?'RTL':'placement'}</a>`).join(' · ')}</td></tr>`).join('');
}
document.querySelectorAll('input,select').forEach(e=>e.addEventListener('change',render));render();
</script></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('studies', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--omit-energy', action='store_true', help='omit power evidence and energy tables')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    data = collect([p.resolve() for p in args.studies], output, include_power=not args.omit_energy)
    data['power_reporting'] = 'omitted' if args.omit_energy else 'included'
    encoded = json.dumps(data, indent=2, allow_nan=False)
    (output / 'summary.json').write_text(encoded + '\n')
    page = PAGE.replace('@REPORT@', os.path.relpath(ROOT / 'build/report/index.html', output))
    page = page.replace('@PROGRESS@', progress_html(data))
    page = page.replace('@IMPLEMENTATION@', physical_html(data))
    page = page.replace('@COMPARISON@', comparison_html(data, output))
    page = page.replace('@ENERGY@', '' if args.omit_energy else power_html(data, output))
    if args.omit_energy:
        page = page.replace('<a href="#energy">Power / energy</a> · ', '')
    write_physical_exports(data, output)
    (output / 'index.html').write_text(page.replace('@DATA@', encoded.replace('<', '\\u003c')))
    print('Report: ' + str(output / 'index.html'))


if __name__ == '__main__':
    main()
