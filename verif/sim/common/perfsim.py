#!/usr/bin/env python3
"""Make helper for pinned ETISS/CorePerfDSL generation and native execution."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[3]
PERF = ROOT/'verif/perfsim'
sys.path.insert(0, str(PERF))
from dependencies import check_sources, digest, fetch, load_lock
from model import MODEL_VERSION, fingerprint, render, render_external_bindings
from config_frontend import load_configurations, write_configuration
from block_schedule import generate_blocks, load_profile
from map_explorer import load_profile as load_map_profile
from elf_image import expected_traps, load_elf
from interrupts import interrupt_plan
from benchmark_fast import read_memory, write_memory
from benchmark_measure import benchmark_result, marker_addresses, read_log, software_compatible
from memory import load as load_memory


def command(argv, log, *, cwd=ROOT, env=None, timeout=None):
    with Path(log).open('a') as out:
        out.write('$ '+shlex.join(map(str, argv))+'\n');out.flush()
        subprocess.run(list(map(str, argv)), cwd=cwd, env=env, timeout=timeout,
                       stdout=out, stderr=subprocess.STDOUT, check=True)


def configurations(names, imem, dmem, contract="queue",memory=None):
    return load_configurations(names, imem, dmem, contract=contract,memory=memory)


def tool_env(source):
    env=dict(os.environ)
    env['PYTHONPATH']=str(source)+os.pathsep+env.get('PYTHONPATH','')
    return env


def python_identity(python):
    script = ('import sys,json,importlib.metadata as m; '
              'print(json.dumps(dict(executable=sys.executable,version=sys.version,'
              'packages={d.metadata["Name"]:d.version for d in m.distributions()})))')
    return json.loads(subprocess.check_output([str(python), '-c', script], text=True))


def operand_masks(schema):
    """Architectural operands come from trace mappings, not timing paths.

    Fine forwarding removes register-connector edges from CorePerfDSL. Those
    changes must not disable RV32E encoding checks or change functional usage.
    """
    bits={'rs1':1,'rs2':2,'rd':4}
    return {str(i['id']):sum(bits[m['traceValue']] for m in i['mappings']
                            if m['traceValue'] in bits and str(m['description'])!='0')
            for i in schema['trace']['instructions']}


def generate(rows, root, isa_python, model_python, *, etiss_root=None, jobs=2, cmake_args=(), block_profile=None, scheduler="block"):
    lock=load_lock(ROOT/'config/perfsim/upstream.lock.json');check_sources(lock,root)
    descriptions={row['model']['id']:row['model'] for row in rows}
    map_contract=all(d['schedule'].get('contract')=='map_dse' for d in descriptions.values())
    profile_loader=load_map_profile if map_contract else load_profile
    files=[*PERF.rglob('*.py'),*PERF.rglob('*.h'),*PERF.rglob('*.cpp'),
           *PERF.rglob('*.patch'),PERF/'models/uqu.corePerfDsl.in',PERF/'native/CMakeLists.txt',
           PERF/'native/uqu_map.cpp.in',PERF/'native/uqu_map_extract.cpp.in',Path(__file__),ROOT/'config/perfsim/upstream.lock.json',
           ROOT/'config/selectors.json', ROOT/'verif/sim/common/hw_config.py']
    files=[p for p in files if 'tests' not in p.relative_to(ROOT).parts and
           p.name not in ('test_frontend.py','compare.py')]
    sources={str(p.relative_to(ROOT)):digest(p) for p in files}
    library=Path(etiss_root)/'lib/libETISS.so' if etiss_root else None
    if library and not library.is_file():raise ValueError('ETISS_ROOT needs an installed lib/libETISS.so')
    binaries = ({str(p.relative_to(etiss_root)): digest(p) for p in Path(etiss_root).rglob('*.so')}
                if etiss_root else {})
    upstream_files = {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob('*'))
                      if p.is_file() and not {'.git', '__pycache__'}.intersection(p.parts)}
    tools = dict(isa_python=python_identity(isa_python), model_python=python_identity(model_python))
    key=fingerprint(dict(models=list(descriptions.values()),sources=sources,
                         etiss_root=str(etiss_root),etiss_binaries=binaries, upstream_tree=fingerprint(upstream_files),
                         cmake_args=list(cmake_args),tools=tools,
                         block_profile=profile_loader(block_profile) if block_profile else None,
                         scheduler=scheduler if block_profile else 'instruction'))
    target=ROOT/'build/perfsim-models'/key
    if (target/'build.json').exists():
        record=json.loads((target/'build.json').read_text())
        if record['status']=='passed' and (not etiss_root or (target/'native/uqu_perfsim').is_file()):
            if etiss_root and digest(target/'native/uqu_perfsim') != record.get('native_executable_sha256'):
                raise ValueError('cached native executable changed: '+str(target))
            return target,record
    target.mkdir(parents=True,exist_ok=True)
    print('Model build artifacts:',target,flush=True)
    (target/'upstream-files.json').write_text(json.dumps(upstream_files,indent=2)+'\n')
    log=target/'build.log';started=time.monotonic()
    generator=target/'generator'
    shutil.copytree(root/'code_gen/generators/M2-ISA-R-Perf',generator,dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__'))
    command(['patch','-p1','-i',PERF/'patches/m2isar-perf-branch-identity.patch'],log,cwd=generator)
    schema=None; model_dirs=[]
    for ident,description in descriptions.items():
        folder=target/ident;folder.mkdir(exist_ok=True)
        dsl=folder/'uqu.corePerfDsl';dsl.write_text(render(description))
        (folder/'model.json').write_text(json.dumps(description,indent=2)+'\n')
        command([model_python,generator/'m2isar_perf/run.py',dsl,'-c','-m','-o',folder/'generated'],log)
        command([model_python,PERF/'schedule_ir.py',generator,dsl,folder/'schedule-ir.json'],log)
        trace=folder/'generated/UQU/UQU_trace.json'
        raw=json.loads(trace.read_text())
        if map_contract:
            # Assign only fields absent from the authoritative DSL mapping.
            # This avoids monitor garbage becoming synthetic dependencies.
            for instruction in raw['trace']['instructions']:
                used={m['traceValue'] for m in instruction['mappings']}
                instruction['mappings'].extend(dict(traceValue=k,description='0')
                    for k in ('rs1','rs2','rd','brTarget') if k not in used)
        if schema is not None and raw!=schema:raise ValueError('generated trace schemas differ; cannot share functional execution')
        schema=raw
        model_dirs.append(folder/'generated/UQU/code/perf_estimator'/description['name'])
    isa_source=target/'isa-generator'
    shutil.copytree(root/'code_gen/generators/M2-ISA-R',isa_source,dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__'))
    command(['patch','-p1','-i',PERF/'patches/m2isar-trace-numeric-code.patch'],log,cwd=isa_source)
    isa_model=target/'isa'
    shutil.copytree(root/'code_gen/descriptions/core_dsl/etiss_arch_riscv',isa_model,
                    dirs_exist_ok=True,ignore=shutil.ignore_patterns('gen_model','__pycache__'))
    env=tool_env(isa_source)
    command([isa_python,'-m','m2isar.frontends.coredsl2.parser',isa_model/'top.core_desc'],log,env=env)
    trace_file=target/'trace.json';trace_file.write_text(json.dumps(schema,indent=2)+'\n')
    command([isa_python,'-m','m2isar.backends.trace_gen.trace_gen',trace_file,
             isa_model/'gen_model/top.m2isarmodel','-o',target/'channel'],log,env=env)
    # Add a functional pre-instruction guard after generated identity capture.
    # The hook is inactive for ordinary unprotected RV32I/M/C arithmetic.
    monitor_source=target/'channel/code/UQU/monitor/src/UQU_InstructionMonitors.cpp'
    content=monitor_source.read_text()
    needle='ret_strs << "*UQU_Monitor_instrCnt += 1;\\n";'
    hook='\n    ret_strs << "if (uqu_arch_guard || " << ((ba.to_ulong() & 127)==115) << ") { if (uqu_before_instruction(cpu)) return 0; }\\n";'
    if needle not in content:raise ValueError('unsupported generated monitor hook layout')
    monitor_source.write_text(content.replace(needle,needle+hook))
    channel=target/'channel/code/UQU'
    src=[*channel.glob('channel/src/*.cpp'),*channel.glob('monitor/src/*.cpp')]
    includes=[channel/'channel/include',channel/'monitor/include']
    registry=['#include "registry.h"']
    c=rows[0]['config']
    registry.append('uqu::Architecture architectural_configuration(){uqu::Architecture a;'+
        ''.join('a.'+field+'='+str(int(c[key]))+';' for field,key in [('embedded','ISA_E'),('multiply','ISA_M'),('compressed','ISA_C'),('user','ISA_UMODE'),('pmp','ISA_PMP'),('hart','HART_ID')])+'return a;}')

    for description,folder in zip(descriptions.values(),model_dirs):
        name=description['name'];registry.append(f'#include "{name}_PerformanceModel.h"')
        src.extend(folder.glob('src/*.cpp'));includes.append(folder/'include')
    if block_profile and scheduler=='block':
        block_sources, model_groups=generate_blocks(target,list(descriptions.values()),model_dirs,block_profile)
        src.extend(block_sources)
    else:
        model_groups={d['id']:0 for d in descriptions.values()}
        src.append(PERF/'native/uqu_blocks_empty.cpp')
    map_includes=[]
    if map_contract:
        command([model_python,PERF/'map_explorer.py',target],log)
        src.append(target/'map/extractor.cpp')
        backend=root/'etiss-perf-sim/etiss_plugins/SoftwareEvalLib/libs/backends'
        src.append(backend/'src/internal/BlockExtractor.cpp')
        map_includes=[backend/'libs/MAPModels/include']
    else:
        src.append(PERF/'native/uqu_map_extract_empty.cpp')
    if block_profile and scheduler=='map_explorer':
        if not map_contract:raise ValueError('MAPExplorer requires the map_dse model contract')
        command(['patch','-p1','-i',PERF/'patches/m2isar-perf-map-mapping.patch'],log,cwd=generator)
        command(['patch','-p1','-i',PERF/'patches/m2isar-perf-map-algebra.patch'],log,cwd=generator)
        bindings=target/'map-descriptions.json'
        bindings.write_text(json.dumps(list(descriptions.values()),indent=2)+'\n')
        command([model_python,PERF/'map_explorer.py',target,'--generator',generator,
                 '--descriptions',bindings,'--profile',block_profile],log)
        map_record=json.loads((target/'map/generation.json').read_text())
        src.extend(map(Path,map_record['sources']))
        patched=target/'map-upstream'
        shutil.copytree(backend/'include',patched/'include',dirs_exist_ok=True)
        command(['patch','-p1','-i',PERF/'patches/map-explorer-runtime.patch'],log,cwd=patched)
        map_includes.insert(0,patched/'include/internal')
    else:
        src.append(PERF/'native/uqu_map_empty.cpp')
    for d in descriptions.values():
        name=d['name']
        registry.append(f'static TimingView view_{name}(PerformanceModel& base) {{ auto& m=static_cast<{name}::{name}_PerformanceModel&>(base); '
                        'return {m,{&m.IF_stage,&m.DE_stage,&m.EX_stage,&m.MEM_stage,&m.WB_stage},'
                        'm.entrancePoint,m.regModel,m.serialModel,m.frontendModel}; }')
    registry.append('std::vector<ModelInstance> make_models(bool reference) { std::vector<ModelInstance> result;')
    for d in descriptions.values():
        name=d['name']
        registry.append(f'{{ auto m=std::make_unique<{name}::{name}_PerformanceModel>(); '
                        +render_external_bindings(d)+
                        f'ModelInstance entry;entry.id="{d["id"]}";entry.model=std::move(m);'
                        f'entry.view=view_{name};entry.block_group={model_groups[d["id"]]};'
                        f'if(reference) {{ auto m=std::make_unique<{name}::{name}_PerformanceModel>();'
                        +render_external_bindings(d)+
                        'entry.reference=std::move(m); } result.push_back(std::move(entry)); }')
    registry.append('return result; }')
    ids=[x['id'] for x in schema['trace']['instructions'] if x['name'].lower()!='_def']
    registry.append('bool supported_type(uint64_t id) { switch(id) {'+''.join(f'case {i}: ' for i in ids)+'return true; default: return false; }}')
    event_ids={i['name'].lower():i['id'] for i in schema['trace']['instructions']}
    registry.append('unsigned event_type(unsigned event){switch(event){'+
        ''.join('case '+str(n)+':return '+str(event_ids.get(name,event_ids['_def']))+';' for n,name in [(1,'ecall'),(2,'ebreak'),(3,'wfi'),(4,'mret'),(6,'cnop')])+
        'default:throw std::runtime_error("invalid architectural event");}}')
    masks=operand_masks(schema)
    registry.append('unsigned operand_mask(uint64_t id) {switch(id) {'+
                    ''.join(f'case {i}:return {mask};' for i,mask in masks.items())+'default:return 0;}}')
    (target/'operand-masks.json').write_text(json.dumps(masks,sort_keys=True)+'\n')
    (target/'registry.cpp').write_text('\n'.join(registry)+'\n')
    def cmake_list(name,values):return 'set('+name+'\n'+''.join('  "'+str(v).replace('\\','/')+'"\n' for v in values)+')\n'
    (target/'models.cmake').write_text(cmake_list('MODEL_SOURCES',src)+cmake_list('MODEL_INCLUDES',includes)+cmake_list('MODEL_MAP_INCLUDES',map_includes))
    if etiss_root:
        command(['cmake','-S',PERF/'native','-B',target/'native','-DCMAKE_BUILD_TYPE=Release',
                 '-DETISS_ROOT='+str(etiss_root),'-DPERFSIM_ROOT='+str(root),
                 '-DGENERATED_DIR='+str(target),*cmake_args],log)
        command(['cmake','--build',target/'native','--parallel',str(jobs)],log)
    record=dict(status='passed',models=list(descriptions.values()),source_sha256=sources,
                generation_build_seconds=time.monotonic()-started,
                block_profile_sha256=digest(block_profile) if block_profile else None,
                scheduler=scheduler if block_profile else 'instruction',
                upstream_lock_sha256=digest(ROOT/'config/perfsim/upstream.lock.json'),
                etiss_library_sha256=digest(library) if library else None,
                etiss_binaries_sha256=binaries,upstream_tree_sha256=fingerprint(upstream_files),tools=tools)
    if etiss_root:
        record['native_executable_sha256']=digest(target/'native/uqu_perfsim')
        record['tools']['cmake']=subprocess.check_output(['cmake','--version'],text=True).splitlines()[0]
        cache=(target/'native/CMakeCache.txt').read_text()
        compiler=re.search(r'^CMAKE_CXX_COMPILER:FILEPATH=(.+)$',cache,re.M)
        if compiler:
            record['tools']['cxx']=subprocess.check_output([compiler[1],'--version'],text=True).splitlines()[0]
    (target/'build.json').write_text(json.dumps(record,indent=2)+'\n')
    return target,record


def validate_benchmark(text, benchmark):
    pattern=r'^Total ticks\s+: ([0-9]+)$' if benchmark['validator']=='coremark' else r'^Cycles: ([0-9]+)$'
    match=re.search(pattern,text,re.M)
    if not match:raise ValueError('benchmark output lacks its functional ISS timer value')
    ticks=int(match[1])
    result=benchmark_result(text,benchmark,ticks)
    result['iss_timer_ticks_per_iteration']=result.pop('cycles_per_iteration')
    return dict(result,iss_timer_ticks=ticks,
                timer_scope='functional ISS counter; never substituted for estimated cycles')


def prepare_blocks(rows, instruction_dir, instruction_build, program, root, isa_python, model_python,
                   *, etiss_root, jobs=2, cmake_args=(), limit=100000000, timeout=300, scheduler="block"):
    """Extract once per immutable ELF/schema, then compile reusable block kernels."""
    started=time.monotonic()
    map_contract=rows[0]['model']['schedule'].get('contract')=='map_dse'
    profile_loader=load_map_profile if map_contract else load_profile
    identity=dict(elf_sha256=digest(program),functional_id=rows[0]['resolved']['functional_id'],
                  schema_sha256=digest(instruction_dir/'trace.json'),
                  operand_masks_sha256=digest(instruction_dir/'operand-masks.json'),
                  extractor_sha256=fingerprint({str(p):digest(p) for p in (PERF/'native/driver.cpp',PERF/'native/uqu_map_extract.cpp.in')}),
                  block_format=2 if map_contract else 1)
    folder=ROOT/'build/perfsim-profiles'/fingerprint(identity)
    profile=folder/'blocks.json';manifest=folder/'profile.json'
    hit=False
    if profile.is_file() and manifest.is_file():
        saved=json.loads(manifest.read_text())
        if saved.get('identity')!=identity or saved.get('sha256')!=digest(profile):
            raise ValueError('block profile cache changed: '+str(folder))
        profile_loader(profile);hit=True
    else:
        runs=execute(rows,instruction_dir,instruction_build,program,limit,timeout,False,profile=True)
        source=runs[0]/'blocks.json'
        if map_contract:
            data=json.loads(source.read_text());data['schema_version']=2
            source.write_text(json.dumps(data,indent=2)+'\n')
        data=profile_loader(source)
        data['identity']=identity
        folder.mkdir(parents=True,exist_ok=True)
        profile.write_text(json.dumps(data,indent=2)+'\n')
        manifest.write_text(json.dumps(dict(identity=identity,sha256=digest(profile),
            extraction_run=str(runs[0]),extraction_seconds=time.monotonic()-started),indent=2)+'\n')
    target,record=generate(rows,root,isa_python,model_python,etiss_root=etiss_root,jobs=jobs,
                           cmake_args=cmake_args,block_profile=profile,scheduler=scheduler)
    return target,record,dict(profile=str(profile),profile_cache_hit=hit,
        extraction_functional_runs=0 if hit else 1,preparation_seconds=time.monotonic()-started,
        generation=json.loads((target/('map' if scheduler=='map_explorer' else 'blocks')/'generation.json').read_text()))


def execute(rows, model_dir, build_record, program, limit, timeout, trace, timing_trace=True,
            scheduler='instruction', share_models=False, verify=False, profile=False):
    if scheduler=='map_explorer':share_models=True
    if scheduler=='block' and rows[0]['model']['schedule'].get('contract')=='map_dse':
        raise ValueError('project block adapter only supports the queue timing contract')
    if scheduler not in ('instruction','block','map_explorer'):
        raise ValueError('unknown scheduling backend')
    if scheduler in ('block','map_explorer') and not build_record.get('block_profile_sha256'):
        raise ValueError('block scheduler needs generated kernels')
    if scheduler in ('block','map_explorer'):
        if build_record.get('scheduler')!=scheduler:
            raise ValueError('generated scheduling backend does not match requested backend')
        block_data=(load_map_profile if scheduler=='map_explorer' else load_profile)(
            model_dir/('map' if scheduler=='map_explorer' else 'blocks')/'profile.json')
        if block_data.get('identity',{}).get('elf_sha256')!=digest(program):
            raise ValueError('generated block profile belongs to a different ELF')
        if block_data['identity'].get('functional_id')!=rows[0]['resolved']['functional_id']:
            raise ValueError('generated block profile belongs to a different functional configuration')
    image=load_elf(program)
    for row in rows:image.validate_core(row['config'])
    traps=expected_traps(image)
    if traps and any(r['config']['MUA_BRANCH_PREDICTOR']!='none' or r['config']['MUA_BTB']!='none' for r in rows):
        raise ValueError('synchronous trap timing initially requires prediction disabled')
    if traps and rows[0]['model']['schedule'].get('contract')!='map_dse':
        raise ValueError('synchronous trap timing requires map_dse')
    if interrupt_plan(image,rows[0]['config']):
        raise ValueError('asynchronous interrupt injection is not modeled yet')
    if any(s.flags&3==3 for s in image.segments):raise ValueError('initial perfsim requires separate executable and writable segments')
    start,stop=marker_addresses(image) if 'uqu_bench_start' in image.symbols or 'uqu_bench_stop' in image.symbols else (0,0)
    software_path=program.parent/'build.json'
    software=json.loads(software_path.read_text()) if software_path.is_file() else None
    benchmark=software.get('benchmark') if software else None
    if benchmark and (software.get('status')!='passed' or software.get('elf_sha256')!=digest(program) or
                      any(not software_compatible(software['parameters'],r['config']) for r in rows)):
        raise ValueError('benchmark ELF/build metadata do not match selected software/ISA inputs')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    directories=[ROOT/'build'/('uquintus-'+row['name'])/'perfsim'/('run-'+stamp) for row in rows]
    shared=directories[0];shared.mkdir(parents=True,exist_ok=True)
    write_memory(image,shared/'program-image.bin')
    records=[]
    for row,directory in zip(rows,directories):
        directory.mkdir(parents=True,exist_ok=True)
        record=dict(schema_version=1,kind='perfsim',status='running',configuration_scope='core',
                    configuration=dict(name=row['name'],parameters=row['config']),component='uqu_core',
                    target='etiss_coreperfdsl',selection=scheduler+'_scheduling',
                    workload=digest(program),started_at=datetime.now(timezone.utc).isoformat(),
                    context=dict(model_version=row['model']['schedule']['version'],model_status='uncalibrated',
                        approximations=row['model']['approximations'],
                        model_batch=sorted({r['model']['id'] for r in rows}),
                        memory=dict(imem_response_cycles=row['model']['schedule']['imem_latency'],
                                    dmem_response_cycles=row['model']['schedule']['dmem_latency']),
                        measurement='(start, stop] modeled WB completion' if start else 'whole execution including fill/drain',
                        functional_runs=1,backend=({'block':'feedback-barrier max-plus blocks','map_explorer':'upstream MAPExplorer composed blocks with shared trace models'}.get(scheduler,'generated instruction schedules')),
                        block_scheduling=scheduler in ('block','map_explorer'), upstream_map_explorer=scheduler=='map_explorer', shared_component_evaluation=share_models,
                        verify_scheduling=verify, block_extraction=profile),metrics=[],source_sha256=build_record['source_sha256'],
                    model_build=str(model_dir),shared_execution=str(shared),
                    upstream_lock_sha256=build_record['upstream_lock_sha256'],
                    etiss_library_sha256=build_record['etiss_library_sha256'],
                    etiss_binaries_sha256=build_record['etiss_binaries_sha256'],
                    upstream_tree_sha256=build_record['upstream_tree_sha256'],
                    native_executable_sha256=build_record['native_executable_sha256'],
                    tools=build_record['tools'],
                    model=row['model'],configuration_label=row['resolved']['configuration']['label'],
                    functional_configuration=row['resolved']['functional'],
                    artifacts=['config.yml','model.json','native.json','native.log','workload.json',
                               'build.json','trace.csv','traps.csv','benchmark.log','final-memory.bin','rtl-comparison.json',
                               'resolved.json','uqu.corePerfDsl','external_models.inc'])
        write_configuration(row,directory)
        if row['model']['schedule'].get('contract')=='map_dse':record['context']['memory_environment']=row['model']['memory_environment']
        (directory/'model.json').write_text(json.dumps(row['model'],indent=2)+'\n')
        (directory/'build.json').write_text(json.dumps(build_record,indent=2)+'\n')
        (directory/'workload.json').write_text(json.dumps(dict(elf=str(program),sha256=digest(program),
            entry=image.entry,tohost=image.tohost,start=start,stop=stop,benchmark=benchmark),indent=2)+'\n')
        (directory/'report.json').write_text(json.dumps(record,indent=2)+'\n');records.append(record)
        print('Artifacts:',directory,flush=True)
    isa=rows[0]['resolved']['functional']['etiss']
    args=[model_dir/'native/uqu_perfsim',shared/'program-image.bin',hex(image.entry),hex(image.tohost),
          hex(start),hex(stop),str(limit),hex(isa['misa']),str(isa['hart_id']),str(int(trace) | (2 if trace and timing_trace else 0)),
          *(f'{s.address}:{s.address+s.size}' for s in image.segments if s.flags&1)]
    started=time.monotonic()
    for record in records:record['command']=list(map(str,args))
    import struct
    (shared/'expected-traps.bin').write_bytes(b'UQUTRP01'+struct.pack('<I',len(traps))+b''.join(struct.pack('<III',*t) for t in traps))
    environment=dict(os.environ,UQU_PERFSIM_SCHEDULER=scheduler,
                     UQU_PERFSIM_SHARING=str(int(share_models)),UQU_PERFSIM_VERIFY=str(int(verify)),
                     UQU_PERFSIM_PROFILE=str(int(profile)))
    environment['UQU_PERFSIM_TRAPS']=str(shared/'expected-traps.bin')
    for record in records:
        record['execution_environment']={k:v for k,v in environment.items() if k.startswith('UQU_PERFSIM_')}
    try:
        command(args,shared/'native.log',cwd=shared,env=environment,timeout=timeout)
        native=json.loads((shared/'native.json').read_text())
        if native.get('status')!='passed':raise ValueError('native perfsim did not pass')
        observed={m['id']:m for m in native['models']}
        if len(observed)!=len(native['models']) or set(observed)!={r['model']['id'] for r in rows}:
            raise ValueError('native results do not cover the requested timing models')
        validation=None
        if benchmark:
            text=read_log(image,read_memory(shared/'final-memory.bin'))
            (shared/'benchmark.log').write_text(text)
            validation=validate_benchmark(text,benchmark)
        elapsed=time.monotonic()-started
        for row,record in zip(rows,records):
            m=observed[row['model']['id']]
            if type(m['cycles']) is not int or m['cycles']<=0 or type(m['instructions']) is not int or m['instructions']<=0:
                raise ValueError('invalid estimated duration')
            record['context']['execution']=native.get('execution',{})
            record.update(status='passed',detail='Functional completion passed; generated timing estimates are uncalibrated.',
                          validation=validation,simulation_wall_seconds=elapsed,
                          model_generation_build_seconds=build_record['generation_build_seconds'],metrics=[
                dict(name='estimated_cycles',value=m['cycles'],unit='cycles'),
                dict(name='instructions',value=m['instructions'],unit='instructions'),
                dict(name='estimated_cpi',value=m['cycles']/m['instructions'],unit='cycles/instruction'),
                dict(name='simulation_wall_seconds',value=elapsed,unit='s'),
                dict(name='functional_mips',value=native['functional_instructions']/elapsed/1e6,unit='MIPS')])
            print(f'ESTIMATE (uncalibrated): {row["name"]}: {m["cycles"]} cycles, '
                  f'{m["instructions"]} instructions, CPI {m["cycles"]/m["instructions"]:.4f}',flush=True)
    except BaseException as error:
        for record in records:record.update(status='failed',detail=str(error))
        raise
    finally:
        for directory,record in zip(directories,records):
            if directory!=shared:
                for name in ('native.json','native.log'):
                    if (shared/name).is_file():shutil.copyfile(shared/name,directory/name)
            record['finished_at']=datetime.now(timezone.utc).isoformat()
            (directory/'report.json').write_text(json.dumps(record,indent=2)+'\n')
    return directories


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('fetch','config','model','run'))
    parser.add_argument('--config',default='rv32i')
    parser.add_argument('--configs',default='',help='comma-separated additional complete hardware YAMLs')
    parser.add_argument('--elf',default='')
    parser.add_argument('--root',default=os.environ.get('PERFSIM_ROOT',str(ROOT/'build/deps/perfsim-upstream')))
    parser.add_argument('--archives',default=str(ROOT/'build/deps/perfsim-archives'))
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--isa-python',default=os.environ.get('PERFSIM_ISA_PYTHON',sys.executable))
    parser.add_argument('--model-python',default=os.environ.get('PERFSIM_MODEL_PYTHON',sys.executable))
    parser.add_argument('--etiss-root',default=os.environ.get('ETISS_ROOT',''))
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--imem-latency',type=int,default=1)
    parser.add_argument('--dmem-latency',type=int,default=1)
    parser.add_argument('--memory',type=Path,help='external OBI/cache timing environment YAML')
    parser.add_argument('--max-instructions',type=int,default=100000000)
    parser.add_argument('--timeout',type=float,default=300)
    parser.add_argument('--trace',action='store_true')
    parser.add_argument('--instruction-trace',action='store_true',help='PC/encoding stream without per-model stage timestamp CSVs')
    parser.add_argument('--model-contract',choices=('queue','map_dse'),default=None)
    parser.add_argument('--scheduler',choices=('instruction','block','map_explorer'),default='map_explorer')
    parser.add_argument('--share-models',action='store_true',help='enable legacy queue transition caching; MAP-DSE always shares trace models')
    parser.add_argument('--verify-scheduling',action='store_true',help='compare instruction-reference state at instruction/block boundaries')
    args=parser.parse_args()
    root=Path(args.root).expanduser().resolve()
    if args.action=='fetch':return fetch(load_lock(ROOT/'config/perfsim/upstream.lock.json'),root,Path(args.archives),args.offline)
    if args.jobs<1 or args.max_instructions<1 or args.timeout<=0:raise ValueError('positive jobs, instruction limit and timeout required')
    contract=args.model_contract or ('map_dse' if args.scheduler=='map_explorer' else 'queue')
    if args.scheduler=='map_explorer' and contract!='map_dse':
        raise ValueError('MAPExplorer requires the map_dse timing contract')
    rows=configurations([args.config]+[x for x in args.configs.split(',') if x],args.imem_latency,args.dmem_latency,
                        contract=contract,memory=load_memory(args.memory) if args.memory else None)
    if args.action=='config':
        for row in rows:
            directory=write_configuration(row,ROOT/'build'/('uquintus-'+row['name'])/'perfsim/config')
            plan=row['resolved']
            print(f'{row["name"]}: {plan["functional"]["isa"]}; model {row["model"]["id"]}; uncalibrated')
            print('External models:',json.dumps(plan['external_models'],sort_keys=True))
            print('Resolved configuration:',directory/'resolved.json')
        return
    if args.action=='run' and (not args.elf or not args.etiss_root):raise ValueError('perfsim run requires ELF and ETISS_ROOT')
    target,record=generate(rows,root,Path(args.isa_python).expanduser().absolute(),
                           Path(args.model_python).expanduser().absolute(),
                           etiss_root=Path(args.etiss_root).expanduser().resolve() if args.etiss_root else None,
                           jobs=args.jobs,cmake_args=shlex.split(os.environ.get('PERFSIM_CMAKE_ARGS','')))
    print('Generated model:',target,flush=True)
    preparation=None
    if args.scheduler in ('block','map_explorer') and (args.elf or args.action=='run'):
        if not args.elf or not args.etiss_root:
            raise ValueError('block generation requires ELF and ETISS_ROOT for checked extraction')
        target,record,preparation=prepare_blocks(rows,target,record,Path(args.elf).resolve(),root,
            Path(args.isa_python).expanduser().absolute(),Path(args.model_python).expanduser().absolute(),
            etiss_root=Path(args.etiss_root).expanduser().resolve(),jobs=args.jobs,
            cmake_args=shlex.split(os.environ.get('PERFSIM_CMAKE_ARGS','')),
            limit=args.max_instructions,timeout=args.timeout,scheduler=args.scheduler)
        print('Generated blocks:',target,flush=True)
    if args.action=='run':
        runs=execute(rows,target,record,Path(args.elf).resolve(),args.max_instructions,args.timeout,
            args.trace or args.instruction_trace,timing_trace=args.trace,scheduler=args.scheduler,
            share_models=args.share_models,verify=args.verify_scheduling)
        if preparation:
            for directory in runs:
                path=directory/'report.json';result=json.loads(path.read_text())
                result['block_preparation']=preparation
                path.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,yaml.YAMLError,subprocess.SubprocessError) as error:
        print('perfsim:',error,file=sys.stderr);sys.exit(1)
