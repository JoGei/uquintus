"""Bounded external Spike execution and strict native RVFI differential checks.

Traps, interrupts and MRET use debugger snapshots of actual Spike state.
An optional verification device drives IRQ inputs at independently checked
native boundaries. No event is silently skipped or resynchronized.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from elf_image import load_elf
from rvfi_trace import read_trace
from toolchain import isa_abi
from spike_zfinx import FP_CSRS, operation as fp_operation, channels as fp_channels, read_fp_trace, coverage as fp_coverage
from interrupts import interrupt_plan, replay_masks, pending_interrupt
from timing import COUNTERS, SAMPLED_CSRS, replay_samples

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / 'verif/reference/spike.lock.json'
MASK = 0xffffffff
RAM_BASE, RAM_SIZE = 0x80000000, 0x10000
CSR_NAMES = {0x301: 'misa', 0x300: 'mstatus', 0x304: 'mie', 0x305: 'mtvec', 0x340: 'mscratch', 0x341: 'mepc',
             0x342: 'mcause', 0x343: 'mtval', 0xf14: 'mhartid',
             0x306: 'mcounteren', 0x320: 'mcountinhibit', 0x344: 'mip', **COUNTERS}
BOOT_INSNS = [0x297, 0x02028593, 0xf1402573, 0x0182a283, 0x00028067]
TRAP_CAUSES = {'trap_instruction_address_misaligned': 0, 'trap_illegal_instruction': 2,
               'trap_breakpoint': 3, 'trap_load_address_misaligned': 4,
               'trap_store_address_misaligned': 6, 'trap_user_ecall': 8,
               'trap_machine_ecall': 11}
SNAPSHOT_CSRS = (*(name for name in dict.fromkeys(CSR_NAMES.values()) if name!='mcounteren'),
                 'mcycleh', 'minstreth')
MSTATUS_MASK = 0x221888


class Mismatch(ValueError):
    def __init__(self, index, field, expected, actual):
        self.observation = dict(index=index, field=field, spike=expected, rvfi=actual)
        super().__init__(f'Spike mismatch at instruction {index}, {field}: '
                         f'Spike={expected!r}, RVFI={actual!r}')


def discover_spike(explicit=None, environ=None):
    env = os.environ if environ is None else environ
    selected = explicit or env.get('SPIKE')
    candidates = [selected] if selected else ([str(Path(env['RISCV']) / 'bin/spike')]
                   if env.get('RISCV') else []) + ['spike']
    for candidate in candidates:
        executable = shutil.which(candidate, path=env.get('PATH', os.defpath))
        if executable:
            return str(Path(executable).absolute())
    raise ValueError('Spike not found; set SPIKE, provide $RISCV/bin/spike or put spike on PATH')


def identify_spike(executable):
    result = subprocess.run([executable, '--help'], text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=10)
    lines = result.stdout.strip().splitlines()
    lock = json.loads(LOCK.read_text())
    sha = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    if (not lines or lines[0] != lock['version_string'] or sha != lock['executable_sha256']):
        raise ValueError('Spike differs from verif/reference/spike.lock.json; '
                         'qualify the new build and update the explicit binary pin')
    for option in ('--log-commits', '--debug-cmd=', '--pc=', '--hartids=', '--pmpregions='):
        if option not in result.stdout:
            raise ValueError(f'Spike lacks required option {option}')
    return dict(lock, executable=executable, resolved_executable=str(Path(executable).resolve()))


def parse_commits(path):
    """Parse the qualified text format, rejecting unrecognized commit effects.

    -l instruction/disassembly lines are distinct from --log-commits lines.
    Loads log addresses only; stores also log a value whose width is access size.
    """
    commits = []
    header = re.compile(r'core\s+(\d+):\s+([03])\s+(0x[0-9a-f]+)\s+\((0x[0-9a-f]+)\)(.*)')
    disasm = re.compile(r'core\s+\d+:\s+0x[0-9a-f]+\s+\(0x[0-9a-f]+\).*')
    effect = re.compile(r'\s+(?:x\s*(\d+)\s+(0x[0-9a-f]+)|c(\d+)_\w+\s+(0x[0-9a-f]+)|mem\s+(0x[0-9a-f]+)(?:\s+(0x[0-9a-f]+))?)')
    exception = re.compile(r'core\s+(\d+): exception (\w+), epc (0x[0-9a-f]+)')
    interrupt = re.compile(r'core\s+(\d+): exception interrupt #(3|7|11), epc (0x[0-9a-f]+)')
    tval = re.compile(r'core\s+(\d+):\s+tval (0x[0-9a-f]+)')
    last_disasm = None
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        match = header.fullmatch(line)
        if not match:
            if disasm.fullmatch(line):
                last_disasm = re.fullmatch(r'core\s+(\d+):\s+(0x[0-9a-f]+)\s+\((0x[0-9a-f]+)\).*', line)
                continue
            trap = exception.fullmatch(line)
            irq = interrupt.fullmatch(line)
            if irq:
                hart,cause,pc=irq.groups()
                commits.append(dict(hart=int(hart),mode=None,pc=int(pc,16),insn=None,
                    registers={},csrs={},memory=[],interrupt=True,cause=int(cause),tval=0,line=number))
                last_disasm=None
                continue
            if trap:
                hart, name, pc = trap.groups()
                if name not in TRAP_CAUSES or last_disasm is None:
                    raise ValueError(f'unsupported or unpaired Spike exception: {line}')
                if (int(last_disasm[1]), int(last_disasm[2], 16)) != (int(hart), int(pc, 16)):
                    raise ValueError('Spike exception does not match the attempted instruction')
                commits.append(dict(hart=int(hart), mode=None, pc=int(pc, 16),
                    insn=int(last_disasm[3], 16), registers={}, csrs={}, memory=[],
                    trap=1, cause=TRAP_CAUSES[name], tval=0, line=number))
                last_disasm = None
                continue
            value = tval.fullmatch(line)
            if value:
                if not commits or not (commits[-1].get('trap') or commits[-1].get('interrupt')) or commits[-1]['hart'] != int(value[1]) or commits[-1].get('tval_seen'):
                    raise ValueError('unpaired or duplicate Spike exception tval')
                commits[-1].update(tval=int(value[2], 16) & MASK, tval_seen=True)
                continue
            if re.fullmatch(r'core\s+\d+: >>>>\s+\S.*', line):
                continue
            raise ValueError(f'unrecognized Spike log line {number}: {line}')
        hart, mode, pc, insn, tail = match.groups()
        row = dict(hart=int(hart), mode=int(mode), pc=int(pc, 16),
                   insn=int(insn, 16), registers={}, csrs={}, memory=[], line=number)
        position = 0
        while position < len(tail):
            token = effect.match(tail, position)
            if not token:
                if not tail[position:].strip(): break
                raise ValueError(f'unrecognized Spike commit effect at line {number}: {tail[position:]}')
            reg, value, csr, csr_value, address, memory_value = token.groups()
            if reg is not None:
                index = int(reg)
                if not 0 < index < 32 or index in row['registers']:
                    raise ValueError('invalid or duplicate Spike register effect')
                row['registers'][index] = int(value, 16)
            elif csr is not None:
                address_csr = int(csr)
                if address_csr in row['csrs']: raise ValueError('duplicate Spike CSR effect')
                row['csrs'][address_csr] = int(csr_value, 16)
            else:
                row['memory'].append(dict(address=int(address, 16),
                    value=int(memory_value, 16) if memory_value else None,
                    size=(len(memory_value)-2)//2 if memory_value else None))
            position = token.end()
        commits.append(row)
    if not commits: raise ValueError('Spike emitted no commit records')
    return commits


def irq_index(mask):
    return ((mask >> 3)&1) | (((mask >> 7)&1)<<1) | (((mask >> 11)&1)<<2)


def debug_commands(steps, masks=None, sampled=False, zfinx=False):
    names = (*SNAPSHOT_CSRS, *FP_CSRS.values()) if zfinx else SNAPSHOT_CSRS
    snapshot = ['pc 0', 'priv 0', *('reg 0 '+name for name in names)]
    commands=[] if sampled else list(snapshot)
    if masks is not None and len(masks)!=steps: raise ValueError('IRQ replay step count mismatch')
    for index in range(steps):
        if sampled:
            commands += ['mem 50000100', *snapshot]
        elif masks is not None: commands.append(f'mem {0x50000000+8*irq_index(masks[index]):x}')
        commands += ['run 1',*snapshot]
    return '\n'.join([*commands,'quit'])+'\n'


def read_snapshots(path, steps, masks=None, sampled=False, zfinx=False):
    names = (*SNAPSHOT_CSRS, *FP_CSRS.values()) if zfinx else SNAPSHOT_CSRS
    lines = Path(path).read_text().splitlines()
    warning = "warning: tohost and fromhost symbols not in ELF; can't communicate with target"
    if lines and lines[0] == warning: lines.pop(0)
    width = len(names) + 2
    if sampled:
        if len(lines)!=steps*(2*width+1): raise ValueError('missing sampled reference inputs/states')
        clean=[]
        for index in range(steps):
            offset=index*(2*width+1)
            if lines[offset]!=f'0x{index+1:08x}': raise ValueError('Spike sampled input acknowledgement mismatch')
            clean += lines[offset+1:offset+1+2*width]
        lines=clean
    elif masks is not None:
        if len(lines)!=(steps+1)*width+steps: raise ValueError('missing IRQ device acknowledgements/snapshots')
        clean=lines[:width]
        position=width
        for mask in masks:
            if lines[position]!=f'0x{irq_index(mask):08x}': raise ValueError('Spike IRQ pin acknowledgement mismatch')
            clean += lines[position+1:position+1+width]
            position+=width+1
        lines=clean
    if len(lines) != (steps*2 if sampled else steps+1)*width:
        raise ValueError('missing/extra Spike debugger state observations')
    states = []
    for offset in range(0, len(lines), width):
        values = lines[offset:offset+width]
        if values[1] not in ('M', 'U') or any(not re.fullmatch('0x[0-9a-f]{8}', s) for s in values[:1]+values[2:]):
            raise ValueError('unrecognized Spike debugger state format')
        states.append(dict(pc=int(values[0], 16), mode=3 if values[1]=='M' else 0,
                           csrs={name:int(value,16) for name,value in zip(names, values[2:])}))
    for state in states:
        for name in ('mcycle','minstret'):
            state['csrs'][name] |= state['csrs'][name+'h'] << 32
    return list(zip(states[::2],states[1::2])) if sampled else states


def attach_snapshots(commits, states):
    sampled=bool(states and isinstance(states[0],tuple))
    if len(states) != len(commits)+(0 if sampled else 1):
        raise ValueError('Spike instruction/trap count differs from debugger steps')
    for index, row in enumerate(commits):
        before, after = states[index] if sampled else states[index:index+2]
        if row['pc'] != before['pc'] or row['mode'] not in (None, before['mode']):
            raise ValueError('Spike event and debugger pre-state disagree')
        row.update(mode=before['mode'], before=before, after=after)
    return commits


def memory_operation(insn):
    """Access direction/width, independent of the DUT's RVFI masks."""
    if insn & 3 == 3:
        opcode, funct3 = insn & 127, insn >> 12 & 7
        if opcode in (3, 35):
            sizes = {0: 1, 1: 2, 2: 4, 4: 1, 5: 2} if opcode == 3 else {0: 1, 1: 2, 2: 4}
            if funct3 not in sizes: raise ValueError('unsupported memory instruction')
            return ('load' if opcode == 3 else 'store'), sizes[funct3]
    else:
        quadrant, funct3 = insn & 3, insn >> 13 & 7
        if quadrant in (0, 2) and funct3 in (2, 6):
            return ('load' if funct3 == 2 else 'store'), 4
    return None, 0


