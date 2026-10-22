"""Zfinx architectural observations, independent of native RTL/arithmetic models.

Expected values come only from Spike pre/post snapshots and prior Spike GPR
writes. This module describes ISA fields and observer masks; it never predicts
an FP arithmetic result or copies an expected value from the DUT.
"""
import json
from pathlib import Path

FP_CSRS = {1:'fflags', 2:'frm', 3:'fcsr'}


def coverage(events):
    """Descriptive coverage for a trace already accepted by the reference.

    Encoded mode 7 is dynamic; its effective mode comes from the compared FP
    CSR read. This is observed execution coverage, not ISA certification.
    """
    operations, registers, csr_forms, traps = {}, {k:set() for k in ('rd','rs1','rs2','rs3')}, {}, {}
    modes=set()
    unary={'fsqrt','fclass','fcvt_w_s','fcvt_wu_s','fcvt_s_w','fcvt_s_wu'}
    fused={'fmadd','fmsub','fnmsub','fnmadd'}
    for row in events:
        if row['type']!='instruction': continue
        insn=row['rvfi_insn']
        desc=operation(insn)
        if row['rvfi_trap']:
            key=str(row['cause'])
            traps[key]=traps.get(key,0)+1
            continue
        if insn & 127==0x73 and insn >> 20 in FP_CSRS:
            key=f'{FP_CSRS[insn >> 20]}:{insn >> 12 & 7}'
            csr_forms[key]=csr_forms.get(key,0)+1
        if not desc: continue
        modes.add(row['rvfi_mode'])
        op=operations.setdefault(desc['name'],dict(count=0,static_rm={},dynamic_rm={}))
        op['count']+=1
        registers['rd'].add(insn >> 7 & 31)
        for index in range(3 if desc['name'] in fused else 1 if desc['name'] in unary else 2):
            registers[f'rs{index+1}'].add(desc['sources'][index])
        rm=desc['rounding']
        if rm is not None:
            dynamic=rm==7
            if dynamic: rm=row['csrs']['frm']['rdata']
            counts=op['dynamic_rm' if dynamic else 'static_rm']
            counts[str(rm)]=counts.get(str(rm),0)+1
    return dict(schema_version=1,scope='Successfully compared RVFI/Spike execution; not certification',
                operations=operations,registers={k:sorted(v) for k,v in registers.items()},
                modes=sorted(modes),fp_csr_forms=csr_forms,traps=traps)


def operation(insn):
    """Return mnemonic, three sources/use mask and rounding field, or None.

    Reserved rounding fields still describe an attempted FP instruction; the
    reference determines whether it traps. Fixed function fields are checked.
    """
    opcode, f, upper = insn & 127, insn >> 12 & 7, insn >> 25
    a,b,c = insn >> 15 & 31, insn >> 20 & 31, insn >> 27
    if opcode in (0x43,0x47,0x4b,0x4f) and not (insn >> 25 & 3):
        name={0x43:'fmadd',0x47:'fmsub',0x4b:'fnmsub',0x4f:'fnmadd'}[opcode]
        return dict(name=name, sources=(a,b,c), rounding=f)
    if opcode != 0x53:
        return None
    if upper in (0,4,8,12):
        name={0:'fadd',4:'fsub',8:'fmul',12:'fdiv'}[upper]
        return dict(name=name, sources=(a,b,0), rounding=f)
    if upper==0x2c and b==0:
        return dict(name='fsqrt',sources=(a,0,0),rounding=f)
    if upper==0x10 and f in (0,1,2):
        return dict(name=('fsgnj','fsgnjn','fsgnjx')[f],sources=(a,b,0),rounding=None)
    if upper==0x14 and f in (0,1):
        return dict(name=('fmin','fmax')[f],sources=(a,b,0),rounding=None)
    if upper==0x50 and f in (0,1,2):
        return dict(name=('fle','flt','feq')[f],sources=(a,b,0),rounding=None)
    if upper==0x70 and f==1 and b==0:
        return dict(name='fclass',sources=(a,0,0),rounding=None)
    if upper in (0x60,0x68) and b in (0,1):
        name=(('fcvt_w_s','fcvt_wu_s') if upper==0x60 else ('fcvt_s_w','fcvt_s_wu'))[b]
        return dict(name=name,sources=(a,0,0),rounding=f)
    return None


