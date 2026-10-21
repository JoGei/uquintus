"""Read the simulation JSONL stream, validating the native RVFI profile."""
import json
from pathlib import Path
from rvfi_csrs import CSR_CATALOG


RVFI_WIDTHS = dict(order=64, insn=32, trap=1, halt=1, intr=1, mode=2, ixl=2,
    rs1_addr=5, rs2_addr=5, rs1_rdata=32, rs2_rdata=32, rd_addr=5, rd_wdata=32,
    pc_rdata=32, pc_wdata=32, mem_addr=32, mem_rmask=4, mem_wmask=4,
    mem_rdata=32, mem_wdata=32, mem_fault=1, mem_fault_rmask=4, mem_fault_wmask=4)


def read_trace(path):
    """Return records or raise ValueError on malformed/inconsistent output.

    Checks the observation format and event sequencing, not ISA execution.
    An instruction model must independently check the recorded effects.
    """
    records = []
    epoch, order, entry, next_pc = -1, 0, False, None
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError('record must be an object')
            kind = record.get('type')
            fields = {'reset': set(), 'interrupt': {'pc','cause','target','csrs'},
                      'instruction': {'rvfi_'+key for key in RVFI_WIDTHS} | {'cause','tval','csrs'}}
            if kind not in fields or set(record) != fields[kind] | {'type','epoch'}:
                raise ValueError('unknown record type or incorrect field set')
            if type(record['epoch']) is not int:
                raise ValueError('epoch must be an integer')
            if kind!='reset':
                csrs=record['csrs']
                if not isinstance(csrs,dict): raise ValueError('csrs must be an object')
                for name,values in csrs.items():
                    if name not in CSR_CATALOG or not isinstance(values,dict) or set(values)!={'rmask','wmask','rdata','wdata'}:
                        raise ValueError('unknown or malformed CSR channel')
                    width=CSR_CATALOG[name]['width']
                    if any(type(v) is not int or not 0<=v<2**width for v in values.values()):
                        raise ValueError('CSR field out of range')
                    if not (values['rmask'] or values['wmask']):
                        raise ValueError('inactive channel in sparse CSR object')
            if kind == 'reset':
                if record['epoch'] != epoch+1:
                    raise ValueError('reset epochs must be consecutive from zero')
                epoch, order, entry, next_pc = epoch+1, 0, False, None
            elif epoch < 0 or record['epoch'] != epoch:
                raise ValueError('event outside its reset epoch')
            elif kind == 'interrupt':
                for name in ('pc','cause','target'):
                    if type(record[name]) is not int or not 0 <= record[name] < 2**32:
                        raise ValueError('interrupt field out of range')
                if record['cause'] not in (3,7,11):
                    raise ValueError('unsupported interrupt cause')
                if next_pc is not None and record['pc'] != next_pc:
                    raise ValueError('interrupt saved PC does not match instruction boundary')
                entry, next_pc = True, record['target']
            else:
                r = {name:record['rvfi_'+name] for name in RVFI_WIDTHS}
                for name, width in (('cause',5),('tval',32)):
                    if type(record[name]) is not int or not 0 <= record[name] < 2**width:
                        raise ValueError('trap diagnostic out of range')
                    if not r['trap'] and record[name]:
                        raise ValueError('trap diagnostic without trap')
                for name, width in RVFI_WIDTHS.items():
                    if type(r[name]) is not int or not 0 <= r[name] < 2**width:
                        raise ValueError('RVFI field out of range: '+name)
                if r['order'] != order:
                    raise ValueError('duplicate or missing RVFI order')
                if r['intr'] != entry:
                    raise ValueError('incorrect first-handler marker')
                if next_pc is not None and r['pc_rdata'] != next_pc:
                    raise ValueError('discontinuous instruction PC')
                if r['ixl'] != 1 or r['mode'] not in (0,3) or r['halt']:
                    raise ValueError('unsupported XLEN, mode or halt')
                for name in ('rs1','rs2','rd'):
                    data = r[name+('_wdata' if name=='rd' else '_rdata')]
                    if r[name+'_addr'] == 0 and data != 0:
                        raise ValueError('x0/nonwriter data must be zero')
                if r['trap'] and (r['rd_addr'] or r['mem_rmask'] or r['mem_wmask']):
                    raise ValueError('trapped instruction reports committed effects')
                if r['mem_rmask'] & r['mem_wmask']:
                    raise ValueError('native profile has no atomic memory operations')
                if any(r[name] for name in ('mem_rmask','mem_wmask','mem_fault_rmask','mem_fault_wmask')) and r['mem_addr'] & 3:
                    raise ValueError('RVFI memory address must be word aligned')
                if r['mem_fault'] and not r['trap']:
                    raise ValueError('memory fault without a trap')
                if not r['mem_fault'] and (r['mem_fault_rmask'] or r['mem_fault_wmask']):
                    raise ValueError('fault mask without memory fault')
                order, entry, next_pc = order+1, bool(r['trap']), r['pc_wdata']
            records.append(record)
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError(f'{path}:{line_number}: {error}') from error
    if epoch < 0:
        raise ValueError(f'{path}: no reset epoch')
    return records