def source_registers(insn):
    """Architectural source addresses, decoded independently of the DUT."""
    floating = fp_operation(insn)
    if floating:
        return floating['sources'][:2]
    if insn & 3 == 3:
        op, rs1, rs2 = insn & 127, insn >> 15 & 31, insn >> 20 & 31
        if op in (0x33, 0x63, 0x23): return rs1, rs2
        if op in (0x03, 0x13, 0x67): return rs1, 0
        if op == 0x73 and insn >> 12 & 7 in (1, 2, 3): return rs1, 0
        return 0, 0
    q, f = insn & 3, insn >> 13 & 7
    rd, rs2, compact = insn >> 7 & 31, insn >> 2 & 31, 8 + (insn >> 7 & 7)
    if q == 0:
        if f == 0: return 2, 0
        if f == 2: return compact, 0
        if f == 6: return compact, 8 + (insn >> 2 & 7)
    if q == 1:
        if f == 0: return rd, 0
        if f == 3 and rd == 2: return 2, 0
        if f in (6, 7): return compact, 0
        if f == 4:
            return compact, (8 + (insn >> 2 & 7)) if insn >> 10 & 3 == 3 else 0
    if q == 2:
        if f == 0: return rd, 0
        if f == 2: return 2, 0
        if f == 6: return 2, rs2
        if f == 4:
            if not rs2: return rd, 0  # JR/JALR
            return (rd if insn >> 12 & 1 else 0), rs2  # ADD/MV
    return 0, 0


