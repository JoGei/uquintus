#!/usr/bin/env python3
"""Measure trace-free native RTL versus ETISS/CorePerfDSL host execution cost."""
import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import platform
import shutil
import shlex
import statistics
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'verif/sim/common'))
from benchmark_fast import read_memory
from benchmark_measure import BenchmarkWindow, benchmark_result, read_log
from config_frontend import load_configurations
from dependencies import digest
from elf_image import load_elf
from perfsim import generate, validate_benchmark


def summarize(samples):
    if not samples:
        raise ValueError('empty runtime sample set')
    wall = [s['wall_seconds'] for s in samples]
    return dict(samples=len(samples), median_seconds=statistics.median(wall),
                min_seconds=min(wall), max_seconds=max(wall),
                median_cpu_seconds=statistics.median(s['user_seconds']+s['system_seconds'] for s in samples),
                peak_rss_mib=max(s['max_rss_kib'] for s in samples)/1024)


def measure(command, directory, cpu, timeout):
    """Linux wait4 supplies per-process CPU/RSS without cumulative-child maxima.

    The clock includes process startup/JIT, native execution and final outputs;
    it excludes file preparation, Python validation and report formatting.
    """
    directory.mkdir(parents=True, exist_ok=False)
    argv = ['taskset', '--cpu-list', str(cpu), *map(str, command)]
    (directory/'command.json').write_text(json.dumps(argv, indent=2)+'\n')
    with (directory/'native.log').open('w') as log:
        started = time.perf_counter_ns()
        process = subprocess.Popen(argv, cwd=directory, stdout=log, stderr=subprocess.STDOUT)
        timer = threading.Timer(timeout, process.kill)
        timer.start()
        try:
            _, status, usage = os.wait4(process.pid, 0)
            elapsed = (time.perf_counter_ns()-started)/1e9
            process.returncode = os.waitstatus_to_exitcode(status)
        finally:
            timer.cancel()
            timer.join()
            if process.returncode is None:
                process.kill()
                process.wait()
    result = dict(wall_seconds=elapsed, user_seconds=usage.ru_utime,
                  system_seconds=usage.ru_stime, max_rss_kib=usage.ru_maxrss,
                  exit_code=process.returncode, command=argv, directory=str(directory))
    (directory/'process.json').write_text(json.dumps(result, indent=2)+'\n')
    if process.returncode:
        raise RuntimeError('native execution failed; see '+str(directory/'native.log'))
    return result


def native_signature(native, backend):
    if native.get('status') != 'passed':
        raise ValueError('native simulation did not pass')
    if backend == 'rtl':
        return {key: native[key] for key in ('cycles', 'retired', 'exit_code', 'start', 'stop')}
    models = {m['id']: (m['cycles'], m['instructions']) for m in native['models']}
    if len(models) != len(native['models']):
        raise ValueError('duplicate native timing model')
    return dict(functional_instructions=native['functional_instructions'], models=models)


def trace_free_command(command, backend, image):
    command = list(command)
    command[0] = str(Path(command[0]).resolve())
    command[1] = str(image.resolve())
    if backend == 'rtl':
        if len(command) == 10 and command[-1] == 'retire.bin':
            command.pop()
        if len(command) != 9:
            raise ValueError('unexpected RTL command/trace convention')
    else:
        if len(command) < 10:
            raise ValueError('unexpected ETISS command')
        command[9] = '0'
    return command


def validate(directory, backend, image, benchmark, expected):
    native = json.loads((directory/'native.json').read_text())
    if native_signature(native, backend) != expected:
        raise ValueError('trace-free result differs from validated accuracy run: '+str(directory))
    if list(directory.glob('timing-*.csv')) or any((directory/n).exists() for n in ('trace.csv','retire.bin')):
        raise ValueError('tracing unexpectedly enabled')
    text = read_log(image, read_memory(directory/'final-memory.bin'))
    if backend == 'rtl':
        window = BenchmarkWindow(image)
        window.start, window.stop = native['start'], native['stop']
        result = benchmark_result(text, benchmark, window.finish()['cycles'])
    else:
        result = validate_benchmark(text, benchmark)
    (directory/'benchmark.log').write_text(text)
    (directory/'validation.json').write_text(json.dumps(result, indent=2)+'\n')


