#!/usr/bin/env python3
"""Matched ELF/config/memory validation of the native and RTL platforms."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'verif/sim/common'))
from config_frontend import load_configurations
from dependencies import digest
from perfsim import generate,prepare_blocks,execute
from memory import load as load_memory
from compare import compare
from rtl import run as run_rtl

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='rv32i');p.add_argument('--elf',type=Path,required=True)
    p.add_argument('--memory',type=Path);p.add_argument('--jobs',type=int,default=4)
    p.add_argument('--max-error',type=float,default=.005)
    a=p.parse_args()
    if not 0<=a.max_error<1:p.error('max-error must be in [0,1)')
    profile=load_memory(a.memory)
    rows=load_configurations([a.config],contract='map_dse',memory=profile)
    kwargs=dict(etiss_root=Path(os.environ['ETISS_ROOT']),jobs=a.jobs,
                cmake_args=['-DBoost_DIR=/usr/lib/x86_64-linux-gnu/cmake/Boost-1.83.0'])
    upstream=ROOT/'build/deps/perfsim-upstream'
    isa=Path(os.environ['PERFSIM_ISA_PYTHON']);model=Path(os.environ['PERFSIM_MODEL_PYTHON'])
    folder=ROOT/'build/investigations/perfsim-platform'/(
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    record=dict(status='running',configuration=rows[0]['resolved'],elf_sha256=digest(a.elf),memory=profile,
                error_budget=dict(relative=a.max_error,short_test_absolute_cycles=1))
    try:
        instruction,build=generate(rows,upstream,isa,model,**kwargs)
        generated,map_build,_=prepare_blocks(rows,instruction,build,a.elf,upstream,isa,model,scheduler='map_explorer',**kwargs)
        record['source_sha256']=map_build['source_sha256']
        native,=execute(rows,generated,map_build,a.elf,100000000,300,True,timing_trace=True,scheduler='map_explorer',verify=True)
        record['perfsim']=str(native)
        rtl=run_rtl(a.elf,rows[0]['path'],rows[0]['config'],memory=profile,jobs=a.jobs)
        record['rtl']=str(rtl)
        c=compare(native,rtl);record['comparison']=c
        if 'timing_error' not in c:raise ValueError('validation requires measurement markers')
        error=c['timing_error']
        if error['absolute_cycles']>1 and error['absolute_relative_error']>a.max_error:
            raise ValueError('RTL cycle accuracy gate failed')
        record['status']='passed'
    except BaseException as error:
        record.update(status='failed',detail=str(error));raise
    finally:(folder/'validation.json').write_text(json.dumps(record,indent=2)+'\n');print('Validation:',folder,flush=True)

if __name__=='__main__':main()
