#!/usr/bin/env python3
"""RTL reference runs for perfsim memory environments and declared sync traps.

This is a validation harness, not the benchmark publication flow. It accepts
the same complete core YAML and external timing YAML as the native simulator.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

import yaml

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'verif/sim/common'))
from benchmark_fast import write_memory
from component_runner import (HDL_LANGUAGE_ARGS,bender_include_dirs,bender_source_options,
                              command_output,load_component,order_control_files,simulator_build_key)
from elf_image import expected_traps,load_elf
from hw_config import load_configuration,parameters_for_component,write_header
from interrupts import interrupt_plan
from memory import cpp_configuration,load as load_memory,validate as validate_memory

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run(program,config_path,config,*,memory=None,imem=1,dmem=1,bender='bender',jobs=4,
        max_cycles=100000000,timeout=300,shared_build=None):
    image=load_elf(program);image.validate_core(config);image.tohost
    if interrupt_plan(image,config):raise ValueError('perfsim RTL reference excludes asynchronous interrupts')
    profile=validate_memory(memory) if memory is not None else load_memory(imem=imem,dmem=dmem)
    start=image.symbols.get('uqu_benchmark_start',0);stop=image.symbols.get('uqu_benchmark_stop',0)
    # Existing software uses timer markers with these public symbol names.
    if not start:
        from benchmark_measure import marker_addresses
        try:start,stop=marker_addresses(image)
        except ValueError:start=stop=0
    traps=expected_traps(image)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    directory=ROOT/'build'/('uquintus-'+Path(config_path).stem)/'verilator'/'perfsim-reference'/stamp
    directory.mkdir(parents=True)
    catalog=json.loads((ROOT/'config/selectors.json').read_text());write_header(catalog,directory/'include')
    (directory/'config.yml').write_text(yaml.safe_dump(config,sort_keys=False))
    (directory/'memory.yml').write_text(yaml.safe_dump(profile,sort_keys=False))
    shutil.copyfile(program,directory/'program.elf');write_memory(image,directory/'program-image.bin')
    (directory/'expected-traps.bin').write_bytes(b'UQUTRP01'+struct.pack('<I',len(traps))+b''.join(struct.pack('<III',*t) for t in traps))
    header=directory/'include/memory_environment.h'
    header.write_text('inline void configure_memory(uqu::MemoryPort* ports) {\n'+
        '\n'.join(cpp_configuration(profile[p],f'ports[{i}]') for i,p in enumerate(('imem','dmem')))+'\n}\n')
    component=dict(load_component('core_elf'),bender_target='rtl')
    component['bender_targets']=[*component.get('bender_targets',[]),'benchmark_stats']
    parameters=parameters_for_component(config,component['parameters'],catalog)
    options=bender_source_options(component,'verilator',parameters)
    tree=command_output([bender,'sources',*options])
    sources=[(ROOT/p.strip()).resolve() for p in command_output([bender,'script','flist',*options]).splitlines()
             if p.strip() and not p.lstrip().startswith('//')]
    sources=order_control_files([*sources,ROOT/'verif/perfsim/rtl/uqu_perfsim_tb.sv'])
    driver=ROOT/'verif/perfsim/rtl/main.cpp'
    includes=[directory/'include',ROOT/'verif/perfsim/models',*bender_include_dirs(json.loads(tree))]
    headers=sorted({p for d in includes for ext in ('*.h','*.vh','*.svh') for p in d.rglob(ext)})
    key=simulator_build_key([*sources,driver],headers,includes,parameters,'uqu_perfsim_tb',
                           command_output(['verilator','--version'])+command_output(['c++','--version']),False,directory/'include')
    record=dict(schema_version=1,kind='test',configuration_scope='core',component='core_elf',target='verilator',
                selection='perfsim-reference',configuration=dict(name=Path(config_path).stem,parameters=config),
                workload=sha(program),status='running',metrics=[],required_tests=['software_completion_and_declared_traps'],
                results_file='results.xml',started_at=datetime.now(timezone.utc).isoformat(),
                context=dict(memory_environment=profile,measurement='retirement edges (start, stop]'),
                source_sha256={str(p.relative_to(ROOT)):sha(p) for p in [*sources,driver,*[p for p in headers if p.is_relative_to(ROOT) and not p.is_relative_to(directory)],Path(__file__),ROOT/'verif/sim/common/elf_image.py']},
                artifacts=['native.json','native.log','retire.bin','traps.csv','config.yml','memory.yml','program.elf','program-image.bin','final-memory.bin'])
    output=directory/'report.json';output.write_text(json.dumps(record,indent=2)+'\n')
    tests=ET.Element('testsuites');case=ET.SubElement(ET.SubElement(tests,'testsuite',name='perfsim-reference'),'testcase',name=record['required_tests'][0])
    before=time.monotonic()
    print('RTL reference:',directory,flush=True)
    try:
        if shared_build is not None and shared_build.get('key')==key:
            executable=shared_build['executable'];record['reused_simulator_build']=str(executable)
        else:
            obj=directory/'obj'
            command=['verilator','--cc','--exe','--build','--assert','-j',str(jobs),'--top-module','uqu_perfsim_tb',
                '--prefix','Vuqu_perfsim_tb','-Mdir',str(obj),'-o','uqu_perfsim','-O3','-CFLAGS','-O3 -std=c++17 -I'+str(directory/'include')+' -I'+str(ROOT/'verif/perfsim/models'),
                *HDL_LANGUAGE_ARGS,*['-I'+str(p) for p in includes],*[f'-G{k}={v}' for k,v in parameters.items()],
                *map(str,sources),str(driver)]
            result=subprocess.run(command,cwd=directory,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
            (directory/'build.log').write_text(result.stdout)
            if result.returncode:raise RuntimeError('Verilator reference build failed: '+result.stdout[-3000:])
            executable=obj/'uqu_perfsim'
            if shared_build is not None:shared_build.update(key=key,executable=executable)
        record['executable_sha256']=sha(executable)
        record['command']=[str(executable),'program-image.bin',str(max_cycles),str(image.entry),'1','1',str(image.tohost),str(start),str(stop),'retire.bin']
        env=dict(os.environ,UQU_PERFSIM_TRAPS=str(directory/'expected-traps.bin'))
        result=subprocess.run(record['command'],cwd=directory,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
        (directory/'native.log').write_text(result.stdout)
        native=json.loads((directory/'native.json').read_text())
        if result.returncode or native['status']!='passed':raise RuntimeError(native.get('detail') or result.stdout)
        record['status']='passed'
        if start:
            window=dict(cycles=native['stop']['cycle']-native['start']['cycle'],retired=native['stop']['retired']-native['start']['retired'])
            evidence=dict(status='passed',window=window,memory_environment=profile)
            (directory/'benchmark.json').write_text(json.dumps(evidence,indent=2)+'\n')
            record['artifacts'].append('benchmark.json')
            record['metrics']=[dict(name='rtl_cycles',value=window['cycles'],unit='cycles'),dict(name='rtl_retired',value=window['retired'],unit='instructions')]
    except BaseException as error:
        record.update(status='failed',detail=str(error));ET.SubElement(case,'failure',message=str(error))
        raise
    finally:
        record['finished_at']=datetime.now(timezone.utc).isoformat();record['wall_seconds']=time.monotonic()-before
        output.write_text(json.dumps(record,indent=2)+'\n');ET.ElementTree(tests).write(directory/'results.xml',encoding='unicode')
    return directory

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='rv32i');parser.add_argument('--elf',type=Path,required=True)
    parser.add_argument('--memory',type=Path);parser.add_argument('--imem-latency',type=int,default=1)
    parser.add_argument('--dmem-latency',type=int,default=1);parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args();path=Path(args.config)
    if not path.is_file():path=ROOT/'config'/(args.config+'.yml')
    config=load_configuration(path,json.loads((ROOT/'config/selectors.json').read_text()))
    print(run(args.elf,path,config,memory=load_memory(args.memory) if args.memory else None,imem=args.imem_latency,dmem=args.dmem_latency,jobs=args.jobs))