def read_fp_trace(path):
    """Strict simulation companion, keyed by RVFI epoch/order, not extra RVFI ports."""
    result={}
    previous=(-1,-1)
    widths=dict(epoch=32,order=64,pc=32,insn=32,rs3_addr=5,rs3_rdata=32,rm=3)
    for number,line in enumerate(Path(path).read_text().splitlines(),1):
        row=json.loads(line)
        if not isinstance(row,dict) or set(row)!=set(widths):
            raise ValueError(f'{path}:{number}: malformed FP companion')
        if any(type(row[k]) is not int or not 0<=row[k]<1<<w for k,w in widths.items()):
            raise ValueError(f'{path}:{number}: FP companion value out of range')
        key=row['epoch'],row['order']
        if key<=previous:
            raise ValueError('duplicate or out-of-order FP companion')
        if row['rs3_addr']==0 and row['rs3_rdata']:
            raise ValueError('FP companion x0 data must be zero')
        result[key]=row
        previous=key
    return result


def channels(insn, trapped, before, after, effects):
    """FP observer masks and log consistency from the independent reference."""
    if before is None or after is None:
        raise ValueError('Zfinx comparison requires independent FP CSR snapshots')
    for state in (before,after):
        if state['fcsr'] != (state['frm']<<5)|state['fflags'] or state['frm']>7 or state['fflags']>31:
            raise ValueError('inconsistent Spike FP CSR aliases')
        if state['mstatus'] & 0x6000 or state['misa'] & ((1<<5)|(1<<3)|(1<<16)):
            raise ValueError('Spike Zfinx FS/F/D/Q state violates configured ISA')
    desc=operation(insn)
    csr_address=insn >> 20 if insn & 127==0x73 and insn >> 12 & 7 else None
    function,source,dest=insn >> 12 & 7,insn >> 15 & 31,insn >> 7 & 31
    writes=bool(not trapped and csr_address in FP_CSRS and (function in (1,5) or source))
    masks={}
    if not trapped and desc:
        masks={'fflags':(31,31),'fcsr':(31,31)}
        if desc['rounding']==7:
            masks.update(frm=(7,0),fcsr=(255,31))
        allowed={1}
        if before['frm']!=after['frm']:
            raise ValueError('FP instruction changed rounding CSR')
        if before['fflags'] & ~after['fflags']:
            raise ValueError('FP instruction cleared accrued exception flags')
        if before['fflags']!=after['fflags'] and set(effects)!={1}:
            raise ValueError('missing Spike accrued-flags commit effect')
    elif csr_address in FP_CSRS and not trapped:
        read=dest!=0 if function in (1,5) else True
        name=FP_CSRS[csr_address]
        masks={name:(0xffffffff if read else 0,0xffffffff if writes else 0)}
        masks={name:pair for name,pair in masks.items() if any(pair)}
        allowed={1,2} if writes and csr_address==3 else {csr_address} if writes else set()
        if writes:
            if csr_address==1: masks['fcsr']=(0,31)
            elif csr_address==2: masks['fcsr']=(0,224)
            else: masks.update(fflags=(0,31),frm=(0,7))
        if set(effects)!=allowed:
            raise ValueError('missing/extra Spike explicit FP CSR commit effect')
        for untouched in (('frm',) if writes and csr_address==1 else
                          ('fflags',) if writes and csr_address==2 else
                          () if writes else tuple(FP_CSRS.values())):
            if before[untouched]!=after[untouched]:
                raise ValueError('explicit FP CSR access changed unrelated state')
    else:
        allowed=set()
        if any(before[name]!=after[name] for name in FP_CSRS.values()):
            raise ValueError('non-FP/faulting instruction changed FP state')
    if not set(effects)<=allowed:
        raise ValueError('unexpected Spike FP CSR effect')
    for address,value in effects.items():
        if value!=after[FP_CSRS[address]]:
            raise ValueError('Spike FP CSR log and post-snapshot disagree')
    return masks
