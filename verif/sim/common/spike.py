"""Bounded external Spike execution and strict native RVFI differential checks.

This first profile deliberately rejects traps, interrupts, counters, PMP and
other implementation-dependent CSRs. It never skips an unsupported event.
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

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / 'verif/reference/spike.lock.json'
MASK = 0xffffffff
RAM_BASE, RAM_SIZE = 0x80000000, 0x10000
CSR_NAMES = {0x305: 'mtvec', 0x340: 'mscratch', 0x341: 'mepc',
             0x342: 'mcause', 0x343: 'mtval', 0xf14: 'mhartid'}
BOOT_INSNS = [0x297, 0x02028593, 0xf1402573, 0x0182a283, 0x00028067]


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
    for option in ('--log-commits', '--instructions=', '--pc=', '--hartids=', '--pmpregions='):
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
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        match = header.fullmatch(line)
        if not match:
            if disasm.fullmatch(line):
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
    """Architectural source addresses for the initial I/E/M/C profile."""
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
    if any(config.get(k, 0) for k in ('ISA_PMP', 'ISA_F', 'ISA_ZFINX', 'ISA_A', 'XIF', 'DEBUG', 'MUA_HARDENED')):
        raise ValueError('Spike initial profile supports native RV32I/E/M/C without PMP, FPU, XIF or debug')
    if image.symbols.get('fromhost') is not None:
        raise ValueError('initial Spike profile requires tohost-only ELF, without host-service fromhost')
    if any(s.address < RAM_BASE or s.address + s.size > RAM_BASE + RAM_SIZE for s in image.segments):
        raise ValueError('initial Spike profile requires ELF segments in the native 64 KiB RAM')
    if sum(r['type'] == 'reset' for r in records) != 1:
        raise ValueError('Spike differential ELF run requires exactly one reset epoch')
    instructions = []
    for record in records:
        if record['type'] == 'reset': continue
        if record['type'] != 'instruction' or record['rvfi_trap'] or record['rvfi_intr']:
            raise ValueError('Spike initial profile does not support traps or interrupt injection')
        insn = record['rvfi_insn']
        if insn & 127 == 0x73:
            if not insn >> 12 & 7 or insn >> 20 not in CSR_NAMES:
                raise ValueError(f'Spike initial profile rejects counter/implementation-dependent CSR or SYSTEM instruction {insn:#x}')
        instructions.append(record)
    if not instructions: raise ValueError('no RVFI instructions to compare')
    return instructions


def compare(instructions, commits, image):
    """Compare every RVFI event, plus one Spike lookahead for the last next PC."""
    def equal(index, field, expected, actual):
        if expected != actual: raise Mismatch(index, field, expected, actual)

    equal(-1, 'commit_count', len(instructions) + 6, len(commits))
    for index, insn in enumerate(BOOT_INSNS):
        equal(-1, 'bootstrap', (0x1000 + 4*index, insn, 3, 5),
              tuple(commits[index][k] for k in ('pc', 'insn', 'mode', 'hart')))
    equal(-1, 'entry', image.entry, commits[5]['pc'])
    memory, regs = image.memory(), [0] + [None]*31
    csr_state = {name: (5 if name == 'mhartid' else 0) for name in CSR_NAMES.values()}
    for index, actual in enumerate(instructions):
        reference, following = commits[index+5:index+7]
        for name, rvfi in (('pc', 'pc_rdata'), ('insn', 'insn'), ('mode', 'mode')):
            equal(index, name, reference[name], actual['rvfi_' + rvfi])
        equal(index, 'hart', 5, reference['hart'])
        equal(index, 'next_pc', following['pc'], actual['rvfi_pc_wdata'])
        equal(index, 'source_registers', source_registers(reference['insn']),
              (actual['rvfi_rs1_addr'], actual['rvfi_rs2_addr']))
        for source in ('rs1', 'rs2'):
            address = actual['rvfi_' + source + '_addr']
            if regs[address] is None:
                raise ValueError(f'RVFI source x{address} is uninitialized at instruction {index}')
            equal(index, source + '_value', regs[address], actual['rvfi_' + source + '_rdata'])
        writes = {actual['rvfi_rd_addr']: actual['rvfi_rd_wdata']} if actual['rvfi_rd_addr'] else {}
        equal(index, 'gpr_write', reference['registers'], writes)
        regs_updates = reference['registers']
        expected_csrs = {CSR_NAMES[a]: value for a, value in reference['csrs'].items() if a in CSR_NAMES}
        if len(expected_csrs) != len(reference['csrs']): raise ValueError('unsupported Spike CSR effect')
        actual_csrs = {name: value['wdata'] & value['wmask'] for name, value in actual['csrs'].items() if value['wmask']}
        equal(index, 'csr_write', expected_csrs, actual_csrs)
        insn = reference['insn']
        if insn & 127 == 0x73:
            address, function, source, dest = insn >> 20, insn >> 12 & 7, insn >> 15 & 31, insn >> 7 & 31
            if address not in CSR_NAMES: raise ValueError('unsupported reference CSR')
            name = CSR_NAMES[address]
            read = dest != 0 if function in (1, 5) else True
            write = function in (1, 5) or source != 0
            equal(index, 'csr_channels', {name} if read or write else set(), set(actual['csrs']))
            channel = actual['csrs'].get(name, {})
            equal(index, 'csr_rmask', MASK if read else 0, channel.get('rmask', 0))
            equal(index, 'csr_wmask', MASK if write else 0, channel.get('wmask', 0))
            if read: equal(index, 'csr_read', csr_state[name], channel['rdata'])
        else:
            equal(index, 'csr_channels', set(), set(actual['csrs']))
        csr_state.update(expected_csrs)
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
    return len(instructions)


def check_run(directory, config, info, timeout=30):
    """Preserve raw log, process diagnostics and first-mismatch evidence."""
    directory = Path(directory)
    result = dict(status='running', profile=info['profile'], tool=info,
                  policy='deterministic native RAM; no traps, interrupts or counter reads',
                  artifacts=['spike.log', 'spike-process.log', 'rvfi.jsonl'])
    try:
        image = load_elf(directory / 'program.elf')
        records = read_trace(directory / 'rvfi.jsonl')
        instructions = validate_profile(records, config, image)
        march, _ = isa_abi(config)
        command = [info['executable'], '--isa=' + march,
                   '--priv=' + ('mu' if config['ISA_UMODE'] else 'm'), '--pmpregions=0',
                   '--hartids=5', f'--pc={image.entry:#x}', f'-m{RAM_BASE:#x}:{RAM_SIZE:#x}',
                   f'--instructions={len(instructions)+6}', '-l', '--log-commits',
                   '--log=' + str(directory / 'spike.log'), str(directory / 'program.elf')]
        result['command'] = command
        result['elf_sha256'] = hashlib.sha256((directory / 'program.elf').read_bytes()).hexdigest()
        with (directory / 'spike-process.log').open('w') as output:
            process = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
        if process.returncode: raise ValueError(f'Spike exited with {process.returncode}; see spike-process.log')
        commits = parse_commits(directory / 'spike.log')
        count = compare(instructions, commits, image)
        result.update(status='passed', compared_instructions=count)
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
