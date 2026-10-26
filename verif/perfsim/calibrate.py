#!/usr/bin/env python3
"""Pair complete hardware YAMLs and benchmark ELFs with RTL accuracy evidence."""
import argparse
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import uuid
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'verif/sim/common'))
from benchmark_fast import run_fast
from compare import compare
from perfsim import configurations, execute, generate, prepare_blocks
from config_frontend import resolve_path
from hw_config import load_configuration
from dependencies import digest


def environment_workload(program, imem, dmem):
    """Reuse identical software bytes with explicitly derived harness metadata.

    Memory response latency is an execution-environment setting, not an ELF
    compiler input. Preserve the compiler/source identity and the parent record.
    """
    if min(imem,dmem)<1:raise ValueError('positive memory latencies required')
    metadata=program.parent/'build.json'
    data=json.loads(metadata.read_text())
    identity=hashlib.sha256(json.dumps([digest(program),digest(metadata),imem,dmem]).encode()).hexdigest()
    folder=ROOT/'build/perfsim-environments'/identity;folder.mkdir(parents=True,exist_ok=True)
    data['environment_derivation']=dict(parent_build=str(metadata),parent_sha256=digest(metadata),
        parent_memory=data['benchmark']['memory'],unchanged_elf_sha256=digest(program))
    data['benchmark']=dict(data['benchmark'],memory=dict(imem_latency=imem,dmem_latency=dmem),
                           max_cycles=data['benchmark']['max_cycles']*max(imem,dmem))
    shutil.copyfile(program,folder/'program.elf')
    (folder/'build.json').write_text(json.dumps(data,indent=2)+'\n')
    return folder/'program.elf'


def retained_rtl(evidence,config,program):
    """Reuse checked RTL, never stale sources or an unchecked trace."""
    if evidence is None:return None
    if evidence.get('status')!='passed':raise ValueError('RTL reuse requires passed evidence')
    for pair in evidence['results']:
        if pair['status']!='passed' or digest(Path(pair['elf']))!=digest(program):continue
        folder=Path(pair['rtl']);report=json.loads((folder/'report.json').read_text())
        if yaml.safe_load((folder/'config.yml').read_text())!=config:continue
        if report['status']!='passed':raise ValueError('retained RTL report failed')
        bench=json.loads((folder/'benchmark.json').read_text())
        memory=json.loads((program.parent/'build.json').read_text())['benchmark']['memory']
        if bench['memory']!=memory:continue
        for name,expected in report['source_sha256'].items():
            path=ROOT/name
            if not path.is_file() or digest(path)!=expected:
                raise ValueError('retained RTL input changed: '+name)
        trace=report['diagnostic_retirement_trace']
        if digest(folder/trace['file'])!=trace['sha256']:
            raise ValueError('retained RTL trace changed')
        return folder
    return None


def materialize_matrix(path, directory):
    """Expand an experiment matrix into complete, normally validated core YAMLs."""
    matrix = yaml.safe_load(path.read_text())
    if (not isinstance(matrix, dict) or set(matrix)!={'base','prefix','common','cases'} or
            not re.fullmatch('[a-z][a-z0-9_-]*', matrix['prefix']) or
            not isinstance(matrix['common'],dict) or not isinstance(matrix['cases'],dict) or not matrix['cases']):
        raise ValueError('invalid accuracy matrix')
    catalog = json.loads((ROOT/'config/selectors.json').read_text())
    base = load_configuration(resolve_path(matrix['base']), catalog)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, change in matrix['cases'].items():
        if not re.fullmatch('[a-z][a-z0-9_-]*', name) or not isinstance(change, dict):
            raise ValueError('invalid matrix case name/parameters')
        path = directory/(matrix['prefix']+'-'+name+'.yml')
        path.write_text(yaml.safe_dump(dict(base, **{**matrix['common'],**change}),sort_keys=False))
        load_configuration(path, catalog)
        paths.append(str(path))
    return paths


