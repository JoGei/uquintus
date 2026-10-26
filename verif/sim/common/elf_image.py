"""Small, strict loader for statically linked little-endian RISC-V ELF32 tests.

PT_LOAD segments, not section names, define the memory image. This environment
uses identity addressing; dynamic linking and distinct load/run addresses are
deliberately rejected. No simulator or third-party ELF package is required.
"""
from dataclasses import dataclass
from pathlib import Path
import struct


@dataclass(frozen=True)
class Segment:
    address: int
    data: bytes
    size: int
    flags: int


@dataclass(frozen=True)
class ELFImage:
    entry: int
    flags: int
    segments: tuple
    symbols: dict

    def memory(self):
        image = {}
        for segment in self.segments:
            image.update((segment.address + n, byte)
                         for n, byte in enumerate(segment.data))
            image.update((address, 0) for address in range(
                segment.address + len(segment.data), segment.address + segment.size))
        return image

    def validate_core(self, parameters):
        if self.flags & 1 and not parameters['ISA_C']:
            raise ValueError('ELF permits compressed instructions but ISA_C=0')
        if bool(self.flags & 8) != bool(parameters['ISA_E']):
            raise ValueError('ELF RV32E ABI flag does not match ISA_E')

    @property
    def tohost(self):
        address = self.symbols.get('tohost')
        if address is None:
            raise ValueError('ELF needs a defined tohost symbol; retain the symbol table')
        if address & 7:
            raise ValueError('tohost must be 8-byte aligned')
        if not any(s.flags & 2 and s.address <= address and
                   address + 8 <= s.address + s.size for s in self.segments):
            raise ValueError('tohost must occupy 8 bytes in a writable PT_LOAD segment')
        if any(self.memory_byte(address + n) for n in range(8)):
            raise ValueError('tohost must initially contain zero')
        return address

    def memory_byte(self, address):
        for segment in self.segments:
            offset = address - segment.address
            if 0 <= offset < segment.size:
                return segment.data[offset] if offset < len(segment.data) else 0
        raise ValueError(f'address outside ELF image: {address:#x}')