def validate_profile(records, config, image):
    if config.get('HART_ID',0)>0x7fffffff:
        raise ValueError('Pinned Spike --hartids parser accepts signed 32-bit IDs only; use native checking for HART_ID above 0x7fffffff')
    if any(config.get(k, 0) for k in ('ISA_PMP', 'ISA_F', 'ISA_A', 'XIF', 'DEBUG', 'MUA_HARDENED')):
        raise ValueError('Spike profile supports native RV32I/E/M/C/Zfinx without PMP, full F, atomics, XIF or debug')
    if image.symbols.get('fromhost') is not None:
        raise ValueError('initial Spike profile requires tohost-only ELF, without host-service fromhost')
    if any(s.address < RAM_BASE or s.address + s.size > RAM_BASE + RAM_SIZE for s in image.segments):
        raise ValueError('initial Spike profile requires ELF segments in the native 64 KiB RAM')
    if sum(r['type'] == 'reset' for r in records) != 1:
        raise ValueError('Spike differential ELF run requires exactly one reset epoch')
    instructions = []
    for record in records:
        if record['type'] == 'reset': continue
        if record['type'] == 'interrupt':
            if record.get('cause') not in (3,7,11): raise ValueError('unsupported interrupt cause')
            instructions.append(record)
            continue
        if record['rvfi_trap'] and record['cause'] not in TRAP_CAUSES.values():
            raise ValueError('unsupported synchronous trap cause in Spike profile')
        insn = record['rvfi_insn']
        desc = fp_operation(insn)
        if config.get('ISA_E',0) and desc and max(insn >> 7 & 31,*desc['sources'])>=16:
            raise ValueError('Pinned Spike lacks RV32E Zfinx high-register rejection; run these probes natively')
        if insn & 127 == 0x73:
            if insn not in (0x73, 0x100073, 0x30200073) and (not insn >> 12 & 7 or insn >> 20 not in (CSR_NAMES.keys() | FP_CSRS.keys())):
                raise ValueError(f'Spike profile rejects unsupported CSR or SYSTEM instruction {insn:#x}')
        instructions.append(record)
    if not instructions: raise ValueError('no RVFI instructions to compare')
    return instructions


