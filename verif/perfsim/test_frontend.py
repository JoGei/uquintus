#!/usr/bin/env python3
"""Make helper: compare the perfsim queue component against the real IF RTL."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'verif/sim/common'))
from component_runner import bender_include_dirs, load_component, bender_source_options
from hw_config import write_header


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bender',default='bender')
    p.add_argument('--jobs',type=int,default=2)
    p.add_argument('--masks',default='0,1,2,3,4,5,6,7')
    p.add_argument('--depths',default='2,4')
    p.add_argument('--compressed',default='0,1',help='ISA_C values to compare')
    p.add_argument('--latencies',default='1,2,5')
    p.add_argument('--memory-profile',type=int,choices=(0,1,2),default=0,help='0=fixed, 1=variable, 2=cache stub (queue tests only)')
    p.add_argument('--prediction',action='store_true',help='exercise clocked BPU/replay and DE stalls')
    p.add_argument('--hwords',default='0,2,6,8',help='replay capacities for --prediction')
    args=p.parse_args()
    if args.prediction and args.memory_profile:p.error('memory profiles currently require queue tests')
    compressed=[int(x) for x in args.compressed.split(',')]
    if not compressed or any(c not in (0,1) for c in compressed):p.error('compressed must contain 0/1')
    masks,depths,latencies=([int(x) for x in s.split(',')] for s in (args.masks,args.depths,args.latencies))
    if args.jobs<1 or any(x<0 or x>7 for x in masks) or any(x<2 for x in depths) or any(x<1 for x in latencies):
        p.error('invalid jobs, bypass mask, depth or latency')
    hwords=[int(x) for x in args.hwords.split(',')] if args.prediction else [0]
    if any(h<0 or (0 in compressed and h%2) for h in hwords):p.error('invalid replay halfword capacity')
    driver=ROOT/'verif/perfsim/tests'/('frontend_prediction_rtl.cpp' if args.prediction else 'frontend_rtl.cpp')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    output=ROOT/'build/uquintus-perfsim-frontend/verilator/perfsim_frontend'/stamp
    output.mkdir(parents=True)
    print('Artifacts:',output,flush=True)
    catalog=json.loads((ROOT/'config/selectors.json').read_text())
    write_header(catalog,output/'include')
    options=bender_source_options(load_component('if'))
    sources=[Path(x) for x in subprocess.check_output([args.bender,'script','flist',*options],cwd=ROOT,text=True).splitlines() if x.strip()]
    tree=json.loads(subprocess.check_output([args.bender,'sources',*options],cwd=ROOT,text=True))
    includes=[output/'include',*bender_include_dirs(tree)]
    headers=sorted({h for directory in includes for pattern in ('*.vh','*.svh') for h in directory.rglob(pattern)})
    # The generated selector header is already identified by selectors.json;
    # keep its per-run directory out of the reusable compilation key.
    headers=[h for h in headers if not h.is_relative_to(output)]
    files=[*sources,*headers,ROOT/'verif/perfsim/models/uqu_frontend.h',ROOT/'verif/perfsim/models/uqu_memory.h',driver,ROOT/'verif/perfsim/models/uqu_bpu_model.h',Path(__file__),ROOT/'config/selectors.json']
    hashes={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    version=subprocess.check_output(['verilator','--version'],text=True).strip()
    tests=[f'c{c}_h{h}_bypass{b}_depth{d}_latency{l}' for c in compressed for h in hwords for b in masks for d in depths for l in latencies]
    record=dict(memory_profile=args.memory_profile,schema_version=1,kind='regression',configuration_scope='component',
                configuration=dict(name='perfsim-frontend',parameters=dict(ISA_C=compressed)),
                component='perfsim_frontend',target='verilator',selection='clocked_bpu_replay' if args.prediction else 'queue_equivalence',
                context=dict(scope=('6000 RTL edges with BPU/replay and independent DE stalls' if args.prediction else '3000 RTL edges per case; immediate grants, mixed 16/32-bit fetch')),
                status='running',required_tests=tests,results_file='results.xml',
                source_sha256=hashes,tools=dict(verilator=version),artifacts=['native.log'])
    xml=ET.Element('testsuites');suite=ET.SubElement(xml,'testsuite',name='perfsim_frontend')
    try:
        with (output/'native.log').open('w') as log:
            for c in compressed:
             for h in hwords:
              for b in masks:
                for d in depths:
                    key=hashlib.sha256(json.dumps([hashes,version,c,b,d,h,args.prediction],sort_keys=True).encode()).hexdigest()
                    cache=ROOT/'build/perfsim-frontend-rtl'/key
                    exe=cache/'Vuqu_stage_if'
                    if not exe.is_file():
                        cache.mkdir(parents=True,exist_ok=True)
                        command=['verilator','--cc','--exe','--build','-j',str(args.jobs),'-Wno-fatal',
                            '--top-module','uqu_stage_if','-Mdir',str(cache),
                            '-GISA_C='+str(c),'-GMUA_REDIRECT_BYPASS='+str(b),'-GMUA_IF_BUFFER_WORDS='+str(d),
                            *(['-GMUA_BRANCH_PREDICTOR=2','-GMUA_BTB=1','-GMUA_BTB_IDATA_HWORDS='+str(h)] if args.prediction else []),
                            *['-I'+str(i) for i in includes],*map(str,sources),
                            str(driver),
                            '-CFLAGS','-std=c++17 -DUQU_TEST_C='+str(c)+' -DUQU_TEST_H='+str(h)+' -I'+str(ROOT/'verif/perfsim/models')]
                        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
                    for l in latencies:
                        case=ET.SubElement(suite,'testcase',name=f'c{c}_h{h}_bypass{b}_depth{d}_latency{l}')
                        start=time.monotonic()
                        result=subprocess.run([str(exe),str(b),str(d),str(l),*([str(args.memory_profile)] if not args.prediction else [])],stdout=log,stderr=subprocess.STDOUT)
                        case.set('time',str(time.monotonic()-start))
                        if result.returncode:
                            ET.SubElement(case,'failure',message='frontend differs from RTL; see native.log')
                            raise RuntimeError('frontend differs from RTL; see '+str(output/'native.log'))
            record['status']='passed'
    except BaseException as e:
        record.update(status='failed',detail=str(e));raise
    finally:
        ET.ElementTree(xml).write(output/'results.xml',encoding='unicode',xml_declaration=True)
        (output/'report.json').write_text(json.dumps(record,indent=2)+'\n')
    print('PASS:',len(tests),'frontend RTL comparisons',flush=True)


if __name__=='__main__':
    main()
