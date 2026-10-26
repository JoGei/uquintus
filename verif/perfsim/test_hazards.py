#!/usr/bin/env python3
"""Compare fine forwarding and operand retention windows with the RTL hazard unit."""
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
    folder=ROOT/'build/uquintus-perfsim-hazards/verilator/perfsim_hazards'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True);write_header(json.loads((ROOT/'config/selectors.json').read_text()),folder/'include')
    source=[ROOT/'src/uquintus/uqu_hazard.v']
    files=[*source,ROOT/'verif/perfsim/models/uqu_hazard_windows.h',ROOT/'verif/perfsim/tests/hazard_windows_rtl.cpp',Path(__file__),ROOT/'config/selectors.json']
    hashes={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    version=subprocess.check_output(['verilator','--version'],text=True).strip()
    cases=[(1,m,r) for m in range(16) for r in (0,1)]+[(0,0,r) for r in (0,1)]
    names=[f'f{f}_m{m}_r{r}' for f,m,r in cases]
    record=dict(schema_version=1,kind='regression',configuration_scope='component',component='perfsim_hazards',
        configuration=dict(name='perfsim-hazards',parameters={}),target='verilator',selection='native_rtl_equivalence',
        context=dict(scope='1000 two-producer scenarios per path mask/retention; load/CSR readiness, WAW, x0, stalls and RF fallback'),
        source_sha256=hashes,tools=dict(verilator=version),required_tests=names,results_file='results.xml',
        status='running',artifacts=['native.log'])
    xml=ET.Element('testsuites');suite=ET.SubElement(xml,'testsuite',name='perfsim_hazards')
    print('Hazard artifacts:',folder,flush=True)
    try:
        with (folder/'native.log').open('w') as log:
            for (f,m,r),name in zip(cases,names):
                key=hashlib.sha256(json.dumps([hashes,version,f,m,r],sort_keys=True).encode()).hexdigest()
                cache=ROOT/'build/perfsim-hazards-rtl'/key;exe=cache/'Vuqu_hazard'
                case=ET.SubElement(suite,'testcase',name=name)
                cache.mkdir(parents=True,exist_ok=True)
                if not exe.is_file():
                    cmd=['verilator','--cc','--exe','--build','-j',str(a.jobs),'-Wno-fatal','--top-module','uqu_hazard','-Mdir',str(cache),
                        '-GMUA_FORWARDING='+str(f),'-GMUA_FORWARD_EX_TO_DE='+str(bool(m&1)*1),
                        '-GMUA_FORWARD_MEM_TO_DE='+str(bool(m&2)*1),'-GMUA_FORWARD_MEM_TO_EX='+str(bool(m&4)*1),
                        '-GMUA_FORWARD_WB_TO_EX='+str(bool(m&8)*1),'-GMUA_DE_OPERAND_RETENTION='+str(r),'-I'+str(folder/'include'),
                        *map(str,source),str(ROOT/'verif/perfsim/tests/hazard_windows_rtl.cpp'),'-CFLAGS',
                        f'-std=c++17 -DUQU_MASTER={f} -DUQU_MASK={m} -DUQU_RETAIN={r} -I'+str(ROOT/'verif/perfsim/models')]
                    subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
                r=subprocess.run([str(exe)],stdout=log,stderr=subprocess.STDOUT)
                if r.returncode:
                    ET.SubElement(case,'failure',message='native Hazard differs from RTL')
                    raise RuntimeError('Hazard mismatch; see '+str(folder/'native.log'))
        record['status']='passed'
    except BaseException as error:record.update(status='failed',detail=str(error));raise
    finally:
        ET.ElementTree(xml).write(folder/'results.xml',encoding='unicode',xml_declaration=True)
        (folder/'report.json').write_text(json.dumps(record,indent=2)+'\n')
    print('PASS:',len(cases)*1000,'hazard admission scenarios',flush=True)
if __name__=='__main__':main()
