#!/usr/bin/env python3
"""Check block/shared backends against retained RTL-calibrated estimates and time them."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shlex
import statistics
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'verif/sim/common'))
from perfsim import generate, execute, prepare_blocks
from config_frontend import load_configurations
from dependencies import digest
from benchmark_cost import measure, native_signature, summarize, validate
from elf_image import load_elf


def report(directory, record):
    (directory/'acceleration.json').write_text(json.dumps(record,indent=2)+'\n')
    lines=['# Scheduling acceleration', '',
           'Whole-process host time, fixed CPU, fresh ETISS JIT, traces/reference checking off during timing. '
           'Block extraction and compilation are reported separately. Models remain uncalibrated.', '',
           '| Workload | Retained instruction (s) | Instruction (s) | Shared instruction (s) | Block (s) | Shared block (s) | Block vs retained | Shared callback hits |',
           '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in record['results']:
        if 'summary' not in r:continue
        s=r['summary'];base=s.get('retained_instruction',s['instruction'])['median_seconds']
        block=s['block']['median_seconds'];shared=s['block_shared']['median_seconds']
        e=r['execution']['block_shared']
        old=f'{base:.4f}' if 'retained_instruction' in s else '—'
        lines.append(f'| {r["workload"]} | {old} | {s["instruction"]["median_seconds"]:.4f} | {s["instruction_shared"]["median_seconds"]:.4f} | '
                     f'{block:.4f} | {shared:.4f} | {base/block:.2f}× | '
                     f'{e["frontend_cache_hits"]:,}/{e["frontend_calls"]:,} |')
    (directory/'acceleration.md').write_text('\n'.join(lines)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--accuracy',type=Path,required=True)
    p.add_argument('--workloads',default='',help='comma-separated workload suffixes; empty selects all')
    p.add_argument('--configs',default='',help='comma-separated configuration names; empty selects all')
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--warmups',type=int,default=1)
    p.add_argument('--jobs',type=int,default=2)
    p.add_argument('--cpu',type=int,default=min(os.sched_getaffinity(0)))
    p.add_argument('--timeout',type=float,default=300)
    p.add_argument('--etiss-root',default=os.environ.get('ETISS_ROOT',''))
    p.add_argument('--isa-python',default=os.environ.get('PERFSIM_ISA_PYTHON',sys.executable))
    p.add_argument('--model-python',default=os.environ.get('PERFSIM_MODEL_PYTHON',sys.executable))
    p.add_argument('--root',type=Path,default=ROOT/'build/deps/perfsim-upstream')
    p.add_argument('--resume',type=Path,help='reuse checked builds/completed workloads after a host-study interruption')
    a=p.parse_args()
    if min(a.repeats,a.jobs)<1 or a.warmups<0 or a.timeout<=0 or a.cpu not in os.sched_getaffinity(0):
        p.error('positive repeats/jobs/timeout, nonnegative warmups and an allowed CPU required')
    if not a.etiss_root:p.error('ETISS_ROOT required')
    accuracy=json.loads((a.accuracy/'accuracy.json').read_text())
    if accuracy['status']!='passed' or any(r['status']!='passed' for r in accuracy['results']):
        raise ValueError('successful accuracy evidence required')
    selected=set(a.configs.split(',')) if a.configs else {c['configuration']['name'] for c in accuracy['configurations']}
    known={c['configuration']['name'] for c in accuracy['configurations']}
    if not selected<=known:raise ValueError('unknown accuracy configuration')
    old=[c for c in accuracy['configurations'] if c['configuration']['name'] in selected]
    rows=load_configurations([c['configuration']['path'] for c in old],
                             accuracy['memory']['imem_latency'],accuracy['memory']['dmem_latency'])
    if [r['resolved'] for r in rows]!=old:raise ValueError('model/configuration changed since accuracy sweep')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    output=a.resume.resolve() if a.resume else ROOT/'build/investigations/perfsim-acceleration'/stamp
    if not a.resume:output.mkdir(parents=True)
    print('Acceleration artifacts:',output,flush=True)
    kwargs=dict(etiss_root=Path(a.etiss_root).resolve(),jobs=a.jobs,
                cmake_args=shlex.split(os.environ.get('PERFSIM_CMAKE_ARGS','')))
    isa=Path(a.isa_python).absolute();model=Path(a.model_python).absolute()
    if a.resume:
        record=json.loads((output/'acceleration.json').read_text())
        if (record['accuracy_run']!=str(a.accuracy.resolve()) or record['configurations']!=[r['name'] for r in rows]
                or record['repeats']!=a.repeats or record['warmups']!=a.warmups or record['host']['cpu']!=a.cpu):
            raise ValueError('resume requires the original accuracy/configurations/sampling/CPU')
        instruction_dir=Path(record['instruction_build'])
        instruction_build=json.loads((instruction_dir/'build.json').read_text())
        # The study driver can change without changing compiled schedules. All
        # generation/native inputs and installed ETISS binaries must still match.
        for name,expected in instruction_build['source_sha256'].items():
            if name not in ('verif/perfsim/accelerate.py','verif/perfsim/benchmark_cost.py','verif/perfsim/calibrate.py'):
                if digest(ROOT/name)!=expected:raise ValueError('compiled input changed: '+name)
        if digest(instruction_dir/'native/uqu_perfsim')!=instruction_build['native_executable_sha256']:
            raise ValueError('cached instruction executable changed')
        for name,expected in instruction_build['etiss_binaries_sha256'].items():
            if digest(Path(a.etiss_root)/name)!=expected:raise ValueError('ETISS binary changed: '+name)
        record.setdefault('resumes',[]).append(dict(at=datetime.now(timezone.utc).isoformat(),
            previous_status=record['status'],previous_detail=record.pop('detail',None)))
        record['status']='running'
    else:
        instruction_dir,instruction_build=generate(rows,a.root.resolve(),isa,model,**kwargs)
        record=dict(schema_version=1,status='running',accuracy_run=str(a.accuracy.resolve()),
        configurations=[r['name'] for r in rows],timing_models=len({r['model']['id'] for r in rows}),
        instruction_build=str(instruction_dir),source_sha256=instruction_build['source_sha256'],
        tools=instruction_build['tools'],host=dict(cpu=a.cpu,kernel=platform.platform(),load=os.getloadavg()),
        repeats=a.repeats,warmups=a.warmups,results=[],started_at=datetime.now(timezone.utc).isoformat())
    snapshot=output/('accelerate-'+stamp+'.py');snapshot.write_text(Path(__file__).read_text())
    record.setdefault('study_sources',[]).append(dict(path=snapshot.name,sha256=digest(snapshot)))
    report(output,record)
    try:
        workloads=list(dict.fromkeys(r['workload'] for r in accuracy['results']))
        filters=a.workloads.split(',') if a.workloads else []
        if filters and any(not any(w.endswith(f) for w in workloads) for f in filters):
            raise ValueError('unknown workload filter')
        for w in workloads:
            if filters and not any(w.endswith(f) for f in filters):continue
            previous_result=next((r for r in record['results'] if r['workload']==w),None)
            if previous_result and 'summary' in previous_result:continue
            print('Workload:',w,flush=True)
            pairs=[r for r in accuracy['results'] if r['workload']==w and r['configuration'] in selected]
            if len(pairs)!=len(rows) or len({r['elf'] for r in pairs})!=1:raise ValueError('incomplete workload matrix')
            elf=Path(pairs[0]['elf'])
            # Retained estimates are already checked against RTL instruction streams.
            previous=Path(pairs[0]['perfsim'])
            expected=native_signature(json.loads((previous/'native.json').read_text()),'iss')
            ids={r['model']['id'] for r in rows}
            expected['models']={k:v for k,v in expected['models'].items() if k in ids}
            if previous_result:
                block_dir=Path(previous_result['block_build'])
                block_build=json.loads((block_dir/'build.json').read_text())
                for name,expected_hash in block_build['source_sha256'].items():
                    if name not in ('verif/perfsim/accelerate.py','verif/perfsim/benchmark_cost.py','verif/perfsim/calibrate.py'):
                        if digest(ROOT/name)!=expected_hash:raise ValueError('block input changed: '+name)
                if digest(block_dir/'native/uqu_perfsim')!=block_build['native_executable_sha256']:
                    raise ValueError('cached block executable changed')
                preparation=previous_result['block_preparation']
                checked=list(map(Path,previous_result['checked_runs']))
            else:
                block_dir,block_build,preparation=prepare_blocks(rows,instruction_dir,instruction_build,elf,
                    a.root.resolve(),isa,model,timeout=a.timeout,**kwargs)
                checked=execute(rows,block_dir,block_build,elf,100000000,a.timeout,False,
                                scheduler='block',share_models=True,verify=True)
            actual=native_signature(json.loads((checked[0]/'native.json').read_text()),'iss')
            if actual!=expected:raise ValueError('block result differs from retained accuracy evidence')
            simulation=json.loads((checked[0]/'report.json').read_text())
            command=list(simulation['command']);command[9]='0'
            retained=json.loads((previous/'report.json').read_text())
            old_native=Path(retained['command'][0])
            old_ids={m['id'] for m in json.loads((previous/'native.json').read_text())['models']}
            keep_old=old_ids==ids
            if keep_old and (digest(old_native)!=retained['native_executable_sha256'] or
                    retained['etiss_binaries_sha256']!=instruction_build['etiss_binaries_sha256']):
                raise ValueError('retained executable or ETISS installation changed')
            image=load_elf(elf);benchmark=json.loads((elf.parent/'build.json').read_text())['benchmark']
            row=dict(workload=w,elf=str(elf),elf_sha256=digest(elf),block_build=str(block_dir),
                     block_preparation=preparation,checked_runs=list(map(str,checked)),
                     samples={k:[] for k in (('retained_instruction',) if keep_old else ())+('instruction','instruction_shared','block','block_shared')},
                     retained_executable=str(old_native) if keep_old else None,
                     retained_executable_sha256=digest(old_native) if keep_old else None,
                     execution={},warmup_samples=[])
            if previous_result:record['results'][record['results'].index(previous_result)]=row
            else:record['results'].append(row)
            attempt=uuid.uuid4().hex[:8]
            report(output,record)
            for repeat in range(a.warmups+a.repeats):
                modes=list(row['samples']);offset=repeat%len(modes);modes=modes[offset:]+modes[:offset]
                for mode in modes:
                    block=mode.startswith('block');shared=mode.endswith('shared')
                    argv=list(command);argv[0]=str((block_dir if block else instruction_dir)/'native/uqu_perfsim')
                    if mode=='retained_instruction':argv[0]=str(old_native)
                    argv=['env','UQU_PERFSIM_SCHEDULER='+('block' if block else 'instruction'),
                          'UQU_PERFSIM_SHARING='+str(int(shared)),'UQU_PERFSIM_VERIFY=0','UQU_PERFSIM_PROFILE=0',*argv]
                    directory=output/('workload-'+str(record['results'].index(row)))/attempt/(mode+'-'+str(repeat))
                    sample=measure(argv,directory,a.cpu,a.timeout)
                    validate(directory,'iss',image,benchmark,expected)
                    execution=json.loads((directory/'native.json').read_text()).get('execution',{})
                    if block and not execution['block_calls']:raise ValueError('block backend was not exercised')
                    row['execution'][mode]=execution
                    sample['warmup']=repeat<a.warmups
                    (row['warmup_samples'] if sample['warmup'] else row['samples'][mode]).append(sample)
            row['summary']={k:summarize(v) for k,v in row['samples'].items()}
            report(output,record)
        record['status']='passed'
    except BaseException as e:
        record.update(status='failed',detail=str(e));raise
    finally:
        record['finished_at']=datetime.now(timezone.utc).isoformat();report(output,record)
    print(output/'acceleration.md',flush=True)


if __name__=='__main__':main()