def statistics(results):
    errors = [r['comparison']['timing_error']['relative_error']
              for r in results if r['status'] == 'passed']
    counts = dict(pairs=len(errors), failed_pairs=sum(r['status']=='failed' for r in results),
                  pending_pairs=sum(r['status'] not in ('passed','failed') for r in results))
    if not errors:
        return counts
    return dict(counts, mean_signed_relative_error=sum(errors)/len(errors),
                mean_absolute_relative_error=sum(map(abs, errors))/len(errors),
                max_absolute_relative_error=max(map(abs, errors)))


def write_summary(directory, record):
    record['accuracy'] = statistics(record['results'])
    (directory/'accuracy.json').write_text(json.dumps(record, indent=2)+'\n')
    lines = ['# RTL/perfsim accuracy', '',
             'Identical ELF, complete hardware configuration and memory latencies per pair. '
             'Cycles use the same retirement window `(start, stop]`. '
             'Negative error means perfsim underestimates RTL. No correction factor is fitted.', '',
             '| Configuration | Workload | RTL cycles | Estimated cycles | RTL CPI | Estimated CPI | Error |',
             '|---|---|---:|---:|---:|---:|---:|']
    for r in record['results']:
        name, workload = r['configuration'], r['workload']
        if r['status'] != 'passed':
            lines.append(f'| {name} | {workload} | {r["status"].upper()} | | | | |')
            continue
        error = r['comparison']['timing_error']
        n = r['window_instructions']
        lines.append(f'| {name} | {workload} | {error["rtl_cycles"]:,} | '
                     f'{error["estimated_cycles"]:,} | {error["rtl_cycles"]/n:.4f} | '
                     f'{error["estimated_cycles"]/n:.4f} | {error["relative_error"]:+.2%} |')
    lines += ['', 'Machine-readable results and source/run provenance: [accuracy.json](accuracy.json).', '']
    (directory/'accuracy.md').write_text('\n'.join(lines))


def recompare(directory):
    """Re-evaluate retained streams without rebuilding or re-executing RTL."""
    record = json.loads((directory/'accuracy.json').read_text())
    if record['status'] == 'running':
        raise ValueError('cannot rewrite a running sweep')
    stream_cache = {}
    for r in record['results']:
        if 'rtl' not in r:
            continue
        try:
            r['comparison'] = compare(r['perfsim'], r['rtl'], stream_cache=stream_cache)
            report = json.loads((Path(r['perfsim'])/'report.json').read_text())
            r['window_instructions'] = next(m['value'] for m in report['metrics'] if m['name']=='instructions')
            r.update(status='passed')
            r.pop('detail', None)
        except Exception as error:
            r.update(status='failed', detail=str(error))
    complete = len(record['results']) == record.get('expected_pairs', len(record['results']))
    record['status'] = 'passed' if complete and record['results'] and all(r['status']=='passed' for r in record['results']) else 'failed'
    record['compared_at'] = datetime.now(timezone.utc).isoformat()
    write_summary(directory, record)
    print(json.dumps(record['accuracy'], indent=2), flush=True)
    if record['status'] != 'passed':
        raise RuntimeError('comparison failures remain; see accuracy.json')


