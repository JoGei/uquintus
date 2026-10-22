#!/usr/bin/env python3
"""Collect flow artifacts into a portable static build/report site."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import quote
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[1]
KINDS = {
    'regression': 'Component regressions', 'test': 'Core / software tests',
    'lint': 'RTL lint', 'software': 'Software builds',
    'synthesis': 'Synthesis / PPA', 'formal': 'Formal verification',
    'benchmark': 'Benchmarks',
}
STATES = ('error', 'failed', 'running', 'skipped', 'passed')
CORE_COMPONENTS = {'core', 'core_elf', 'uqu_core', 'riscv-tests'}
OUTCOME_LABELS = {
    'passed': 'The reported checks passed for their stated scope. Declared exclusions remain skipped.',
    'failed': 'The run was unsuccessful: a test, check, build or tool invocation failed.',
    'error': 'Evidence is inconsistent or unusable, or the runner reported an error. Read the run diagnostics.',
    'running': 'No final outcome has been recorded. An interrupted run may retain this label.',
    'skipped': 'The check was excluded or not executed. A skipped check is not a pass.',
    'not_reported': 'No retained results exist for this configuration and flow.',
}
INPUT_LABELS = {
    'match': 'All recorded input hashes match the available files. Unrecorded inputs and tool changes are not covered.',
    'changed': 'At least one recorded input differs from the current workspace. This labels historical evidence; it is not a test failure.',
    'unknown': 'No input hashes were recorded, or recorded input files are unavailable, so a match cannot be established.',
}
FILES = ('run.json', 'build.json', 'report.json', 'results.xml', 'execution.json',
         'config.yml', 'component.yml', 'selectors.json', 'lint.log',
         'simulation.log', 'build.log', 'program.map', 'software-build.json',
         'spike.json', 'spike.log', 'spike-process.log', 'spike-debug.cmd',
         'interrupts.json', 'timing.json', 'spike-inputs.txt', 'spike-irq-build.json', 'spike-irq-build.log',
         'benchmark.json', 'benchmark.log',
         'xif.jsonl', 'xif-agent.json', 'fpu.jsonl', 'zfinx-coverage.json')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def read_json(path):
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('expected a JSON object')
    return value


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec='seconds')


def esc(value):
    return html.escape(str(value), quote=True)


def badge(state, label=None):
    explanation = {**OUTCOME_LABELS, **INPUT_LABELS}.get(state, '')
    return f'<span class="badge {esc(state)}" title="{esc(explanation)}">{esc(label or state.replace("_", " "))}</span>'


def legend():
    def entries(labels):
        return ''.join(f'<dt>{badge(label)}</dt><dd>{esc(explanation)}</dd>'
                       for label, explanation in labels.items())

    return f'''<details class="legend" id="legend"><summary>Label legend: outcomes and recorded inputs</summary>
<p>Run outcomes and input evidence describe different things. A passed historical run can have changed inputs today.</p>
<div class="legend-grid"><div><h2>Run outcomes</h2><dl>{entries(OUTCOME_LABELS)}</dl></div>
<div><h2>Recorded inputs</h2><dl>{entries(INPUT_LABELS)}</dl>
<h2>Configuration labels</h2><p><b>Current preset</b>: defined in <code>config/*.yml</code> now.
<b>Core artifact snapshot</b>: recorded by a core-level flow; it may differ from current presets.
The fingerprint identifies the recorded parameter values.</p></div></div></details>'''


def aggregate(records):
    if not records:
        return 'not_reported'
    return next(state for state in STATES if any(r['status'] == state for r in records))


def junit(path):
    cases = []
    for case in ET.parse(path).findall('.//testcase'):
        problem = next((case.find(tag) for tag in ('error', 'failure', 'skipped')
                        if case.find(tag) is not None), None)
        state = {'error': 'error', 'failure': 'failed', 'skipped': 'skipped'}.get(
            problem.tag if problem is not None else '', 'passed')
        duration = float(case.get('time', '0'))
        if not math.isfinite(duration) or duration < 0:
            raise ValueError('invalid JUnit duration')
        cases.append({'name': case.get('name', ''), 'status': state,
                      'seconds': duration, 'detail': '' if problem is None else
                      (problem.get('message', '') + '\n' + (problem.text or ''))[:4000]})
    return cases


def configuration(name, parameters):
    if not isinstance(name, str) or not name or not isinstance(parameters, dict):
        raise ValueError('configuration needs a name and parameter object')
    fingerprint = digest(parameters)
    return {'id': digest([name, fingerprint])[:16], 'name': name,
            'fingerprint': fingerprint, 'parameters': parameters}


def inputs_status(record, root, hashes):
    changed, missing = [], []
    for filename, expected in record.items():
        source = Path(filename)
        if not source.is_absolute():
            source = root / source
        source = source.resolve()
        if not source.is_relative_to(root.resolve()) or not source.is_file():
            missing.append(filename)
            continue
        if source not in hashes:
            hashes[source] = hashlib.sha256(source.read_bytes()).hexdigest()
        if hashes[source] != expected:
            changed.append(filename)
    state = 'changed' if changed else 'unknown' if missing or not record else 'match'
    return {'status': state, 'recorded_files': len(record), 'changed': changed, 'missing': missing}


def normalize(path, build, root, hashes):
    raw = read_json(path)
    for field in ('parameters', 'source_sha256', 'header_sha256', 'input_sha256',
                  'context', 'component_manifest', 'elf'):
        if field in raw and not isinstance(raw[field], dict):
            raise ValueError(f'{field} must be an object')
    native = path.name == 'report.json'
    if native:
        if raw.get('schema_version') != 1 or raw.get('kind') not in KINDS:
            raise ValueError('report.json needs schema_version=1 and a supported kind')
        required = ('status', 'configuration', 'component', 'target', 'selection')
        if any(key not in raw for key in required):
            raise ValueError(f'report.json requires {required}')
        if not isinstance(raw['configuration'], dict):
            raise ValueError('configuration must contain name and parameters')
        config = configuration(raw['configuration']['name'], raw['configuration']['parameters'])
        kind = raw['kind']
    else:
        if not isinstance(raw.get('configuration'), str):
            raise ValueError('legacy configuration must be a file path')
        if path.name == 'run.json' and raw.get('action') not in ('test', 'lint'):
            raise ValueError('unsupported legacy action')
        name = Path(raw['configuration']).stem
        parameters = raw['parameters']
        snapshot = path.parent / 'config.yml'
        if snapshot.is_file():
            parameters = yaml.safe_load(snapshot.read_text())
        config = configuration(name, parameters)
        kind = 'software' if path.name == 'build.json' else (
            'lint' if raw['action'] == 'lint' else
            'test' if raw['component'] in ('core', 'core_elf') else 'regression')
    state = raw.get('status')
    if state not in STATES:
        raise ValueError(f'unsupported run status: {state!r}')
    context = raw.get('context', {})
    if not isinstance(context, dict):
        raise ValueError('comparison context must be an object')
    digest(context)  # Reject non-finite/non-JSON comparison keys before grouping.
    timing_paths=raw.get('timing_paths')
    # Flow artifacts may be produced incrementally; older records need not
    # duplicate the scoped paths already retained in their stage summary.
    if timing_paths is None and native and context.get('stage') in ('mapped_preplacement','placed_pre_cts'):
        summary=path.parent/'timing'/context['stage']/'summary.json'
        if summary.is_file():
            observation=read_json(summary)
            if observation.get('stage')!=context['stage']:
                raise ValueError('Timing artifact stage disagrees with run context')
            timing_paths=observation.get('paths')
    if timing_paths is None: timing_paths={}
    if not isinstance(timing_paths,dict): raise ValueError('timing_paths must be an object')
    for scope,timing_path in timing_paths.items():
        if not isinstance(scope,str) or not isinstance(timing_path,dict) or timing_path.get('status') not in ('timed','no_paths'):
            raise ValueError('Invalid timing path scope/status')
        if timing_path['status']=='timed' and (type(timing_path.get('slack_ns')) not in (int,float) or
                not math.isfinite(timing_path['slack_ns']) or any(not isinstance(timing_path.get(k),str) or not timing_path[k]
                for k in ('startpoint','endpoint'))):
            raise ValueError('Timed paths require finite slack_ns and nonempty endpoints')
    metrics = raw.get('metrics', []) if native else []
    if not isinstance(metrics, list):
        raise ValueError('metrics must be a list')
    for metric in metrics:
        if (not isinstance(metric, dict) or not isinstance(metric.get('name'), str) or
                not isinstance(metric.get('unit'), str) or
                type(metric.get('value')) not in (int, float) or
                not math.isfinite(metric['value'])):
            raise ValueError('each metric needs a name, finite numeric value and explicit unit')
    timestamp = path.stat().st_mtime
    time_basis = 'artifact modification time (legacy)'
    if raw.get('finished_at') or raw.get('started_at'):
        date = datetime.fromisoformat(raw.get('finished_at') or raw['started_at'])
        if date.utcoffset() is None:
            raise ValueError('run timestamps must include a timezone')
        timestamp, time_basis = date.timestamp(), 'producer timestamp'
    rel = path.relative_to(build).as_posix()
    record = {
        'id': hashlib.sha256(rel.encode()).hexdigest()[:20], 'kind': kind,
        'status': state, 'declared_status': state,
        'configuration': config, 'component': raw.get('component', path.parent.name),
        'target': raw.get('target', 'compiler' if kind == 'software' else path.parts[-4]),
        'selection': raw.get('selection', raw.get('test', path.parent.name)),
        'seed': raw.get('seed'), 'timestamp': timestamp, 'time': utc(timestamp),
        'time_basis': time_basis, 'source': rel, 'context': context,
        'metrics': list(metrics), 'timing_paths':timing_paths, 'cases': [], 'notes': [], 'artifacts': [],
        'revision': raw.get('revision'),
        'tools': {k: raw[k] for k in ('simulator', 'bender', 'compiler', 'compiler_info', 'host_compiler', 'upstream', 'packages', 'reference') if k in raw},
        'workload': raw.get('workload', raw.get('elf', {}).get('sha256')),
    }
    if native and raw.get('detail'):
        record['notes'].append(str(raw['detail']))
    for field in ('component', 'target', 'selection'):
        if not isinstance(record[field], str) or not record[field]:
            raise ValueError(f'{field} must be a nonempty string')
    if record['seed'] is not None and type(record['seed']) is not int:
        raise ValueError('seed must be an integer or null')
    scope = raw.get('configuration_scope')
    if scope is None:
        scope = 'core' if kind == 'software' or record['component'] in CORE_COMPONENTS else 'component'
    if scope not in ('core', 'component'):
        raise ValueError('configuration_scope must be core or component')
    record['configuration_scope'] = scope
    inputs = dict(raw.get('source_sha256', {}))
    inputs.update(raw.get('header_sha256', {}))
    inputs.update(raw.get('input_sha256', {}))
    record['inputs'] = inputs_status(inputs, root, hashes)
    record['inputs']['scope'] = raw.get('input_scope', 'declared inputs' if native else
        'software sources' if kind == 'software' else 'HDL and available headers only')
    if kind in ('regression', 'test', 'benchmark'):
        results = (path.parent / raw.get('results_file', 'results.xml')).resolve()
        if not results.is_relative_to(path.parent.resolve()):
            raise ValueError('results_file escapes the run directory')
        if results.is_file():
            record['cases'] = junit(results)
            manifest = raw.get('component_manifest', {})
            expected = manifest.get('tests') if raw.get('test') == 'all' else (
                [raw['test']] if raw.get('test') else None)
            excluded = {e['name'] for e in raw.get('excluded_tests', [])}
            if native and 'required_tests' in raw:
                expected = [*raw['required_tests'], *sorted(excluded)]
            names = [case['name'] for case in record['cases']]
            if state == 'passed' and (not names or
                    any(case['status'] != 'passed' and not (
                        case['status'] == 'skipped' and case['name'] in excluded)
                        for case in record['cases']) or
                    (expected is not None and sorted(names) != sorted(expected))):
                record['status'] = 'error'
                record['notes'].append('Passed metadata conflicts with JUnit selection/results.')
        elif state == 'passed' and (not native or 'results_file' in raw or kind == 'benchmark'):
            record['status'] = 'error'
            record['notes'].append('Passed test metadata has no results.xml evidence.')
    execution = path.parent / 'execution.json'
    if execution.is_file():
        detail = read_json(execution)
        for name in ('cycles', 'retired'):
            if type(detail.get(name)) is int:
                record['metrics'].append({'name': name, 'value': detail[name],
                                          'unit': 'cycles' if name == 'cycles' else 'instructions'})
        if detail.get('detail'):
            record['notes'].append(str(detail['detail']))
        if state == 'passed' and detail.get('status') != 'passed':
            record['status'] = 'error'
            record['notes'].append('Passed metadata conflicts with execution status.')
    if kind == 'benchmark':
        evidence_path = path.parent / 'benchmark.json'
        evidence = read_json(evidence_path) if evidence_path.is_file() else {}
        window, result = evidence.get('window', {}), evidence.get('result', {})
        measured = {m['name']: m['value'] for m in metrics}
        consistent = (evidence.get('status') == 'passed' and
            result.get('validation') == 'passed' and result.get('official_score') is False and
            type(window.get('cycles')) is int and window['cycles'] > 0 and
            type(window.get('retired')) is int and window['retired'] > 0 and
            measured.get('benchmark_cycles') == window['cycles'] and
            measured.get('benchmark_retired') == window['retired'] and
            measured.get('benchmark_cpi') == window['cycles'] / window['retired'] and
            measured.get('cycles_per_iteration') == result.get('cycles_per_iteration'))
        if state == 'passed' and not consistent:
            record['status'] = 'error'
            record['notes'].append('Passed benchmark conflicts with workload validation or measurement evidence.')
        record['notes'].append('Cycle-only RTL benchmark; no official benchmark score or silicon execution time is claimed.')
        if context.get('execution_mode') == 'fast':
            record['notes'].append('Fast native execution: workload CRC, completion, trap/watchdog and timer-window checks; no per-instruction ISA/RVFI checking.')
        elif context.get('execution_mode') == 'checked':
            record['notes'].append('Checked execution: instruction oracle, RVFI, per-edge counters and workload CRC checks.')
    offload = path.parent / 'xif-agent.json'
    if offload.is_file():
        evidence = read_json(offload)
        maximum = evidence.get('max_live')
        events = evidence.get('events')
        if type(maximum) is int and isinstance(events,list):
            record['metrics'].append({'name':'xif_max_live_offloads','value':maximum,'unit':'offloads'})
            for kind in ('issue','commit','kill','result','retract','invalid_result'):
                record['metrics'].append({'name':'xif_'+kind,'value':sum(
                    isinstance(e,dict) and e.get('type')==kind for e in events),'unit':'transactions'})
    differential = path.parent / 'spike.json'
    if differential.is_file():
        evidence = read_json(differential)
        record['notes'].append('Spike differential: ' + evidence.get('status', 'unknown'))
        if evidence.get('detail'): record['notes'].append(evidence['detail'])
        reference = raw.get('reference', {})
        count = evidence.get('compared_instructions')
        consistent = (evidence.get('status') == 'passed' and type(count) is int and count > 0 and
                      evidence.get('tool', {}).get('executable_sha256') == reference.get('executable_sha256') and
                      evidence.get('profile') == reference.get('profile'))
        if consistent:
            record['metrics'].append({'name': 'spike_compared_instructions', 'value': count, 'unit': 'instructions'})
            for field, unit in (('compared_traps','traps'), ('compared_mrets','instructions'),
                                ('compared_interrupts','interrupts'), ('checked_counter_cycles','cycles'),
                                ('compared_counter_accesses','accesses'), ('compared_mip_accesses','accesses'),
                                ('compared_fp_instructions','instructions'), ('compared_fp_csr_accesses','accesses')):
                value = evidence.get(field)
                if type(value) is int and value >= 0:
                    record['metrics'].append({'name':'spike_'+field, 'value':value, 'unit':unit})
        if state == 'passed' and not consistent:
            record['status'] = 'error'
            record['notes'].append('Passed metadata conflicts with Spike status/count/reference identity.')
    elif raw.get('reference') and raw.get('component') == 'core_elf' and state == 'passed':
        record['status'] = 'error'
        record['notes'].append('Passed differential run has no spike.json evidence.')
    artifacts = list(FILES)
    if native:
        if not isinstance(raw.get('artifacts', []), list):
            raise ValueError('artifacts must be a list of relative file paths')
        artifacts += raw.get('artifacts', [])
    for filename in dict.fromkeys(artifacts):
        if not isinstance(filename, str):
            raise ValueError('artifact paths must be strings')
        artifact = (path.parent / filename).resolve()
        if not artifact.is_relative_to(path.parent.resolve()):
            raise ValueError('artifact path escapes the run directory')
        if artifact.is_file():
            record['artifacts'].append({'path': filename, 'bytes': artifact.stat().st_size})
    # Large traces/binaries remain in the build; no broken off-site links.
    for filename in ('rvfi.jsonl', 'program.elf', 'dump.vcd', 'dump.fst'):
        artifact = path.parent / filename
        if artifact.is_file():
            record['artifacts'].append({'path': filename, 'bytes': artifact.stat().st_size,
                                        'omitted': 'large/raw artifact; retained in original run directory'})
    return record


def collect(build, root):
    records, issues, hashes = [], [], {}
    for directory, children, files in os.walk(build):
        children[:] = sorted(c for c in children if c not in ('obj', 'report') and not c.startswith('.'))
        here = Path(directory)
        if here == build:
            children[:] = [c for c in children if c.startswith('uquintus-')]
        candidates = ['report.json'] if 'report.json' in files else [
            name for name in ('run.json', 'build.json') if name in files]
        for name in candidates:
            path = here / name
            try:
                records.append(normalize(path, build, root, hashes))
            except (ValueError, KeyError, TypeError, OSError, ET.ParseError, yaml.YAMLError) as error:
                issues.append({'source': path.relative_to(build).as_posix(), 'detail': str(error)})
    # Retry only replaces the same scenario. Different seeds, selections,
    # programs, backends and comparison contexts remain independent evidence.
    newest = {}
    for record in records:
        key = digest([record['configuration']['id'], record['kind'], record['component'],
                      record['target'], record['selection'], record['seed'],
                      record['workload'], record['context']])
        previous = newest.get(key)
        if previous is None or (record['timestamp'], record['source']) > (previous['timestamp'], previous['source']):
            newest[key] = record
    latest = {r['id'] for r in newest.values()}
    for record in records:
        record['latest'] = record['id'] in latest
    configs = {r['configuration']['id']: dict(r['configuration'], preset=False, scope='component') for r in records}
    for record in records:
        if record['configuration_scope'] == 'core':
            configs[record['configuration']['id']]['scope'] = 'core'
    for path in sorted((root / 'config').glob('*.yml')):
        try:
            config = configuration(path.stem, yaml.safe_load(path.read_text()))
            configs[config['id']] = dict(config, preset=True, scope='core')
        except (ValueError, TypeError, OSError, yaml.YAMLError) as error:
            issues.append({'source': f'config/{path.name}', 'detail': str(error)})
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,
                                           stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = None
    return {'schema_version': 1, 'generated_at': utc(datetime.now(timezone.utc).timestamp()),
            'workspace_revision': revision, 'records': sorted(records, key=lambda r: (-r['timestamp'], r['id'])),
            'configurations': sorted(configs.values(), key=lambda c: (not c['preset'], c['name'], c['id'])),
            'issues': issues}


def page(title, body, depth=0):
    prefix = '../' * depth
    nav = [('index.html', 'Overview'), ('configurations.html', 'Configurations')]
    nav += [(kind + '/index.html', label) for kind, label in KINDS.items()]
    links = ''.join(f'<a href="{prefix}{path}">{esc(label)}</a>' for path, label in nav)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · uquintus</title><link rel="stylesheet" href="{prefix}assets/report.css">
<script defer src="{prefix}assets/report.js"></script></head><body>
<header><a class="brand" href="{prefix}index.html">uquintus <span>build report</span></a>
<a href="{prefix}data.json">JSON data ↗</a></header><nav>{links}</nav><main><h1>{esc(title)}</h1>
{legend()}{body}</main><footer>Generated from flow artifacts · No result means no evidence ·
Matching recorded inputs does not cover unrecorded testbench or tool changes.</footer></body></html>'''


def filters(history=False):
    extra = '''<label>Runs<select id="scope"><option value="latest">Latest per scenario</option>
<option value="all">Full history</option></select></label>''' if history else ''
    return f'''<div class="filters"><label>Search<input id="search" type="search" placeholder="Configuration, component, target…"></label>
<label>Status<select id="status"><option value="">All statuses</option>
    {''.join(f'<option>{s}</option>' for s in (*STATES, 'not_reported'))}</select></label>{extra}
<span id="visible-count" aria-live="polite"></span></div>'''


def run_table(records, depth=1):
    prefix = '../' * depth
    rows = []
    for r in records:
        config = r['configuration']
        reference = r['tools'].get('reference')
        reference_label = ('Spike ' + str(reference.get('executable_sha256', 'unknown'))[:8] +
                           ' · ' + reference.get('profile','unknown profile')) if isinstance(reference, dict) else ''
        search = ' '.join(str(x) for x in (config['name'], config['id'], r['component'], r['target'], r['selection'], r['seed'], reference_label))
        cases = Counter(c['status'] for c in r['cases'])
        counts = ', '.join(f'{n} {s}' for s, n in sorted(cases.items())) or '—'
        attrs = f'data-search="{esc(search.lower())}" data-status="{r["status"]}" data-latest="{int(r["latest"])}" data-config="{config["id"]}"'
        rows.append(f'''<tr {attrs}><td><a href="{prefix}runs/{r['id']}.html">{badge(r['status'])}</a></td>
<td title="{config['fingerprint']}">{esc(config['name'])}<small>{config['fingerprint'][:8]}</small></td>
<td>{esc(r['component'])}</td><td>{esc(r['target'])}</td><td>{esc(r['selection'])}<small>seed {esc(r['seed'] if r['seed'] is not None else '—')}</small><small>{esc(reference_label)}</small></td>
<td>{esc(counts)}</td><td>{badge(r['inputs']['status'])}<small>{esc(r['inputs']['scope'])}</small></td>
<td>{esc(r['time'])}<small>{esc(r['time_basis'])}</small></td></tr>''')
    return '''<div class="table-scroll"><table class="filter-table"><thead><tr>''' + ''.join(
        f'<th><button class="sort" type="button">{label}</button></th>' for label in
        ('Outcome', 'Configuration', 'Component', 'Target', 'Scenario', 'Test cases', 'Recorded inputs', 'Observed at')) + \
        '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'


def metric_charts(records):
    groups = defaultdict(list)
    for r in records:
        if r['latest'] and r['status'] == 'passed' and r['context']:
            for metric in r['metrics']:
                groups[(json.dumps(r['context'], sort_keys=True), metric['name'], metric['unit'])].append((r, metric['value']))
    charts = []
    for (context, name, unit), values in sorted(groups.items()):
        if any(value < 0 for _, value in values):
            # Slack/TNS must remain visible when timing is missed. A table
            # preserves signed values without implying a positive bar length.
            rows = ''.join(f'<tr><td><a href="../runs/{r["id"]}.html">'
                           f'{esc(r["configuration"]["name"])} · {esc(r["component"])}</a></td>'
                           f'<td>{esc(value)} {esc(unit)}</td></tr>' for r,value in values)
            charts.append(f'<section><h2>{esc(name)}</h2><p class="context">Comparison context: {esc(context)}</p>'
                          f'<table><thead><tr><th>Configuration / component</th><th>Value</th></tr></thead>'
                          f'<tbody>{rows}</tbody></table></section>')
            continue
        largest = max((v for _, v in values), default=0) or 1
        bars = ''.join(f'<div class="metric-row"><a href="../runs/{r["id"]}.html">{esc(r["configuration"]["name"])} · {esc(r["component"])}</a>'
                       f'<div class="bar-track"><span style="width:{100 * (value / largest):.2f}%"></span></div>'
                       f'<b>{esc(value)} {esc(unit)}</b></div>' for r, value in values)
        charts.append(f'<section><h2>{esc(name)}</h2><p class="context">Comparison context: {esc(context)}</p>{bars}</section>')
    return ''.join(charts)


def render(site, data):
    records = data['records']
    core_configs = [c for c in data['configurations'] if c['scope'] == 'core']
    latest = [r for r in records if r['latest']]
    counts = Counter(r['status'] for r in latest)
    total = len(latest) or 1
    chart = ''.join(f'<span class="{state}" style="width:{100 * counts[state] / total:.3f}%" title="{state}: {counts[state]}"></span>'
                    for state in STATES if counts[state])
    cards = []
    for kind, label in KINDS.items():
        selected = [r for r in latest if r['kind'] == kind]
        summary = ', '.join(f'{n} {s}' for s, n in sorted(Counter(r['status'] for r in selected).items()))
        cards.append(f'<a class="card" href="{kind}/index.html"><h2>{esc(label)}</h2>{badge(aggregate(selected))}'
                     f'<p>{esc(summary or "No artifacts reported yet")}</p></a>')
    issues = ''.join(f'<li><code>{esc(i["source"])}</code>: {esc(i["detail"])}</li>' for i in data['issues'])
    body = f'''<p class="lead">Configurations, execution results and implementation evidence in one artifact.</p>
<p>Generated {esc(data['generated_at'])} · Workspace revision <code>{esc(data['workspace_revision'] or 'unknown')}</code></p>
<div class="stats"><div><b>{len(records)}</b> recorded runs</div><div><b>{len(latest)}</b> latest scenarios</div>
<div><b>{len(core_configs)}</b> core configurations</div><div><b>{len(data['issues'])}</b> collection issues</div></div>
<div class="status-bar" aria-label="Latest scenario outcomes">{chart}</div>
<p>{' · '.join(f'{counts[s]} {s}' for s in STATES if counts[s]) or 'No runs recorded'}</p>
<div class="cards">{''.join(cards)}</div>
<section><h2>Reading this report</h2><p>Latest means the newest retry of the same configuration, target, component, selection, seed, workload and comparison context.
Different seeds and partial suites remain separate. Historical failures are retained. Expected-failure fixtures are failures unless a producer explicitly classifies their check outcome.</p>
<p>Source hashes are checked against the workspace at report generation. Older records cover HDL and available headers only; their timestamps use artifact modification times.
Run records without revision metadata are not attributed to the current commit. Formal and benchmark claims require their own flow results.</p></section>
<section><h2>Collection issues</h2>{'<ul>' + issues + '</ul>' if issues else '<p>No unreadable or malformed records.</p>'}</section>'''
    (site / 'index.html').write_text(page('Project status', body))
    for kind, label in KINDS.items():
        directory = site / kind
        directory.mkdir()
        selected = [r for r in records if r['kind'] == kind]
        body = f'<p>{len(selected)} recorded runs. Filters change the view; underlying records remain available in JSON.</p>'
        if not selected:
            body += '<div class="empty">No artifacts reported yet. This flow has no verification or performance claim in this report.</div>'
        else:
            body += filters(True) + run_table(selected) + metric_charts(selected)
        (directory / 'index.html').write_text(page(label, body, 1))

    rows = []
    for config in core_configs:
        selected = [r for r in latest if r['configuration']['id'] == config['id']]
        cells = []
        for kind in KINDS:
            subset = [r for r in selected if r['kind'] == kind]
            counts = Counter(r['status'] for r in subset)
            label = ', '.join(f'{v} {k}' for k, v in sorted(counts.items())) or 'not reported'
            cells.append(f'<td><a href="{kind}/index.html?config={config["id"]}">{badge(aggregate(subset), label)}</a></td>')
        rows.append(f'<tr data-search="{esc((config["name"] + " " + config["id"]).lower())}" data-status="{aggregate(selected)}">'
                    f'<td>{esc(config["name"])}<small>{config["fingerprint"][:8]} · {"current preset" if config["preset"] else "core artifact snapshot"}</small></td>{"".join(cells)}</tr>')
    options = ''.join(f'<option value="{c["id"]}">{esc(c["name"])} · {c["fingerprint"][:8]}</option>' for c in core_configs)
    # Escaping '<' prevents script termination through configuration values.
    config_json = json.dumps(core_configs, allow_nan=False).replace('<', '\\u003c').replace('&', '\\u0026')
    body = f'''<p>This view covers current core presets and configuration snapshots recorded by core-level flows.
Component-only experiments remain available on the component regression and run-detail pages.</p>
<p>Names are paired with a full parameter fingerprint. Reusing a YAML filename with changed parameters creates a distinct snapshot.</p>
<section><h2>Compare parameters</h2><div class="filters"><label>Configuration A<select id="compare-a">{options}</select></label>
<label>Configuration B<select id="compare-b">{options}</select></label></div>
<div id="parameter-comparison" class="table-scroll"></div><script type="application/json" id="configuration-data">{config_json}</script></section>
<h2>Results matrix</h2>{filters()}<div class="table-scroll"><table class="filter-table"><thead><tr><th>Configuration</th>
{''.join(f'<th>{esc(label)}</th>' for label in KINDS.values())}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>'''
    (site / 'configurations.html').write_text(page('Configurations', body))
    directory = site / 'runs'
    directory.mkdir()
    for r in records:
        config = r['configuration']
        cases = ''.join(f'<tr><td>{esc(c["name"])}</td><td>{badge(c["status"])}</td><td>{c["seconds"]:.6g}</td>'
                        f'<td><pre>{esc(c["detail"])}</pre></td></tr>' for c in r['cases'])
        metrics = ''.join(f'<tr><td>{esc(m["name"])}</td><td>{esc(m["value"])}</td><td>{esc(m["unit"])}</td></tr>' for m in r['metrics'])
        timing_rows=[]
        labels=dict(full='All constrained paths',reg_to_reg='Internal: register to register',
                    input_to_reg='Interface: input to register',reg_to_output='Interface: register to output',
                    input_to_output='Interface: input to output')
        for scope,path in r['timing_paths'].items():
            name,_,delay=scope.rpartition('_')
            check={'max':'Setup','min':'Hold'}.get(delay,delay)
            if path['status']=='timed':
                cells=f'<td>{esc(path["startpoint"])}</td><td>{esc(path["endpoint"])}</td><td>{path["slack_ns"]:.6g}</td>'
            else: cells='<td colspan="3">No constrained paths</td>'
            timing_rows.append(f'<tr><td>{esc(labels.get(name,name))}</td><td>{esc(check)}</td>{cells}</tr>')
        timing=('''<h2>Critical timing paths</h2><p>Slacks use the recorded constraints and stage.
Internal paths are a diagnostic; the full-interface result remains the frequency reference.</p>
<div class="table-scroll"><table><thead><tr><th>Scope</th><th>Check</th><th>Startpoint</th><th>Endpoint</th><th>Slack (ns)</th></tr></thead>
<tbody>'''+''.join(timing_rows)+'</tbody></table></div>') if timing_rows else ''
        artifacts = ''.join(f'<li>{esc(a["path"])} · {a["bytes"]:,} bytes · ' +
                            (f'<a href="../{a["href"]}">open artifact</a>' if 'href' in a else esc(a.get('omitted', 'not bundled'))) + '</li>' for a in r['artifacts'])
        body = f'''<p>{badge(r['status'])} {esc(r['component'])} · {esc(r['target'])} · {esc(r['selection'])} · seed {esc(r['seed'])}</p>
<p>Configuration {esc(config['name'])} · <code>{config['fingerprint']}</code></p>
<p>{esc(r['time'])} ({esc(r['time_basis'])}) · {"latest scenario result" if r['latest'] else "historical result"}</p>
<p>Original metadata: <code>build/{esc(r['source'])}</code></p>
<p>Recorded revision: <code>{esc(r['revision'] or 'unknown / not recorded')}</code></p>
<p>Recorded inputs: {badge(r['inputs']['status'])} · {esc(r['inputs']['scope'])}</p>
{''.join(f'<p class="notice">{esc(note)}</p>' for note in r['notes'])}
<h2>Artifacts</h2><ul>{artifacts}</ul>
<h2>Test cases</h2><div class="table-scroll"><table><thead><tr><th>Case</th><th>Status</th><th>Wall seconds</th><th>Diagnostics</th></tr></thead><tbody>{cases}</tbody></table></div>
<h2>Metrics</h2><table><thead><tr><th>Metric</th><th>Value</th><th>Unit</th></tr></thead><tbody>{metrics}</tbody></table>
{timing}
<details><summary>Parameters, provenance, tools and comparison context</summary><pre>{esc(json.dumps({k:r[k] for k in ('configuration','inputs','tools','context')},indent=2))}</pre></details>'''
        (directory / f'{r["id"]}.html').write_text(page(f'{config["name"]} / {r["component"]}', body, 1))
    summary = ['# uquintus build report', '', f'Generated {data["generated_at"]}.', '',
               'Open [index.html](index.html) for filters, configuration comparison and run details.', '',
               '| Flow | Latest scenarios | Outcome |', '| --- | ---: | --- |']
    for kind, label in KINDS.items():
        selected = [r for r in latest if r['kind'] == kind]
        summary.append(f'| [{label}]({kind}/index.html) | {len(selected)} | {aggregate(selected)} |')
    (site / 'index.md').write_text('\n'.join(summary) + '\n')


def generate(build, output, root=ROOT, artifact_limit=512 * 1024):
    build, output, root = build.resolve(), output.resolve(), root.resolve()
    if output.parent != build or output.name.startswith('uquintus-'):
        raise ValueError('report output must be a direct build child outside flow directories')
    if output.exists() and not (output / '.uqu-report').is_file():
        raise ValueError('refusing to replace a directory not generated by this reporter')
    output.parent.mkdir(parents=True, exist_ok=True)
    data = collect(build, root)
    with tempfile.TemporaryDirectory(prefix='.uqu-report-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'site'
        stage.mkdir()
        shutil.copytree(Path(__file__).parent / 'report_assets', stage / 'assets')
        for r in data['records']:
            for artifact in r['artifacts']:
                if artifact.get('omitted'):
                    continue
                if artifact['bytes'] > artifact_limit:
                    artifact['omitted'] = f'exceeds report artifact limit ({artifact_limit} bytes)'
                    continue
                relative = Path('artifacts') / r['id'] / artifact['path']
                source = build / Path(r['source']).parent / artifact['path']
                destination = stage / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copyfile(source, destination)
                    artifact['href'] = quote(relative.as_posix(), safe='/')
                except OSError as error:
                    artifact['omitted'] = f'unavailable during collection: {error}'
        render(stage, data)
        (stage / 'data.json').write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')
        (stage / '.nojekyll').touch()
        (stage / '.uqu-report').write_text('uquintus generated report v1\n')
        previous = Path(temporary) / 'previous'
        if output.exists():
            output.rename(previous)
        try:
            stage.rename(output)
        except BaseException:
            if previous.exists():
                previous.rename(output)
            raise
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=ROOT / 'build')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/report')
    parser.add_argument('--artifact-limit', type=int, default=512 * 1024)
    args = parser.parse_args()
    if args.artifact_limit < 0:
        parser.error('--artifact-limit must be nonnegative')
    # Serialize report writers; flow producers continue writing their own runs.
    import fcntl
    args.build.mkdir(parents=True, exist_ok=True)
    with (args.build / '.report.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = generate(args.build, args.output, artifact_limit=args.artifact_limit)
    print(f'Report: {args.output.resolve() / "index.html"}')
    print(f'{len(data["records"])} runs, {sum(c["scope"] == "core" for c in data["configurations"])} core configurations, '
          f'{len(data["issues"])} collection issues')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