def compare(instructions, commits, image, *, zfinx=False, fp_records=None, hart_id=0):
    """Compare every RVFI event, plus one Spike lookahead for the last next PC."""
    def equal(index, field, expected, actual):
        if expected != actual: raise Mismatch(index, field, expected, actual)

    names = dict(CSR_NAMES)
    if zfinx:
        names.update(FP_CSRS)
        if fp_records is None:
            raise ValueError('Zfinx comparison requires the actual EX operand companion')
    fp_seen = set()
    equal(-1, 'commit_count', len(instructions) + 6, len(commits))
    for index, insn in enumerate(BOOT_INSNS):
        equal(-1, 'bootstrap', (0x1000 + 4*index, insn, 3, hart_id),
              tuple(commits[index][k] for k in ('pc', 'insn', 'mode', 'hart')))
    equal(-1, 'entry', image.entry, commits[5]['pc'])
    memory, regs = image.memory(), [0] + [None]*31
    csr_state = {name: (hart_id if name == 'mhartid' else 0) for name in CSR_NAMES.values()}
    handler_entry, breakpoint_mtval = False, False
    for index, actual in enumerate(instructions):
        reference, following = commits[index+5:index+7]
        if actual['type']=='interrupt':
            equal(index,'interrupt_event',True,bool(reference.get('interrupt')))
            equal(index,'interrupt_pc',reference['pc'],actual['pc'])
            equal(index,'interrupt_cause',reference['cause'],actual['cause'])
            equal(index,'interrupt_target',reference['after']['pc'],actual['target'])
            equal(index,'interrupt_handler_pc',reference['after']['pc'],following['pc'])
            before,after=reference['before']['csrs'],reference['after']['csrs']
            if zfinx:
                fp_channels(0,False,before,after,
                            {address:value for address,value in reference['csrs'].items() if address in FP_CSRS})
            equal(index,'interrupt_priority',pending_interrupt(reference['mode']==3,before['mstatus'],before['mie'],reference['irq_mask']),reference['cause'])
            equal(index,'interrupt_vector',(before['mtvec'] & ~3)+(4*reference['cause'] if before['mtvec']&1 else 0),actual['target'])
            equal(index,'interrupt_privilege',3,reference['after']['mode'])
            for name,value in (('mepc',actual['pc']),('mcause',0x80000000|reference['cause']),('mtval',0)):
                equal(index,'interrupt_snapshot:'+name,value,after[name])
            equal(index,'interrupt_effects',({},[]),(reference['registers'],reference['memory']))
            channels={'mstatus':(MASK,MASK),'mtvec':(MASK,0),'mepc':(0,MASK),'mcause':(0,MASK),'mtval':(0,MASK)}
            equal(index,'interrupt_csr_channels',set(channels),set(actual['csrs']))
            for name,(read,write) in channels.items():
                channel=actual['csrs'][name]
                equal(index,'interrupt_csr_masks:'+name,(read,write),(channel['rmask'],channel['wmask']))
                mask=MSTATUS_MASK if name=='mstatus' else MASK
                if read: equal(index,'interrupt_csr_read:'+name,before[name]&mask,channel['rdata'])
                if write: equal(index,'interrupt_csr_write:'+name,after[name]&mask,channel['wdata'])
            handler_entry,breakpoint_mtval=True,False
            continue
        equal(index,'unexpected_interrupt',False,bool(reference.get('interrupt')))
        trapped = bool(reference.get('trap'))
        for name, rvfi in (('pc', 'pc_rdata'), ('insn', 'insn'), ('mode', 'mode')):
            equal(index, name, reference[name], actual['rvfi_' + rvfi])
        equal(index, 'hart', hart_id, reference['hart'])
        equal(index, 'trap', int(trapped), actual['rvfi_trap'])
        equal(index, 'handler_entry', int(handler_entry), actual['rvfi_intr'])
        handler_entry = trapped
        equal(index, 'next_pc', following['pc'], actual['rvfi_pc_wdata'])
        if 'after' in reference:
            equal(index, 'snapshot_next_pc', reference['after']['pc'], following['pc'])
            equal(index, 'next_privilege', reference['after']['mode'], following['mode'])
        sources = source_registers(reference['insn'])
        if trapped and reference['cause'] == 2 and reference['insn'] & 127 != 0x73:
            sources = 0, 0
        equal(index, 'source_registers', sources,
              (actual['rvfi_rs1_addr'], actual['rvfi_rs2_addr']))
        for source in ('rs1', 'rs2'):
            address = actual['rvfi_' + source + '_addr']
            if regs[address] is None:
                raise ValueError(f'RVFI source x{address} is uninitialized at instruction {index}')
            equal(index, source + '_value', regs[address], actual['rvfi_' + source + '_rdata'])
        writes = {actual['rvfi_rd_addr']: actual['rvfi_rd_wdata']} if actual['rvfi_rd_addr'] else {}
        equal(index, 'gpr_write', reference['registers'], writes)
        regs_updates = reference['registers']
        insn = reference['insn']
        effects = dict(reference['csrs'])
        floating_effects = {address:effects.pop(address) for address in tuple(effects) if address in FP_CSRS}
        if floating_effects and not zfinx:
            raise ValueError('FP CSR effects with Zfinx disabled')
        if insn == 0x30200073 and not trapped:
            # This qualified Spike build additionally logs two model-only CSRs
            # on MRET. They have no counterpart in the native profile and must
            # remain zero; all architectural native state is sampled directly.
            for address in (0x310, 0x7a5):
                if address in effects and effects.pop(address) != 0:
                    raise ValueError('nonzero model-only MRET CSR effect')
        expected_csrs = {names[a]: (value & (MSTATUS_MASK if a==0x300 else MASK)) <<
                         (32 if a in COUNTERS and a & 0x80 else 0)
                         for a, value in effects.items() if a in names}
        if len(expected_csrs) != len(effects): raise ValueError('unsupported Spike CSR effect')
        actual_csrs = {name: value['wdata'] & value['wmask'] for name, value in actual['csrs'].items() if value['wmask']}
        before = dict(csr_state, **reference.get('before', {}).get('csrs', {}))
        after = reference.get('after', {}).get('csrs')
        if trapped:
            if after is None: raise ValueError('trap comparison requires independent Spike state snapshots')
            equal(index, 'trap_cause', reference['cause'], actual['cause'])
            value = reference['tval']
            breakpoint_mtval = reference['cause'] == 3
            if breakpoint_mtval:
                if value not in (0, reference['pc']): raise ValueError('unexpected Spike breakpoint mtval policy')
                value = 0  # Native documented breakpoint mtval choice.
            equal(index, 'trap_tval', value, actual['tval'])
            equal(index, 'trap_saved_pc', reference['pc'], after['mepc'])
            equal(index, 'trap_snapshot_cause', reference['cause'], after['mcause'])
            equal(index, 'trap_snapshot_tval', reference['tval'], after['mtval'])
            equal(index, 'trap_target', before['mtvec'] & ~3, following['pc'])
            equal(index, 'trap_privilege', 3, reference['after']['mode'])
            expected_csrs = {name: (value if name=='mtval' else after[name] & (MSTATUS_MASK if name=='mstatus' else MASK))
                             for name in ('mstatus', 'mepc', 'mcause', 'mtval')}
            channels = {'mstatus':(MASK,MASK), 'mtvec':(MASK,0),
                        'mepc':(0,MASK), 'mcause':(0,MASK), 'mtval':(0,MASK)}
        elif insn == 0x30200073:
            if after is None: raise ValueError('MRET comparison requires independent Spike state snapshots')
            equal(index, 'mret_target', before['mepc'], following['pc'])
            channels = {'mstatus':(MASK,MASK), 'mepc':(MASK,0)}
            equal(index, 'mret_status_effect', after['mstatus'] & MSTATUS_MASK, expected_csrs.get('mstatus'))
        elif insn & 127 == 0x73:
            address, function, source, dest = insn >> 20, insn >> 12 & 7, insn >> 15 & 31, insn >> 7 & 31
            if address not in names: raise ValueError('unsupported reference CSR')
            name = names[address]
            read = dest != 0 if function in (1, 5) else True
            write = function in (1, 5) or source != 0
            if name=='mtval' and breakpoint_mtval and read and before['mtval'] != 0:
                raise ValueError('clear mtval before reading after breakpoint: native/Spike permitted values differ')
            if name=='mtval' and write: breakpoint_mtval = False
            shift = 32 if address in COUNTERS and address & 0x80 else 0
            mask = MASK << shift
            channels = {name:(mask if read else 0, mask if write else 0)} if read or write else {}
            if write and name in ('mcycle','minstret') and after is not None:
                equal(index, 'counter_preserved_half:'+name, after[name], actual['csrs'][name]['wdata'])
        else:
            channels = {}
        if zfinx:
            floating_channels = fp_channels(insn, trapped, before, after, floating_effects)
            channels.update(floating_channels)
            expected_csrs.update({name:after[name] & write for name,(_,write) in floating_channels.items() if write})
            desc = fp_operation(insn)
            if desc and not trapped:
                key = actual['epoch'],actual['rvfi_order']
                fp_seen.add(key)
                if key not in fp_records:
                    raise ValueError(f'missing FP companion at instruction {index}')
                observed = fp_records[key]
                equal(index,'fp_identity',(actual['rvfi_pc_rdata'],insn),(observed['pc'],observed['insn']))
                address = desc['sources'][2]
                if regs[address] is None:
                    raise ValueError('uninitialized third FP source')
                equal(index,'fp_rs3_addr',address,observed['rs3_addr'])
                equal(index,'fp_rs3_value',regs[address],observed['rs3_rdata'])
                rounding = desc['rounding']
                if rounding is not None:
                    effective = before['frm'] if rounding==7 else rounding
                    equal(index,'fp_effective_rm',effective,observed['rm'])
        equal(index, 'csr_write', expected_csrs, actual_csrs)
        equal(index, 'csr_channels', set(channels), set(actual['csrs']))
        for name, (read, write) in channels.items():
            channel = actual['csrs'][name]
            equal(index, 'csr_rmask:'+name, read, channel['rmask'])
            equal(index, 'csr_wmask:'+name, write, channel['wmask'])
            if read:
                value = before[name] & (MSTATUS_MASK if name=='mstatus' else (1<<64)-1 if name in ('mcycle','minstret') else MASK)
                equal(index, 'csr_read:'+name, value, channel['rdata'])
            if zfinx and name in FP_CSRS.values() and write:
                equal(index, 'fp_csr_post:'+name, after[name], channel['wdata'])
        csr_state.update(expected_csrs)
        if trapped:
            equal(index, 'trap_memory_effects', [], reference['memory'])
            equal(index, 'trap_suppressed_effects', (0,0,0,0,0), tuple(actual['rvfi_'+k] for k in
                  ('rd_addr','rd_wdata','mem_rmask','mem_wmask','mem_fault')))
            equal(index, 'trap_fault_masks', (0,0), (actual['rvfi_mem_fault_rmask'],actual['rvfi_mem_fault_wmask']))
            if reference['cause'] in (4,6):
                equal(index, 'trap_memory_address', reference['tval'] & ~3, actual['rvfi_mem_addr'])
            continue
        direction, size = memory_operation(reference['insn'])
        accesses = reference['memory']
        equal(index, 'memory_count', int(direction is not None), len(accesses))
        if direction:
            access = accesses[0]
            address = access['address']
            if not RAM_BASE <= address <= RAM_BASE + RAM_SIZE - size:
                raise ValueError('Spike access outside native RAM')
            if address % size: raise ValueError('misaligned access outside initial Spike profile')
            offset = address & 3
            mask = ((1 << size)-1) << offset
            equal(index, 'memory_address', address & ~3, actual['rvfi_mem_addr'])
            equal(index, 'load_mask', mask if direction == 'load' else 0, actual['rvfi_mem_rmask'])
            equal(index, 'store_mask', mask if direction == 'store' else 0, actual['rvfi_mem_wmask'])
            if direction == 'store':
                equal(index, 'store_size', size, access['size'])
                value = access['value']
            else:
                equal(index, 'load_effect', None, access['value'])
                value = sum(memory.get(address+n, 0) << (8*n) for n in range(size))
            bits = ((1 << (8*size))-1) << (8*offset)
            equal(index, direction + '_data', value << (8*offset),
                  actual['rvfi_mem_' + ('rdata' if direction == 'load' else 'wdata')] & bits)
            if direction == 'store':
                for n in range(size): memory[address+n] = value >> (8*n) & 255
        else:
            equal(index, 'memory_masks', (0, 0), (actual['rvfi_mem_rmask'], actual['rvfi_mem_wmask']))
        for address, value in regs_updates.items(): regs[address] = value
    if zfinx:
        equal(-1,'fp_companion_events',fp_seen,set(fp_records))
    return len(instructions)


