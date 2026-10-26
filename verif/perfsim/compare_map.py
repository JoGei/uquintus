#!/usr/bin/env python3
"""Validate and time upstream MAPExplorer against a retained RTL accuracy matrix."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shlex
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'verif/sim/common'))
from perfsim import generate, execute, prepare_blocks
from config_frontend import load_configurations
from dependencies import digest
from benchmark_cost import measure, native_signature, summarize, validate
from elf_image import load_elf
from compare import compare as compare_rtl


def report(folder, record):
    errors=[c['timing_error']['absolute_relative_error'] for r in record['results'] for c in r.get('rtl_comparisons',[])]
    if errors:
        record['accuracy']=dict(pairs=len(errors),mean_absolute_relative_error=sum(errors)/len(errors),
                                worst_absolute_relative_error=max(errors))
    (folder/'comparison.json').write_text(json.dumps(record, indent=2)+'\n')
    lines = ['# Upstream MAPExplorer comparison', '', 'Status: '+record['status']+'.', '',
             'Upstream composed-block scheduling with shared trace-driven model groups. '
             'RTL accuracy is measured separately from instruction/block equivalence. Host timing covers fresh native '
             'processes/JIT, pinned to one CPU, with traces and reference checking disabled.', '',
             '| Workload | Instruction (s) | MAPExplorer (s) | Speedup | Blocks | RTL MAPE |'+(' Queue hybrid (s) | Hybrid/MAP speedup |' if record.get('queue_baseline') else ''),
             '|---|---:|---:|---:|---:|---:|'+('---:|---:|' if record.get('queue_baseline') else '')]
    for r in record['results']:
        if 'summary' not in r: continue
        s = r['summary'];a=s['instruction']['median_seconds'];b=s['map_explorer']['median_seconds']
        tail=''
        if 'queue_hybrid' in s:
            q=s['queue_hybrid']['median_seconds'];tail=f' {q:.4f} | {q/b:.2f}× |'
        lines.append(f'| {r["workload"]} | {a:.4f} | {b:.4f} | {a/b:.2f}× | {r["preparation"]["generation"]["blocks"]} | {100*sum(c["timing_error"]["absolute_relative_error"] for c in r["rtl_comparisons"])/len(r["rtl_comparisons"]):.4f}% |'+tail)
    if errors:
        lines += ['', f'RTL cycle error across {len(errors)} pairs: mean {100*record["accuracy"]["mean_absolute_relative_error"]:.6f}%; worst {100*max(errors):.6f}%.']
    lines += ['', 'Extraction and compilation costs, sample ranges, executable identities, checked reference runs '
              'and retained RTL evidence are recorded in [comparison.json](comparison.json).']
    (folder/'comparison.md').write_text('\n'.join(lines)+'\n')
    accuracy=['# MAP-DSE versus RTL','', '| Configuration | Workload | RTL cycles | MAP-DSE cycles | RTL CPI | MAP-DSE CPI | Error |', '|---|---|---:|---:|---:|---:|---:|']
    for r in record['results']:
        for c in r.get('rtl_comparisons',[]):
            e=c['timing_error'];n=c['window_instructions']
            accuracy.append(f'| {c["configuration"]} | {r["workload"]} | {e["rtl_cycles"]:,} | {e["estimated_cycles"]:,} | {e["rtl_cycles"]/n:.4f} | {e["estimated_cycles"]/n:.4f} | {100*e["relative_error"]:+.6f}% |')
    (folder/'accuracy.md').write_text('\n'.join(accuracy)+'\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--accuracy', type=Path, required=True)
    p.add_argument('--workloads', default='', help='comma-separated workload suffixes; empty selects all')
    p.add_argument('--queue-baseline', type=Path, help='retained acceleration.json; remeasure its queue-hybrid executable on the same CPU/ELFs')
    p.add_argument('--max-mean-error', type=float, default=0.001, help='mean absolute relative RTL error budget (default 0.1%%)')
    p.add_argument('--max-error', type=float, default=0.005, help='worst absolute relative RTL error budget (default 0.5%%)')
    p.add_argument('--repeats', type=int, default=3);p.add_argument('--warmups', type=int, default=1)
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--cpu', type=int, default=min(os.sched_getaffinity(0)))
    p.add_argument('--timeout', type=float, default=300)
    p.add_argument('--etiss-root', default=os.environ.get('ETISS_ROOT',''))
    p.add_argument('--isa-python', default=os.environ.get('PERFSIM_ISA_PYTHON',sys.executable))
    p.add_argument('--model-python', default=os.environ.get('PERFSIM_MODEL_PYTHON',sys.executable))
    p.add_argument('--root', type=Path, default=ROOT/'build/deps/perfsim-upstream')
    args = p.parse_args()
    if min(args.repeats,args.jobs)<1 or args.warmups<0 or args.timeout<=0 or args.cpu not in os.sched_getaffinity(0):
        p.error('positive repeats/jobs/timeout, nonnegative warmups and an allowed CPU required')
    if not args.etiss_root: p.error('ETISS_ROOT required')
    if not 0 <= args.max_mean_error <= args.max_error < 1:
        p.error('require 0 <= mean error budget <= worst error budget < 1')
    evidence = json.loads((args.accuracy/'accuracy.json').read_text())
    if evidence['status']!='passed' or not evidence['results'] or any(r['status']!='passed' for r in evidence['results']):
        raise ValueError('successful accuracy evidence required')
    rows = load_configurations([r['configuration']['path'] for r in evidence['configurations']],
                               evidence['memory']['imem_latency'],evidence['memory']['dmem_latency'],contract='map_dse')
    if any(r['config']!=old['configuration']['parameters'] or r['resolved']['functional']!=old['functional']
           for r,old in zip(rows,evidence['configurations'])):
        raise ValueError('hardware/functional configuration changed since RTL evidence')
    queue=None
    if args.queue_baseline:
        queue=json.loads(args.queue_baseline.read_text())
        if (queue['status']!='passed' or queue['configurations']!=[r['name'] for r in rows] or
                Path(queue['accuracy_run']).resolve()!=args.accuracy.resolve()):
            raise ValueError('queue baseline must use the same passed RTL/configuration matrix')
    workloads = list(dict.fromkeys(r['workload'] for r in evidence['results']))
    filters = args.workloads.split(',') if args.workloads else []
    if any(not any(w.endswith(f) for w in workloads) for f in filters):
        raise ValueError('unknown workload filter')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    folder = ROOT/'build/investigations/perfsim-map'/stamp;folder.mkdir(parents=True)
    print('MAPExplorer study:',folder,flush=True)
    kwargs = dict(etiss_root=Path(args.etiss_root).expanduser().resolve(),jobs=args.jobs,
                  cmake_args=shlex.split(os.environ.get('PERFSIM_CMAKE_ARGS','')))
    isa = Path(args.isa_python).expanduser().absolute();model=Path(args.model_python).expanduser().absolute()
    instruction, build = generate(rows,args.root.resolve(),isa,model,**kwargs)
    record = dict(schema_version=1,status='running',accuracy_run=str(args.accuracy.resolve()),
        instruction_build=str(instruction),configuration_count=len(rows),timing_models=len(build['models']),
        configurations=[r['name'] for r in rows],source_sha256=build['source_sha256'],tools=build['tools'],
        host=dict(cpu=args.cpu,kernel=platform.platform(),load=os.getloadavg()),
        repeats=args.repeats,warmups=args.warmups,results=[],started_at=datetime.now(timezone.utc).isoformat())
    record['error_budgets']=dict(mean_absolute_relative_error=args.max_mean_error,worst_absolute_relative_error=args.max_error)
    if queue:
        record['queue_baseline']=dict(path=str(args.queue_baseline.resolve()),sha256=digest(args.queue_baseline),
                                      contract='retained queue model; cycles validated against its own checked run')
    (folder/'compare_map.py').write_text(Path(__file__).read_text());report(folder,record)
    try:
        for workload in workloads:
            if filters and not any(workload.endswith(f) for f in filters): continue
            print('Workload:',workload,flush=True)
            pairs = [r for r in evidence['results'] if r['workload']==workload]
            if len(pairs)!=len(rows) or len({r['elf'] for r in pairs})!=1:
                raise ValueError('incomplete workload matrix')
            elf = Path(pairs[0]['elf']);previous=Path(pairs[0]['perfsim'])
            # The timing contract has changed. Do not require queue-model cycle
            # equality; compare this model's stream/cycles directly against RTL.
            generated, map_build, preparation = prepare_blocks(rows,instruction,build,elf,args.root.resolve(),isa,model,
                scheduler='map_explorer',limit=100000000,timeout=args.timeout,**kwargs)
            checked = execute(rows,generated,map_build,elf,100000000,args.timeout,True,timing_trace=False,scheduler='map_explorer',verify=True)
            expected = native_signature(json.loads((checked[0]/'native.json').read_text()),'iss')
            by_name={r['name']:path for r,path in zip(rows,checked)}
            comparisons=[];stream_cache={}
            for pair in pairs:
                c=compare_rtl(by_name[pair['configuration']],pair['rtl'],stream_cache)
                c.update(configuration=pair['configuration'],window_instructions=pair['window_instructions'])
                comparisons.append(c)
            simulation = json.loads((checked[0]/'report.json').read_text())
            native = json.loads((checked[0]/'native.json').read_text())
            if native['execution']['map_scheduled_instructions']!=native['functional_instructions']*len(build['models']):
                raise ValueError('MAPExplorer did not schedule every timing state/instruction')
            if native['execution']['fetch_model_evaluations']!=native['functional_instructions']*native['execution']['shared_fetch_models']:
                raise ValueError('trace resource sharing did not evaluate each model exactly once per instruction')
            if native['execution']['hazard_model_evaluations']!=native['functional_instructions']*native['execution']['shared_hazard_models']:
                raise ValueError('hazard resource sharing did not evaluate each model exactly once per instruction')
            if native['execution'].get('bpu_model_evaluations',0)!=native['functional_instructions']*native['execution'].get('active_bpu_models',0):
                raise ValueError('trace BPU sharing did not evaluate each active model once per instruction')
            row = dict(workload=workload,elf=str(elf),elf_sha256=digest(elf),map_build=str(generated),preparation=preparation,
                checked_runs=list(map(str,checked)),verified_functional_instructions=native['functional_instructions'],
                execution=native['execution'],rtl_comparisons=comparisons,samples={k:[] for k in ('instruction','map_explorer')},warmup_samples=[])
            queue_command=None;queue_expected=None
            if queue:
                old,=[r for r in queue['results'] if r['workload']==workload]
                if old['elf_sha256']!=row['elf_sha256']:
                    raise ValueError('queue baseline ELF changed')
                prior=Path(old['checked_runs'][0])
                queue_expected=native_signature(json.loads((prior/'native.json').read_text()),'iss')
                queue_command=list(json.loads((prior/'report.json').read_text())['command'])
                executable=Path(old['block_build'])/'native/uqu_perfsim'
                identity=json.loads((Path(old['block_build'])/'build.json').read_text())['native_executable_sha256']
                if digest(executable)!=identity: raise ValueError('retained queue executable changed')
                queue_command[0]=str(executable);queue_command[9]='0'
                row['queue_baseline']=dict(executable=str(executable),sha256=identity,checked_run=str(prior),expected=queue_expected)
                row['samples']['queue_hybrid']=[]
            record['results'].append(row);report(folder,record)
            command = list(simulation['command']);command[9]='0'
            image = load_elf(elf);benchmark=json.loads((elf.parent/'build.json').read_text())['benchmark']
            for repeat in range(args.warmups+args.repeats):
                modes = list(row['samples'])
                if repeat%2: modes.reverse()
                for mode in modes:
                    argv = list(queue_command if mode=='queue_hybrid' else command)
                    if mode!='queue_hybrid':argv[0]=str((generated if mode=='map_explorer' else instruction)/'native/uqu_perfsim')
                    argv = ['env','UQU_PERFSIM_SCHEDULER='+('block' if mode=='queue_hybrid' else mode),'UQU_PERFSIM_SHARING=0',
                            'UQU_PERFSIM_VERIFY=0','UQU_PERFSIM_PROFILE=0',*argv]
                    directory = folder/('workload-'+str(len(record['results'])-1))/(mode+'-'+str(repeat))
                    sample = measure(argv,directory,args.cpu,args.timeout)
                    validate(directory,'iss',image,benchmark,queue_expected if mode=='queue_hybrid' else expected)
                    sample['warmup']=repeat<args.warmups
                    (row['warmup_samples'] if sample['warmup'] else row['samples'][mode]).append(sample)
            row['summary']={k:summarize(v) for k,v in row['samples'].items()};report(folder,record)
        report(folder,record)
        if (record['accuracy']['mean_absolute_relative_error']>args.max_mean_error or
                record['accuracy']['worst_absolute_relative_error']>args.max_error):
            raise ValueError('RTL timing error exceeds recorded DSE acceptance budgets')
        record['status']='passed'
    except BaseException as error:
        record.update(status='failed',detail=str(error));raise
    finally:
        record['finished_at']=datetime.now(timezone.utc).isoformat();report(folder,record)
    print(folder/'comparison.md',flush=True)


if __name__ == '__main__': main()
