"""Build the local verification device against an externally supplied Spike SDK."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

SOURCE=Path(__file__).resolve().parents[2]/'reference/spike_irq.cc'


def build_device(directory, info):
    root=Path(os.environ.get('SPIKE_ROOT') or Path(info['resolved_executable']).parent.parent)
    include,library=root/'include',root/'lib/libriscv.so'
    if not (include/'riscv/sim.h').is_file() or not library.is_file():
        raise ValueError('sampled-state/IRQ reference requires matching Spike headers and libriscv.so; set SPIKE_ROOT')
    cxx=shutil.which(os.environ.get('CXX','c++'))
    if not cxx: raise ValueError('sampled-state/IRQ reference requires an external host C++ compiler (CXX)')
    inputs=[SOURCE,library,*sorted((include/'riscv').rglob('*.h')),*sorted((include/'fesvr').rglob('*.h'))]
    hashes={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    destination=directory/'spike-irq.so'
    command=[cxx,'-std=c++17','-fPIC','-shared','-I'+str(include),str(SOURCE),
             '-L'+str(library.parent),'-Wl,-rpath,'+str(library.parent),'-lriscv','-o',str(destination)]
    evidence=dict(command=command,source_sha256=hashes,
                  compiler=subprocess.check_output([cxx,'--version'],text=True).strip(),status='running')
    try:
        with (directory/'spike-irq-build.log').open('w') as output:
            result=subprocess.run(command,stdout=output,stderr=subprocess.STDOUT,timeout=60)
        if result.returncode: raise ValueError('Spike IRQ device compilation failed; see spike-irq-build.log')
        evidence.update(status='passed',sha256=hashlib.sha256(destination.read_bytes()).hexdigest())
    except BaseException:
        evidence['status']='failed'
        raise
    finally:
        (directory/'spike-irq-build.json').write_text(json.dumps(evidence,indent=2)+'\n')
    return destination