def load_elf(path, max_bytes=16 * 1024 * 1024):
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise ValueError('ELF file exceeds loader size limit')
    raw = path.read_bytes()

    def region(offset, size):
        if offset < 0 or size < 0 or offset + size > len(raw):
            raise ValueError('truncated ELF file or out-of-range table/segment')
        return raw[offset:offset + size]

    header = region(0, 52)
    if header[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('expected little-endian ELF32 version 1')
    (kind, machine, version, entry, phoff, shoff, flags, ehsize,
     phsize, phnum, shsize, shnum, shstr) = struct.unpack_from('<HHIIIIIHHHHHH', header, 16)
    if kind != 2 or machine != 243 or version != 1 or ehsize != 52:
        raise ValueError('expected statically linked RISC-V ET_EXEC ELF32')
    if flags & ~9:
        raise ValueError('unsupported ELF ABI flags (requires soft-float, no TSO/vendor flags)')
    if entry & 3:
        raise ValueError('ELF entry must be word-aligned for boot_addr_i')
    if phsize != 32 or not phnum or phnum == 0xffff:
        raise ValueError('ELF needs ordinary ELF32 program headers')
    region(phoff, phsize * phnum)
    segments = []
    total = 0
    for n in range(phnum):
        ptype, offset, address, physical, filesz, memsz, access, align = struct.unpack(
            '<8I', region(phoff + n * phsize, phsize))
        if ptype in (2, 3, 7):
            raise ValueError('dynamic linking, interpreters and TLS are unsupported')
        if ptype != 1:
            continue
        if filesz > memsz or address + memsz > 1 << 32:
            raise ValueError('invalid PT_LOAD size or RV32 address overflow')
        if physical != address:
            raise ValueError('PT_LOAD physical and virtual addresses must match')
        if align > 1 and (align & (align - 1) or (address - offset) % align):
            raise ValueError('invalid PT_LOAD alignment')
        data = region(offset, filesz)
        if not memsz:
            continue
        total += memsz
        if total > max_bytes:
            raise ValueError('PT_LOAD memory image exceeds loader size limit')
        if any(address < s.address + s.size and s.address < address + memsz for s in segments):
            raise ValueError('overlapping PT_LOAD segments are unsupported')
        segments.append(Segment(address, data, memsz, access))
    if not any(s.flags & 1 and s.address <= entry and entry + 4 <= s.address + s.size
               for s in segments):
        raise ValueError('ELF entry must lie inside an executable PT_LOAD segment')

    # Sections are used only for symbols; BSS loading above needs no sections.
    symbols = {}
    if shnum:
        if shsize != 40:
            raise ValueError('invalid ELF32 section-header size')
        region(shoff, shsize * shnum)
        sections = [struct.unpack('<10I', region(shoff + n * shsize, shsize))
                    for n in range(shnum)]
        for section in sections:
            if section[1] != 2:  # SHT_SYMTAB
                continue
            offset, size, link, entsize = section[4], section[5], section[6], section[9]
            if entsize != 16 or size % 16 or link >= shnum or sections[link][1] != 3:
                raise ValueError('invalid ELF symbol/string table')
            strings = region(sections[link][4], sections[link][5])
            table = region(offset, size)
            for pos in range(0, size, 16):
                name, value, _, info, _, index = struct.unpack_from('<IIIBBH', table, pos)
                if not index or info >> 4 not in (1, 2):  # Defined global/weak symbols only.
                    continue
                if name >= len(strings) or strings.find(b'\0', name) < 0:
                    raise ValueError('invalid ELF symbol name')
                label = strings[name:strings.index(0, name)].decode('utf-8', errors='strict')
                if label:
                    if label in symbols and symbols[label] != value:
                        raise ValueError(f'conflicting ELF symbol: {label}')
                    symbols[label] = value
    return ELFImage(entry, flags, tuple(segments), symbols)


def completion_code(value):
    """Zero waits, one passes, other odd words report a nonzero test exit code."""
    if value == 0:
        return None
    if not 0 < value <= 0xffffffff or not value & 1:
        raise ValueError(f'unsupported tohost value {value:#x}; host syscalls are not implemented')
    return value >> 1


def expected_traps(image):
    """Read optional ordered (PC, cause, tval) words embedded in the ELF.

    This contract is opt-in and bound to the copied ELF bytes, not a sidecar
    that could silently relax a previously built test.
    """
    start = image.symbols.get('uqu_expected_traps')
    end = image.symbols.get('uqu_expected_traps_end')
    if start is None and end is None:
        return []
    if start is None or end is None or start & 3 or not 0 < end-start <= 4096 or (end-start) % 12:
        raise ValueError('invalid uqu_expected_traps ELF table boundaries')
    raw = bytes(image.memory_byte(a) for a in range(start, end))
    result, sites = [], {}
    for pc, cause, tval in struct.iter_unpack('<III', raw):
        if cause not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 11):
            raise ValueError('unsupported declared synchronous trap cause')
        if pc & (1 if image.flags & 1 else 3) or not any(
                s.flags & 1 and s.address <= pc < s.address+s.size for s in image.segments):
            raise ValueError('expected trap PC must be an aligned executable ELF address')
        if pc in sites and sites[pc] != (cause, tval):
            raise ValueError('conflicting expected traps for the same PC')
        sites[pc] = cause, tval
        result.append((pc, cause, tval))
    return result


def validate_trap_sequence(expected, observed, complete=False):
    """Require the declared order/count, retaining strict no-trap defaults."""
    if len(observed) > len(expected) or observed != expected[:len(observed)]:
        raise ValueError(f'ELF traps differ from declaration: observed={observed}, expected={expected}')
    if complete and observed != expected:
        raise ValueError(f'missing declared ELF traps: observed={observed}, expected={expected}')