def check_run(directory, config, info, timeout=30):
    """Preserve raw log, process diagnostics and first-mismatch evidence."""
    directory = Path(directory)
    result = dict(status='running', profile=info['profile'], tool=info,
                  policy='Native clock/retirement counters checked per edge; sampled counter/MIP inputs, independent Spike instruction semantics; aligned IRQ delivery; breakpoint mtval native=0, Spike=0|PC',
                  artifacts=['spike.log', 'spike-process.log', 'spike-debug.cmd', 'rvfi.jsonl'])
    try:
        zfinx = bool(config.get('ISA_ZFINX',0))
        hart_id = config['HART_ID']
        image = load_elf(directory / 'program.elf')
        records = read_trace(directory / 'rvfi.jsonl')
        instructions = validate_profile(records, config, image)
        plan=interrupt_plan(image,config)
        sampled=any(r['type']=='instruction' and r['rvfi_insn'] & 127==0x73 and
                    r['rvfi_insn'] >> 20 in SAMPLED_CSRS for r in instructions)
        audit=None
        masks=None
        if plan:
            audit=json.loads((directory/'interrupts.json').read_text())
            masks=[0]*5+replay_masks(records,audit,plan)+[0]
        elif any(r['type']=='interrupt' for r in instructions):
            raise ValueError('interrupt trace requires an ELF-bound stimulus plan')
        elif any(r['type']=='instruction' and r['rvfi_insn'] & 127==0x73 and
                 r['rvfi_insn'] >> 20 in (0x304,0x344) for r in instructions):
            # Isolate all three external inputs from Spike's default CLINT
            # when the program can enable them, even for a no-IRQ test.
            masks=[0]*(len(instructions)+6)
        if sampled:
            if audit is None:
                audit=json.loads((directory/'interrupts.json').read_text())
                replay_masks(records,audit,plan)
            timing=json.loads((directory/'timing.json').read_text())
            samples=replay_samples(records,timing,audit)
            masks=masks or [0]*(len(instructions)+6)
            inputs=[None]*5+samples+[None]
            (directory/'spike-inputs.txt').write_text(''.join(
                f'{int(sample is not None):x} {(sample or {}).get("mcycle",0):x} '
                f'{(sample or {}).get("minstret",0):x} {(sample or {}).get("mip",0):x} {mask:x}\n'
                for sample,mask in zip(inputs,masks)))
            result['artifacts'] += ['timing.json','interrupts.json','spike-inputs.txt']
            result['checked_counter_cycles']=timing['checked_cycles']
        march, _ = isa_abi(config)
        # This Spike build gates its counter aliases and inhibit mask on Zicntr.
        # Enable the reference facility; TIME remains rejected by our profile.
        march += '_zicntr'
        command = [info['executable'], '--isa=' + march,
                   '--priv=' + ('mu' if config['ISA_UMODE'] else 'm'), '--pmpregions=0',
                   f'--hartids={hart_id}', f'--pc={image.entry:#x}', f'-m{RAM_BASE:#x}:{RAM_SIZE:#x}',
                   '-d', '--debug-cmd=' + str(directory / 'spike-debug.cmd'), '-l', '--log-commits',
                   '--log=' + str(directory / 'spike.log'), str(directory / 'program.elf')]
        result['command'] = command
        if masks is not None:
            from spike_irq import build_device
            device=build_device(directory,info)
            command[-1:-1]=['--extlib='+str(device),'--device=uqu_irq'+
                           (','+str(directory/'spike-inputs.txt') if sampled else '')]
        steps = len(instructions)+6
        (directory / 'spike-debug.cmd').write_text(debug_commands(steps,masks,sampled,zfinx))
        result['elf_sha256'] = hashlib.sha256((directory / 'program.elf').read_bytes()).hexdigest()
        with (directory / 'spike-process.log').open('w') as output:
            process = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
        if process.returncode: raise ValueError(f'Spike exited with {process.returncode}; see spike-process.log')
        commits = parse_commits(directory / 'spike.log')
        commits = attach_snapshots(commits, read_snapshots(directory / 'spike-process.log', steps,masks,sampled,zfinx))
        if sampled:
            for row,sample in zip(commits[5:],samples):
                for name in ('mcycle','minstret','mip'):
                    if row['before']['csrs'][name] != sample[name]:
                        raise ValueError('Spike did not consume sampled input: '+name)
        if masks is not None:
            for row,mask in zip(commits,masks): row['irq_mask']=mask
        fp_records = read_fp_trace(directory/'fpu.jsonl') if zfinx else None
        if zfinx:
            result['artifacts'].append('fpu.jsonl')
        count = compare(instructions, commits, image, zfinx=zfinx, fp_records=fp_records, hart_id=hart_id)
        if zfinx:
            (directory/'zfinx-coverage.json').write_text(json.dumps(fp_coverage(instructions),indent=2)+'\n')
            result['artifacts'].append('zfinx-coverage.json')
        result.update(status='passed', compared_instructions=count-sum(r['type']=='interrupt' for r in instructions),
                      compared_events=count,
                      compared_traps=sum(r.get('rvfi_trap',0) for r in instructions),
                      compared_interrupts=sum(r['type']=='interrupt' for r in instructions),
                      compared_mrets=sum(r.get('rvfi_insn')==0x30200073 and not r['rvfi_trap'] for r in instructions),
                      compared_counter_accesses=sum(r['type']=='instruction' and r['rvfi_insn'] & 127==0x73 and r['rvfi_insn'] >> 20 in COUNTERS for r in instructions),
                      compared_fp_instructions=sum(not r.get('rvfi_trap') and fp_operation(r.get('rvfi_insn',0)) is not None for r in instructions),
                      compared_fp_csr_accesses=sum(r['type']=='instruction' and r['rvfi_insn'] & 127==0x73 and r['rvfi_insn'] >> 20 in FP_CSRS for r in instructions),
                      compared_mip_accesses=sum(r['type']=='instruction' and r['rvfi_insn'] & 127==0x73 and r['rvfi_insn'] >> 20==0x344 for r in instructions),
                      observed_modes=sorted({r['rvfi_mode'] for r in instructions if r['type']=='instruction'}))
    except BaseException as error:
        result.update(status='failed', detail=str(error))
        if isinstance(error, Mismatch):
            result['mismatch'] = error.observation
            index = error.observation['index']
            if 0 <= index < len(instructions): result['rvfi_observation'] = instructions[index]
            if 0 <= index + 5 < len(commits): result['spike_observation'] = commits[index + 5]
        raise
    finally:
        (directory / 'spike.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
