#!/usr/bin/env python3
"""Compare the native BPU component with RTL, including packed replay data."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'verif/sim/common'))
from hw_config import write_header

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--jobs',type=int,default=4)
    a=p.parse_args()
    if a.jobs<1:p.error('positive jobs required')
    folder=ROOT/'build/uquintus-perfsim-bpu/verilator/perfsim_bpu'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True);write_header(json.loads((ROOT/'config/selectors.json').read_text()),folder/'include')
    source=[ROOT/'src/uquintus'/n for n in ('uqu_bpu.v','uqu_btb.v','uqu_bp_bimodal.v')]
    files=[*source,ROOT/'verif/perfsim/models/uqu_bpu_model.h',ROOT/'verif/perfsim/tests/bpu_rtl.cpp',Path(__file__),ROOT/'config/selectors.json']
    hashes={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    version=subprocess.check_output(['verilator','--version'],text=True).strip()
    cases=[(c,p,e,h) for c in (0,1) for p in (1,2) for e in (2,16) for h in (0,6)]
    names=[f'c{c}_p{p}_e{e}_h{h}' for c,p,e,h in cases]
    record=dict(schema_version=1,kind='regression',configuration_scope='component',component='perfsim_bpu',
        configuration=dict(name='perfsim-bpu',parameters={}),target='verilator',selection='native_rtl_equivalence',
        context=dict(scope='4000 lookup/update/capture edges per case; pre-edge state, invalidation and packed payload'),
        source_sha256=hashes,tools=dict(verilator=version),required_tests=names,results_file='results.xml',
        status='running',artifacts=['native.log'])
    xml=ET.Element('testsuites');suite=ET.SubElement(xml,'testsuite',name='perfsim_bpu')
    print('BPU artifacts:',folder,flush=True)
    try:
        with (folder/'native.log').open('w') as log:
            for (c,p,e,h),name in zip(cases,names):
                key=hashlib.sha256(json.dumps([hashes,version,c,p,e,h],sort_keys=True).encode()).hexdigest()
                cache=ROOT/'build/perfsim-bpu-rtl'/key;exe=cache/'Vuqu_bpu'
                case=ET.SubElement(suite,'testcase',name=name)
                cache.mkdir(parents=True,exist_ok=True)
                if not exe.is_file():
                    cmd=['verilator','--cc','--exe','--build','-j',str(a.jobs),'-Wno-fatal','--top-module','uqu_bpu','-Mdir',str(cache),
                        '-GISA_C='+str(c),'-GMUA_BRANCH_PREDICTOR='+str(p),'-GMUA_BP_ENTRIES=4','-GMUA_BTB=1',
                        '-GMUA_BTB_ENTRIES='+str(e),'-GMUA_BTB_IDATA_HWORDS='+str(h),'-I'+str(folder/'include'),
                        *map(str,source),str(ROOT/'verif/perfsim/tests/bpu_rtl.cpp'),'-CFLAGS',
                        f'-std=c++17 -DUQU_BPU_C={c} -DUQU_BPU_P={p} -DUQU_BPU_E={e} -DUQU_BPU_H={h} -I'+str(ROOT/'verif/perfsim/models')]
                    subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
                r=subprocess.run([str(exe)],stdout=log,stderr=subprocess.STDOUT)
                if r.returncode:
                    ET.SubElement(case,'failure',message='native BPU differs from RTL')
                    raise RuntimeError('BPU mismatch; see '+str(folder/'native.log'))
        record['status']='passed'
    except BaseException as error:record.update(status='failed',detail=str(error));raise
    finally:
        ET.ElementTree(xml).write(folder/'results.xml',encoding='unicode',xml_declaration=True)
        (folder/'report.json').write_text(json.dumps(record,indent=2)+'\n')
    print('PASS:',len(cases)*4000,'BPU RTL edges',flush=True)
if __name__=='__main__':main()