def write_report(directory, record):
    (directory/'cost.json').write_text(json.dumps(record, indent=2)+'\n')
    lines = ['# Native simulation host cost', '',
             'Fresh processes, tracing disabled, one fixed CPU. Whole-process elapsed time includes '
             'startup/JIT, full software execution and native output writing; excludes compilation, '
             'Python validation and report generation. These are host seconds, not modeled cycles.', '',
             '| Workload | RTL single (s) | ISS+perfsim single (s) | Speedup | RTL sweep (s) | ISS+perfsim batch (s) | Sweep speedup |',
             '|---|---:|---:|---:|---:|---:|---:|']
    lines[4:4] = ['Status: '+record['status']+'.', '']
    for row in record['results']:
        if 'summary' not in row:
            continue
        s = row['summary']
        lines.append(f'| {row["workload"]} | {s["rtl_single_seconds"]:.4f} | '
                     f'{s["iss_single_seconds"]:.4f} | {s["single_speedup"]:.2f}× | '
                     f'{s["rtl_sweep_seconds"]:.4f} | {s["iss_batch_seconds"]:.4f} | {s["sweep_speedup"]:.2f}× |')
    lines += ['', f'Single and batch medians use {record["repeats"]} timed trials following '
              f'{record["warmups"]} discarded process runs per backend/workload. '
              f'The RTL sweep uses {record["sweep_repeats"]} timed trial(s) per configuration, '
              'reported as the sum of per-configuration medians. Every trial starts a new process; ETISS JIT is included each time.', '',
              f'Batch: {record["configuration_count"]} hardware configurations, '
              f'{record["timing_model_count"]} distinct timing states and one functional execution per workload. '
              'RTL runs the hardware configurations serially. No block-scheduling acceleration is assumed.', '']
    if 'totals' in record:
        totals = record['totals']
        lines += [f'Across the selected workloads: single-configuration speedup '
                  f'**{totals["single_speedup"]:.2f}×**; complete-sweep speedup **{totals["sweep_speedup"]:.2f}×**. '
                  'Ratios divide sums of runtime medians, not averages of speedups.', '']
    lines += ['Build costs are listed separately in `cost.json`: single-model lookup/build is timed with cache-hit status; '
              'batch and RTL build costs come from the retained accuracy-run provenance. They are historical observations, '
              'not a synchronized cold-build comparison. Tool installation and software compilation are excluded.', '',
              'Detailed samples, per-process CPU time, launcher-inclusive peak RSS, validations, commands and executable hashes: [cost.json](cost.json).', '']
    markdown = '\n'.join(lines)
    (directory/'cost.md').write_text(markdown)
    # Standalone portable inspection artifact, without a new report metric kind.
    rows = []
    for line in lines:
        if line.startswith('|') and not line.startswith('|---'):
            cells = line.strip('|').split('|')
            tag = 'th' if not rows else 'td'
            rows.append('<tr>'+''.join(f'<{tag}>{html.escape(c.strip())}</{tag}>' for c in cells)+'</tr>')
    body = '<h1>Native simulation host cost</h1><p>Status: '+html.escape(record['status'])+'</p><p>'
    body += html.escape(lines[2])+'</p><table>'+''.join(rows)+'</table>'
    for line in lines:
        if not line or line.startswith(('#','|','Status:')) or line == lines[2]:
            continue
        plain = html.escape(line).replace('**','').replace('`','')
        plain = plain.replace('[cost.json](cost.json)','<a href="cost.json">cost.json</a>')
        body += '<p>'+plain+'</p>'
    (directory/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Simulation host cost</title>'
        '<style>:root{color-scheme:light dark}body{font:16px system-ui;max-width:1200px;margin:2em auto;padding:0 1em}'
        'table{border-collapse:collapse;width:100%}th,td{border:1px solid GrayText;padding:.5em;text-align:right}'
        'th:first-child,td:first-child{text-align:left}</style>'+body)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--accuracy', type=Path, required=True, help='completed matched RTL/perfsim accuracy sweep')
    p.add_argument('--baseline', default='rv32imc-baseline')
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--sweep-repeats', type=int, default=1)
    p.add_argument('--warmups', type=int, default=1)
    p.add_argument('--cpu', type=int)
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--timeout', type=float, default=300)
    p.add_argument('--output', type=Path)
    p.add_argument('--etiss-root', default=os.environ.get('ETISS_ROOT',''))
    p.add_argument('--isa-python', default=os.environ.get('PERFSIM_ISA_PYTHON',sys.executable))
    p.add_argument('--model-python', default=os.environ.get('PERFSIM_MODEL_PYTHON',sys.executable))
    p.add_argument('--root', type=Path, default=ROOT/'build/deps/perfsim-upstream')
    args = p.parse_args()
    allowed = sorted(os.sched_getaffinity(0))
    cpu = args.cpu if args.cpu is not None else allowed[0]
    if min(args.repeats,args.sweep_repeats,args.jobs)<1 or args.warmups<0 or args.timeout<=0 or cpu not in allowed:
        p.error('positive repeats/jobs/timeout, nonnegative warmups and an allowed CPU required')
    if not args.etiss_root or not shutil.which('taskset'):
        p.error('ETISS_ROOT and taskset required')
    source = json.loads((args.accuracy/'accuracy.json').read_text())
    if (source['status']!='passed' or not source['results'] or
            any(r['status']!='passed' for r in source['results'])):
        raise ValueError('cost comparison requires successful accuracy evidence')
    rows = load_configurations([c['configuration']['path'] for c in source['configurations']],
                               source['memory']['imem_latency'],source['memory']['dmem_latency'])
    baseline = next((r for r in rows if r['name']==args.baseline),None)
    if baseline is None:
        raise ValueError('baseline is not in accuracy sweep')
    if any(r['resolved']!=old for r,old in zip(rows,source['configurations'])):
        raise ValueError('configuration/model differs from validated accuracy sweep')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    output = (args.output or ROOT/'build/investigations/perfsim-cost'/stamp).resolve()
    output.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(__file__,output/'benchmark_cost.py')
    (output/'accuracy.json').write_text(json.dumps(source,indent=2)+'\n')
    print('Cost artifacts:',output,flush=True)
    cached_keys = {p.parent.name for p in (ROOT/'build/perfsim-models').glob('*/build.json')
                   if json.loads(p.read_text()).get('status')=='passed'}
    started = time.perf_counter()
    single_dir, single_build = generate([baseline],args.root.resolve(),Path(args.isa_python).expanduser().absolute(),
        Path(args.model_python).expanduser().absolute(),etiss_root=Path(args.etiss_root).expanduser().resolve(),jobs=args.jobs,
        cmake_args=shlex.split(os.environ.get('PERFSIM_CMAKE_ARGS','')))
    build_lookup_seconds = time.perf_counter()-started
    native_single = single_dir/'native/uqu_perfsim'
    exemplars = [r for r in source['results'] if r['configuration']==args.baseline]
    first = json.loads((Path(exemplars[0]['perfsim'])/'report.json').read_text())
    batch_build = json.loads((Path(first['model_build'])/'build.json').read_text())
    if first['etiss_binaries_sha256'] != single_build['etiss_binaries_sha256']:
        raise ValueError('single and batched ETISS installations differ')
    first_rtl = json.loads((Path(exemplars[0]['rtl'])/'report.json').read_text())
    # Only immutable native/model inputs matter when reusing compiled backends;
    # calibration/report script edits do not alter their execution semantics.
    for name, expected in batch_build['source_sha256'].items():
        if name.endswith(('.h','.cpp','.in','.patch','CMakeLists.txt')) or name in (
                'verif/perfsim/model.py','config/selectors.json'):
            if digest(ROOT/name)!=expected:
                raise ValueError('native/model input changed since calibration: '+name)
    builds = {}
    for r in source['results']:
        rt = json.loads((Path(r['rtl'])/'report.json').read_text())
        if rt.get('compile_wall_seconds',0)>0:
            builds[r['configuration']] = rt['compile_wall_seconds']
    cpu_model = next((l.split(':',1)[1].strip() for l in Path('/proc/cpuinfo').read_text().splitlines()
                      if l.startswith('model name')), 'unknown')
    record = dict(schema_version=1,status='running',accuracy_run=str(args.accuracy.resolve()),baseline=args.baseline,
        configuration_count=len(rows),timing_model_count=len({r['model']['id'] for r in rows}),
        repeats=args.repeats,sweep_repeats=args.sweep_repeats,warmups=args.warmups,
        scope='native process wall time; traces off; fresh process and ETISS JIT per trial; serial fixed-CPU execution',
        resource_scope='wait4 process lifetime; peak RSS includes the pre-exec launcher address space and is not native working-set size',
        host=dict(cpu=cpu_model,pinned_cpu=cpu,allowed_cpus=allowed,kernel=platform.platform(),
                  load_start=os.getloadavg()),
        build_costs=dict(single_model=dict(directory=str(single_dir),recorded_seconds=single_build['generation_build_seconds'],
                            lookup_or_build_seconds=build_lookup_seconds,cache_hit=single_dir.name in cached_keys,
                            includes_cache_lookup=True,jobs=args.jobs),
                        historical_batch_seconds=batch_build['generation_build_seconds'],historical_rtl_seconds=builds),
        source_sha256={str(Path(__file__).relative_to(ROOT)):digest(Path(__file__))},
        source_snapshot='benchmark_cost.py',accuracy_snapshot='accuracy.json',
        tools=dict(rtl_simulator=first_rtl['simulator'],rtl_host_compiler=first_rtl['host_compiler'],
                   iss_build=single_build['tools'],batch_iss_build=batch_build['tools']),
        started_at=datetime.now(timezone.utc).isoformat(),results=[])
    write_report(output,record)
    try:
        for work_index, exemplar in enumerate(exemplars):
            print('Workload:',exemplar['workload'],flush=True)
            pairs = [r for r in source['results'] if r['workload']==exemplar['workload']]
            if len(pairs)!=len(rows) or len({r['elf'] for r in pairs})!=1:
                raise ValueError('incomplete/incompatible sweep workload')
            perfsim = Path(exemplar['perfsim'])
            sim = json.loads((perfsim/'report.json').read_text())
            if digest(Path(sim['command'][0])) != sim['native_executable_sha256']:
                raise ValueError('perfsim executable changed since calibration')
            image = load_elf(Path(exemplar['elf']))
            image_file = Path(sim['shared_execution'])/'program-image.bin'
            if digest(Path(exemplar['elf'])) != sim['workload']:
                raise ValueError('ELF changed since calibration')
            metadata = json.loads((Path(exemplar['elf']).parent/'build.json').read_text())
            benchmark = metadata['benchmark']
            batch_expected = native_signature(json.loads((perfsim/'native.json').read_text()),'iss')
            single_expected = dict(batch_expected,models={baseline['model']['id']:batch_expected['models'][baseline['model']['id']]})
            rt_report = json.loads((Path(exemplar['rtl'])/'report.json').read_text())
            commands = dict(rtl=trace_free_command(rt_report['command'],'rtl',image_file),
                            iss_single=trace_free_command(sim['command'],'iss',image_file),
                            iss_batch=trace_free_command(sim['command'],'iss',image_file))
            commands['iss_single'][0] = str(native_single)
            expected = dict(rtl=native_signature(json.loads((Path(exemplar['rtl'])/'native.json').read_text()),'rtl'),
                            iss_single=single_expected,iss_batch=batch_expected)
            work = dict(workload=exemplar['workload'],elf=exemplar['elf'],elf_sha256=sim['workload'],
                        single_samples={k:[] for k in commands},sweep_samples={},warmup_samples=[],
                        window_instructions=exemplar['window_instructions'],
                        executable_sha256={k:digest(Path(c[0])) for k,c in commands.items()})
            record['results'].append(work)
            workdir = output/('workload-'+str(work_index))
            workdir.mkdir()
            def trial(label, command, expect, backend, warm=False):
                sample = measure(command,workdir/label,cpu,args.timeout)
                validate(Path(sample['directory']),backend,image,benchmark,expect)
                sample['warmup'] = warm
                return sample
            names = list(commands)
            for repeat in range(args.warmups+args.repeats):
                # Rotate backend order to reduce a fixed frequency/cache bias.
                order = names[repeat%3:]+names[:repeat%3]
                for name in order:
                    warm = repeat<args.warmups
                    sample = trial(f'{name}-{repeat}',commands[name],expected[name],
                                   'rtl' if name=='rtl' else 'iss',warm)
                    (work['warmup_samples'] if warm else work['single_samples'][name]).append(sample)
                write_report(output,record)
            for pair in pairs:
                rt = json.loads((Path(pair['rtl'])/'report.json').read_text())
                if digest(Path(rt['command'][0]))!=rt['executable_sha256']:
                    raise ValueError('RTL executable changed')
                if digest(Path(pair['rtl'])/'program-image.bin')!=digest(image_file):
                    raise ValueError('RTL/ISS memory images differ')
                command = trace_free_command(rt['command'],'rtl',image_file)
                expect = native_signature(json.loads((Path(pair['rtl'])/'native.json').read_text()),'rtl')
                samples = [trial(pair['configuration']+'-'+str(i),command,expect,'rtl') for i in range(args.sweep_repeats)]
                work['sweep_samples'][pair['configuration']] = samples
                print('  RTL sweep:',pair['configuration'],f'{summarize(samples)["median_seconds"]:.3f} s',flush=True)
                write_report(output,record)
            s = {k:summarize(v) for k,v in work['single_samples'].items()}
            rtl_sum = sum(summarize(v)['median_seconds'] for v in work['sweep_samples'].values())
            work['statistics'] = s
            work['summary'] = dict(rtl_single_seconds=s['rtl']['median_seconds'],
                iss_single_seconds=s['iss_single']['median_seconds'],iss_batch_seconds=s['iss_batch']['median_seconds'],
                single_speedup=s['rtl']['median_seconds']/s['iss_single']['median_seconds'],
                rtl_sweep_seconds=rtl_sum,sweep_speedup=rtl_sum/s['iss_batch']['median_seconds'])
            print('  SUMMARY:',json.dumps(work['summary']),flush=True)
            write_report(output,record)
        totals = {k:sum(r['summary'][k] for r in record['results']) for k in (
            'rtl_single_seconds','iss_single_seconds','rtl_sweep_seconds','iss_batch_seconds')}
        totals.update(single_speedup=totals['rtl_single_seconds']/totals['iss_single_seconds'],
                      sweep_speedup=totals['rtl_sweep_seconds']/totals['iss_batch_seconds'])
        record.update(status='passed',totals=totals)
    except BaseException as error:
        record.update(status='failed',detail=str(error))
        raise
    finally:
        record['finished_at'] = datetime.now(timezone.utc).isoformat()
        record['host']['load_finish'] = os.getloadavg()
        write_report(output,record)


if __name__ == '__main__':
    main()
