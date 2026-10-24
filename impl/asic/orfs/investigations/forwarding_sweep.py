#!/usr/bin/env python3
"""Characterize a cumulative forwarding ladder with one fixed ISA and ELF.

Reuse the existing benchmark/placement artifact validation and measurements.
This is an order-dependent experiment, not an exhaustive forwarding search.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import html
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[4]
HELPER = Path(__file__).with_name('bpu_replay_sweep.py')
SPEC = importlib.util.spec_from_file_location('bpu_measurements', HELPER)
measure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measure)
PATHS = (
    ('wb2ex', 'MUA_FORWARD_WB_TO_EX'),
    ('mem2ex', 'MUA_FORWARD_MEM_TO_EX'),
    ('mem2de', 'MUA_FORWARD_MEM_TO_DE'),
    ('ex2de', 'MUA_FORWARD_EX_TO_DE'),
)
FORWARD_PARAMS = {'MUA_FORWARDING', *(parameter for _, parameter in PATHS)}


def make_cases(base, prefix='fwd-imc-b16-t16-h6-cif'):
    """WB-to-DE is implicit in the master switch; there is no WB-to-MEM path."""
    cases, configs = [], {}
    for step in range(6):
        config = dict(base, MUA_FORWARDING=int(step > 0))
        config.update({parameter: int(step >= index + 2)
                       for index, (_, parameter) in enumerate(PATHS)})
        paths = ['wb2de'] + [label for label, parameter in PATHS if config[parameter]] if step else []
        added = (['none', 'wb2de'] + [label for label, _ in PATHS])[step]
        name = f'{prefix}-f{step}-{added}'
        configs[name] = config
        cases.append(dict(name=name, step=step, added=added, paths=paths,
                          bp=base['MUA_BP_ENTRIES'], btb=base['MUA_BTB_ENTRIES'],
                          hwords=base['MUA_BTB_IDATA_HWORDS'],
                          c_variant=measure.compressed_variant(base)))
    return cases, configs


def render(directory, manifest):
    rows = []
    esc = html.escape
    tables = []
    for platform in manifest['platforms']:
        group = []
        for case in manifest['cases']:
            benchmark = json.loads((ROOT / case['benchmark']).read_text()) if case.get('benchmark') else {}
            placement = json.loads((ROOT / case[platform]).read_text()) if case.get(platform) else {}
            row = measure.collect(case, benchmark, placement, platform)
            row.update(step=case['step'], added=case['added'], paths=case['paths'])
            group.append(row)
        selected = {r['name'] for r in measure.frontier(group)}
        baseline = group[0]
        for row in group:
            row['local_frontier'] = row['name'] in selected
            if row['qualified'] and baseline['qualified']:
                row['runtime_speedup'] = baseline['execution_time_ms'] / row['execution_time_ms']
        rows.extend(group)
        def value(row, key, digits=3):
            number = row.get(key)
            return '—' if number is None else f'{number:,.{digits}f}'
        body = []
        for row in group:
            links = ' · '.join(f'<a href="{esc(os.path.relpath(ROOT / row[key], directory))}">{label}</a>'
                              for key, label in (('benchmark_report', 'benchmark'), ('placement_report', 'placement'))
                              if row.get(key))
            body.append('<tr>' + f'<td>{row["step"]}</td><td>{esc(" + ".join(row["paths"]) or "none")}</td>' +
                        f'<td>{esc(row["benchmark_status"])}/{esc(row["placement_status"])}</td>' +
                        ''.join(f'<td>{value(row, key, digits)}</td>' for key, digits in (
                            ('cycles', 0), ('cpi', 3), ('area_um2', 0), ('f_max_mhz', 2),
                            ('t_min_ns', 3), ('execution_time_ms', 3), ('runtime_speedup', 3))) +
                        f'<td>{"yes" if row["local_frontier"] else "—"}</td><td>{links}</td></tr>')
        tables.append(f'<h2>{esc(platform)}</h2><table><thead><tr><th>Step</th><th>Enabled paths</th>'
                      '<th>Benchmark/placement</th><th>Cycles</th><th>CPI</th><th>Area (µm²)</th>'
                      '<th>F_max (MHz)</th><th>T_min (ns)</th><th>Runtime (ms)</th>'
                      '<th>Speedup vs none</th><th>Local frontier</th><th>Evidence</th></tr></thead>'
                      '<tbody>' + ''.join(body) + '</tbody></table>')
    measure.write_json(directory / 'summary.json', dict(schema_version=1, context=manifest['context'], rows=rows))
    figures = ''.join(f'<p><object type="image/svg+xml" data="{name}"></object></p>'
                      for name in ('forwarding.svg', 'area-runtime.svg') if (directory / name).is_file())
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="color-scheme" content="light dark">'
            '<title>RV32IMC forwarding ladder</title><style>'
            'body{font-family:system-ui;margin:2rem}table{border-collapse:collapse;font-variant-numeric:tabular-nums}'
            'td,th{padding:.5rem;border-bottom:1px solid GrayText;text-align:right}td:nth-child(2){text-align:left}'
            'object{width:min(100%,1100px)}</style><h1>RV32IMC forwarding ladder</h1>'
            '<p>BP16 / BTB16 / six packed halfwords / IF decompression / multiplier selected by the recorded configuration. '
            'DIV remains iterative with unroll factor 8. WB→DE is implicit when the forwarding master is enabled. '
            'There is no WB→MEM bypass. Each step adds exactly one path; this ladder is order-dependent.</p>'
            '<p>Same CoreMark performance ELF, CRC checked, one-cycle instruction/data responses. '
            f'{manifest["context"]["clock_period_ns"]:g} ns mapping target. '
            'Placement estimates use ideal clocks and estimated wire RC, before CTS/routing. '
            'T_min = target period − full constrained-path setup slack; F_max = 1000/T_min. '
            'Runtime = measured cycles × T_min; this is an estimate, not a routed frequency measurement.</p>'
            '<p>Passed: flow checks succeeded. Missing: no completed evidence yet. Failed: inspect the flow record. '
            'Local frontier compares area and estimated runtime only within this ladder and platform. '
            'Speedup uses the stall-only point; larger is better.</p>'
            '<p><a href="summary.json">Summary JSON</a> · <a href="experiment.json">Inputs and configurations</a> · '
            + ('<a href="audit.json">Evidence audit</a> · ' if (directory / 'audit.json').is_file() else '') +
            '<a href="../../report/index.html">Project report</a></p>' + figures + ''.join(tables) + '</html>')
    (directory / 'index.html').write_text(page)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path)
    parser.add_argument('--base-config', type=Path, default=ROOT / 'config/rv32imc_bimodal_idata.yml')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/investigations/forwarding-rv32imc-60ns')
    parser.add_argument('--sdc', type=Path)
    parser.add_argument('--platforms', nargs='+', choices=('sky130hd', 'ihp-sg13g2'), default=['sky130hd'])
    parser.add_argument('--clock-period', type=float, default=60)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--bender', default=os.environ.get('BENDER', 'bender'))
    parser.add_argument('--orfs-root', default=os.environ.get('ORFS_ROOT', ''))
    parser.add_argument('--yosys', default=os.environ.get('YOSYS_EXE', ''))
    parser.add_argument('--openroad', default=os.environ.get('OPENROAD_EXE', ''))
    parser.add_argument('--summary-only', action='store_true')
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if args.summary_only:
        render(directory, json.loads((directory / 'experiment.json').read_text()))
        return
    if not args.elf or not args.sdc:
        parser.error('--elf and --sdc are required for measurements')
    if args.workers < 1 or args.jobs < 1 or not math.isfinite(args.clock_period) or args.clock_period <= 0:
        parser.error('workers/jobs and the finite clock period must be positive')
    if len(set(args.platforms)) != len(args.platforms):
        parser.error('platforms must be distinct')
    sys.path.insert(0, str(ROOT / 'verif/sim/common'))
    from hw_config import load_configuration
    base = load_configuration(args.base_config, json.loads((ROOT / 'config/selectors.json').read_text()))
    args.elf = args.elf.resolve()
    cases, configs = make_cases(base)
    for subdirectory in ('config', 'logs'):
        (directory / subdirectory).mkdir(exist_ok=True)
    (directory / 'audit.json').unlink(missing_ok=True)
    (directory / 'constraints.sdc').write_bytes(args.sdc.read_bytes())
    for name, config in configs.items():
        (directory / 'config' / (name + '.yml')).write_text(yaml.safe_dump(config, sort_keys=False))
    snapshots = {}
    for source, name in ((Path(__file__), 'measured-method.py.txt'), (HELPER, 'measured-helper.py.txt')):
        (directory / name).write_bytes(source.read_bytes())
        snapshots[name] = measure.sha(source)
    manifest = dict(schema_version=1, started_at=datetime.now(timezone.utc).isoformat(),
                    context=dict(base_config=str(args.base_config), base_config_sha256=measure.sha(args.base_config),
                                 elf=str(args.elf), elf_sha256=measure.sha(args.elf),
                                 clock_period_ns=args.clock_period, sdc_sha256=measure.sha(directory / 'constraints.sdc'),
                                 methods=snapshots, order=['wb2de', *[name for name, _ in PATHS]],
                                 scope='Cumulative forwarding ladder; fixed software, ISA and all other parameters'),
                    platforms=args.platforms, cases=cases, errors=[])
    def save():
        measure.write_json(directory / 'experiment.json', manifest)
        return render(directory, manifest)
    save()
    for phase in ('benchmark', *args.platforms):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(measure.execute, case, phase, args, directory, configs[case['name']],
                                   manifest['context']['elf_sha256']): case for case in cases}
            for index, future in enumerate(as_completed(pending), 1):
                case = pending[future]
                try:
                    path, reused = future.result()
                    case[phase] = path
                    status = json.loads((ROOT / path).read_text())['status']
                    print(f'{phase} {index}/{len(cases)} {case["name"]}: {status}' +
                          (' (reused)' if reused else ''), flush=True)
                    if status != 'passed':
                        manifest['errors'].append(f'{case["name"]}/{phase}: {status}')
                except Exception as error:
                    manifest['errors'].append(str(error))
                    print(str(error), flush=True)
                save()
        if manifest['errors']:
            break
    manifest['finished_at'] = datetime.now(timezone.utc).isoformat()
    save()
    if manifest['errors']:
        raise SystemExit('Some points failed; inspect experiment.json and flow evidence')
    for case in cases:
        for phase in ('benchmark', *args.platforms):
            if not measure.fresh(json.loads((ROOT / case[phase]).read_text())):
                raise SystemExit('Inputs changed during measurements; evidence must be regenerated')
    measure.audit(directory, manifest)
    render(directory, manifest)
    print('Summary: ' + str(directory / 'index.html'), flush=True)


if __name__ == '__main__':
    main()