def resimulate(directory, args):
    """Keep the RTL evidence and compare a newer model against the same ELFs."""
    record = json.loads((directory/'accuracy.json').read_text())
    if record['status'] == 'running':
        raise ValueError('cannot revise a running sweep')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    (directory/('accuracy-before-'+stamp+'.json')).write_text(json.dumps(record, indent=2)+'\n')
    memory = record['memory']
    rows = configurations([r['configuration']['path'] for r in record['configurations']],
                          memory['imem_latency'], memory['dmem_latency'])
    if any(a['configuration']['parameters'] != b['resolved']['configuration']['parameters']
           for a,b in zip(record['configurations'], rows)):
        raise ValueError('hardware inputs changed; start a new RTL sweep')
    model_dir, build = generate(rows, args.root.resolve(), Path(args.isa_python).expanduser().absolute(),
                               Path(args.model_python).expanduser().absolute(), etiss_root=Path(args.etiss_root).resolve(),
                               jobs=args.jobs, cmake_args=shlex.split(os.environ.get('PERFSIM_CMAKE_ARGS', '')))
    for elf in dict.fromkeys(r['elf'] for r in record['results']):
        native = execute(rows, model_dir, build, Path(elf), 100000000, 300, True, timing_trace=False)
        runs = {r['name']: str(run) for r,run in zip(rows,native)}
        for r in record['results']:
            if r['elf'] == elf:
                r['perfsim'] = runs[r['configuration']]
                r['status'] = 'pending'
                r.pop('comparison', None)
                r.pop('window_instructions', None)
    record['configurations'] = [r['resolved'] for r in rows]
    record['status'] = 'awaiting_comparison'
    write_summary(directory, record)
    recompare(directory)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--configs', nargs='+', help='complete hardware YAMLs, identical ISA')
    p.add_argument('--matrix', type=Path, help='expand a declared experiment into complete hardware YAMLs')
    p.add_argument('--elf', nargs='+', type=Path, help='ELFs from benchmark-build')
    p.add_argument('--recompare', type=Path, help='compare retained streams in a finished sweep')
    p.add_argument('--resimulate', type=Path, help='revise model estimates against retained RTL evidence')
    p.add_argument('--output', type=Path)
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--scheduler',choices=('instruction','map_explorer'),default='map_explorer')
    p.add_argument('--imem-latency',type=int)
    p.add_argument('--dmem-latency',type=int)
    p.add_argument('--reuse-rtl',type=Path,help='reuse a passed accuracy study after checking all RTL inputs and trace hashes')
    p.add_argument('--bender', default='bender')
    p.add_argument('--etiss-root', default=os.environ.get('ETISS_ROOT', ''))
    p.add_argument('--isa-python', default=os.environ.get('PERFSIM_ISA_PYTHON', sys.executable))
    p.add_argument('--model-python', default=os.environ.get('PERFSIM_MODEL_PYTHON', sys.executable))
    p.add_argument('--root', type=Path, default=ROOT/'build/deps/perfsim-upstream')
    args = p.parse_args()
    if args.recompare:
        return recompare(args.recompare.resolve())
    if args.resimulate:
        if not args.etiss_root or args.jobs < 1:
            p.error('resimulation requires ETISS_ROOT and positive jobs')
        return resimulate(args.resimulate.resolve(), args)
    if bool(args.configs)==bool(args.matrix) or not args.elf:
        p.error('choose --configs or --matrix, and supply --elf')
    if args.jobs < 1 or not args.etiss_root:
        p.error('positive jobs and ETISS_ROOT required')
    # Derive the environment from each ELF's benchmark metadata, never assume a
    # latency independently of the RTL runner. Reject non-benchmark inputs early.
    workloads = []
    for program in args.elf:
        program = program.resolve()
        if args.imem_latency is not None or args.dmem_latency is not None:
            original=json.loads((program.parent/'build.json').read_text())['benchmark']['memory']
            program=environment_workload(program,args.imem_latency if args.imem_latency is not None else original['imem_latency'],
                args.dmem_latency if args.dmem_latency is not None else original['dmem_latency'])
        metadata = json.loads((program.parent/'build.json').read_text())
        bench = metadata['benchmark']
        workloads.append((program, bench))
    environments = {tuple(sorted(b['memory'].items())) for _, b in workloads}
    if len(environments) != 1:
        p.error('one sweep requires identical benchmark memory settings')
    memory = dict(next(iter(environments)))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    directory = (args.output or ROOT/'build/investigations/perfsim-accuracy'/stamp).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    names = materialize_matrix(args.matrix, directory/'configs') if args.matrix else args.configs
    rows = configurations(names, memory['imem_latency'], memory['dmem_latency'],
                          contract='map_dse' if args.scheduler=='map_explorer' else 'queue')
    record = dict(schema_version=1, status='running', model_status='uncalibrated',
                  started_at=datetime.now(timezone.utc).isoformat(),
                  configurations=[r['resolved'] for r in rows], results=[], memory=memory,
                  expected_pairs=len(rows)*len(workloads),
                  workloads=[dict(elf=str(elf),benchmark=bench) for elf,bench in workloads],
                  definition='estimated/RTL cycles - 1; exact PC/original-encoding prefix through stop')
    print('Accuracy artifacts:', directory, flush=True)
    reuse=json.loads((args.reuse_rtl/'accuracy.json').read_text()) if args.reuse_rtl else None
    if reuse is not None:record['reused_rtl_evidence']=dict(path=str(args.reuse_rtl.resolve()),sha256=digest(args.reuse_rtl/'accuracy.json'))
    write_summary(directory, record)
    try:
        model_dir, build = generate(rows, args.root.resolve(), Path(args.isa_python).expanduser().absolute(),
                                    Path(args.model_python).expanduser().absolute(), etiss_root=Path(args.etiss_root).resolve(),
                                    jobs=args.jobs, cmake_args=shlex.split(os.environ.get('PERFSIM_CMAKE_ARGS', '')))
        runs = []
        for program, bench in workloads:
            selected,recorded=model_dir,build
            if args.scheduler=='map_explorer':
                selected,recorded,_=prepare_blocks(rows,model_dir,build,program,args.root.resolve(),
                    Path(args.isa_python).expanduser().absolute(),Path(args.model_python).expanduser().absolute(),
                    etiss_root=Path(args.etiss_root).resolve(),jobs=args.jobs,
                    cmake_args=shlex.split(os.environ.get('PERFSIM_CMAKE_ARGS','')),scheduler=args.scheduler)
            native = execute(rows, selected, recorded, program, 100000000, 300, True, timing_trace=False,
                             scheduler=args.scheduler,verify=args.scheduler=='map_explorer')
            runs.append((program, bench, native))
        # Keep one Verilator build per configuration across workloads.
        stream_cache = {}
        for index, row in enumerate(rows):
            shared = {}
            for program, bench, native in runs:
                result = dict(configuration=row['name'], workload=bench['name']+'/'+bench['profile'],
                              elf=str(program), perfsim=str(native[index]), status='running')
                record['results'].append(result)
                try:
                    rtl=retained_rtl(reuse,row['config'],program)
                    result['reused_rtl']=rtl is not None
                    if rtl is None:
                        rtl = run_fast(program, row['path'], row['config'], bender=args.bender,
                                       shared_build=shared, jobs=args.jobs, retire_trace=True)
                    result['rtl'] = str(rtl)
                    result['comparison'] = compare(native[index], rtl, stream_cache=stream_cache)
                    report = json.loads((native[index]/'report.json').read_text())
                    result['window_instructions'] = next(m['value'] for m in report['metrics'] if m['name']=='instructions')
                    result['status'] = 'passed'
                    print(row['name'], result['workload'],
                          f'{result["comparison"]["timing_error"]["relative_error"]:+.3%}', flush=True)
                except Exception as error:
                    result.update(status='failed', detail=str(error))
                    print('FAILED:', row['name'], result['workload'], error, flush=True)
                finally:
                    write_summary(directory, record)
        record['status'] = 'passed' if all(r['status']=='passed' for r in record['results']) else 'failed'
    except BaseException as error:
        record.update(status='failed', detail=str(error))
        raise
    finally:
        record['finished_at'] = datetime.now(timezone.utc).isoformat()
        write_summary(directory, record)
    if record['status'] != 'passed':
        raise RuntimeError('some RTL/perfsim comparisons failed; see '+str(directory/'accuracy.json'))


if __name__ == '__main__':
    main()
