"""Native CSR channel catalog and independent architectural observations."""
from pathlib import Path
import re

from csregfile_model import CSRModel


def load_catalog():
    header = Path(__file__).resolve().parents[2]/'common/uqu_rvfi_csrs.vh'
    rows = re.findall(r"`UQU_RVFI_CSR\((\w+), (32|64), (\d+), 12'h([0-9a-f]+), 12'h([0-9a-f]+), 12'h([0-9a-f]+), 12'h([0-9a-f]+)\)",(header.parent/'uqu_rvfi_csr_list.vh').read_text())
    result = {name:dict(width=int(width),index=int(index),addresses=tuple(int(a,16) for a in addresses))
              for name,width,index,*addresses in rows}
    count = int(re.search(r'`define UQU_RVFI_CSR_COUNT (\d+)',header.read_text())[1])
    if len(result)!=count or sorted(r['index'] for r in result.values())!=list(range(count)):
        raise ValueError('CSR catalog has missing/duplicate slots')
    addresses=[a for r in result.values() for a in r['addresses'] if a!=0xfff]
    if len(addresses)!=len(set(addresses)):
        raise ValueError('CSR addresses must map to exactly one canonical channel')
    return result


CSR_CATALOG = load_catalog()


class CSRObservation:
    """Expected masks and state from the shared mathematical CSR model.

    Counter increments occur between instruction events: only explicit counter
    writes have a write mask, including writes through their high-half address.
    """
    def __init__(self, params):
        self.model = CSRModel(params)
        self.read_result = 0

    def value(self, name, row, inputs):
        if name=='mcycle': return self.model.cycle
        if name=='minstret': return self.model.instret
        if row['width']==64: return 0  # Hardwired HPM counters.
        try: return self.model.read(row['addresses'][0],inputs)
        except KeyError: return 0  # Unavailable feature; masks must remain zero.

    def step(self, inputs, event):
        before = {name:self.value(name,row,inputs) for name,row in CSR_CATALOG.items()}
        query,_ = self.model.query(inputs)
        self.read_result = query['rdata']
        self.model.step(inputs)
        if not inputs['rst_n'] or not event:
            return {}
        result = {}
        for name,row in CSR_CATALOG.items():
            low,high,user,user_high = row['addresses']
            selected = inputs['csr_addr'] in tuple(a for a in row['addresses'] if a!=0xfff)
            mask = 0xffffffff << (32 if row['width']==64 and inputs['csr_addr'] in (high,user_high) else 0)
            read = mask if selected and query['read'] else 0
            write = mask if selected and query['write'] and inputs['csr_commit'] else 0
            if inputs['trap']:
                if name in ('mstatus','mtvec'): read=0xffffffff
                if name in ('mstatus','mepc','mcause','mtval'): write=0xffffffff
            if inputs['mret']:
                if name in ('mstatus','mepc'): read=0xffffffff
                if name=='mstatus': write=0xffffffff
            if inputs['fp_flags_valid'] and name in ('fflags','fcsr'):
                read |= 31
            if inputs.get('fp_rm_read'):
                if name == 'frm': read |= 7
                if name == 'fcsr': read |= 0xe0
            alias_write = query['write'] and inputs['csr_commit']
            if name == 'fflags' and (inputs['fp_flags_valid'] or (alias_write and inputs['csr_addr'] == 3)):
                write |= 31
            if name == 'frm' and alias_write and inputs['csr_addr'] == 3:
                write |= 7
            if name == 'fcsr':
                if inputs['fp_flags_valid'] or (alias_write and inputs['csr_addr'] == 1): write |= 31
                if alias_write and inputs['csr_addr'] == 2: write |= 0xe0
            if read or write:
                result[name] = dict(rmask=read,wmask=write,rdata=before[name] if read else 0,
                    wdata=self.value(name,row,inputs) if write else before[name])
        return result
