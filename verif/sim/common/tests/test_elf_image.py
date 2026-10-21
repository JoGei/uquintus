"""ELF file boundaries, program-image semantics, ABI checks and completion."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elf_image import completion_code, load_elf


def executable():
    """Two segments, a zero-fill tail, and a global tohost symbol; no compiler."""
    raw = bytearray(0x2a0)
    ident = b'\x7fELF\x01\x01\x01' + bytes(9)
    struct.pack_into('<16sHHIIIIIHHHHHH', raw, 0, ident, 2, 243, 1,
                     0x80000000, 52, 0x200, 0, 52, 32, 2, 40, 4, 0)
    struct.pack_into('<8I', raw, 52, 1, 0x100, 0x80000000, 0x80000000, 8, 8, 5, 4)
    struct.pack_into('<8I', raw, 84, 1, 0x110, 0x80001000, 0x80001000, 16, 24, 6, 4)
    raw[0x100:0x108] = b'\x13\0\0\0\x6f\0\0\0'
    raw[0x110:0x114] = b'\x78\x56\x34\x12'
    raw[0x180:0x188] = b'\0tohost\0'
    struct.pack_into('<IIIBBH', raw, 0x1b0, 1, 0x80001008, 8, 0x11, 0, 3)
    struct.pack_into('<10I', raw, 0x228, 0, 3, 0, 0, 0x180, 8, 0, 0, 1, 0)
    struct.pack_into('<10I', raw, 0x250, 0, 2, 0, 0, 0x1a0, 32, 1, 1, 4, 16)
    struct.pack_into('<10I', raw, 0x278, 0, 1, 3, 0x80001000, 0x110, 16, 0, 0, 8, 0)
    return raw


class ELFImageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'program.elf'

    def load(self, raw=None, **kwargs):
        self.path.write_bytes(executable() if raw is None else raw)
        return load_elf(self.path, **kwargs)

    def test_segments_zero_fill_symbols_and_independent_memory(self):
        image = self.load()
        self.assertEqual(image.entry, 0x80000000)
        self.assertEqual(image.tohost, 0x80001008)
        memory = image.memory()
        self.assertEqual(len(memory), 32)
        self.assertEqual(bytes(memory[a] for a in range(0x80001000, 0x80001004)), b'\x78\x56\x34\x12')
        self.assertEqual([memory[a] for a in range(0x80001010, 0x80001018)], [0] * 8)
        memory[0x80000000] = 0xff
        self.assertEqual(image.memory()[0x80000000], 0x13)

    def test_rejects_wrong_format_dynamic_abi_and_boot_alignment(self):
        mutations = [(4, b'\x02'), (5, b'\x02'), (16, struct.pack('<H', 1)),
                     (18, struct.pack('<H', 62)), (20, struct.pack('<I', 2)),
                     (24, struct.pack('<I', 0x80000002)), (36, struct.pack('<I', 4)),
                     (36, struct.pack('<I', 16)), (40, struct.pack('<H', 64)),
                     (42, struct.pack('<H', 56)), (52, struct.pack('<I', 2)),
                     (52, struct.pack('<I', 3)), (52, struct.pack('<I', 7))]
        for offset, value in mutations:
            with self.subTest(offset=offset, value=value):
                raw = executable()
                raw[offset:offset + len(value)] = value
                with self.assertRaises(ValueError):
                    self.load(raw)

    def test_truncation_and_segment_limits(self):
        for size in (0, 51, 100, 0x105, 0x190, 0x299):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.load(executable()[:size])
        for offset, value in ((52 + 16, 9), (52 + 12, 0),
                              (84 + 20, 0xffffffff), (84 + 28, 3),
                              (24, 0x90000000)):
            raw = executable()
            struct.pack_into('<I', raw, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.load(raw)
        raw = executable()
        struct.pack_into('<II', raw, 84 + 8, 0x80000004, 0x80000004)
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            self.load(raw)
        raw = executable()
        struct.pack_into('<I', raw, 84 + 20, 0x1000)
        with self.assertRaisesRegex(ValueError, 'memory image'):
            self.load(raw, max_bytes=1024)
        with self.assertRaisesRegex(ValueError, 'file exceeds'):
            self.load(max_bytes=100)

    def test_to_host_must_be_defined_writable_aligned_and_zero(self):
        for offset, value in ((0x1b0 + 4, 0x80001009), (0x1b0 + 4, 0x80001018),
                              (84 + 24, 4), (0x118, 1)):
            raw = executable()
            struct.pack_into('<I', raw, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.load(raw).tohost
        raw = executable()
        struct.pack_into('<H', raw, 0x1b0 + 14, 0)
        with self.assertRaisesRegex(ValueError, 'defined tohost'):
            self.load(raw).tohost

    def test_no_sections_can_load_but_not_complete(self):
        raw = executable()
        struct.pack_into('<H', raw, 48, 0)
        image = self.load(raw)
        self.assertEqual(len(image.memory()), 32)
        with self.assertRaisesRegex(ValueError, 'symbol table'):
            image.tohost

    def test_abi_configuration_compatibility(self):
        for flags in (0, 1, 8, 9):
            raw = executable()
            struct.pack_into('<I', raw, 36, flags)
            image = self.load(raw)
            for e in (0, 1):
                for c in (0, 1):
                    parameters = dict(ISA_E=e, ISA_C=c)
                    if bool(flags & 8) == bool(e) and (not flags & 1 or c):
                        image.validate_core(parameters)
                    else:
                        with self.assertRaises(ValueError):
                            image.validate_core(parameters)

    def test_bad_symbol_table_ranges_and_names(self):
        for offset, value in ((0x250 + 24, 10), (0x250 + 36, 8),
                              (0x1b0, 100), (0x228 + 16, 0xffffff00)):
            raw = executable()
            struct.pack_into('<I', raw, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.load(raw)

    def test_completion_protocol(self):
        self.assertIsNone(completion_code(0))
        self.assertEqual(completion_code(1), 0)
        self.assertEqual(completion_code(15), 7)
        self.assertEqual(completion_code(0xffffffff), 0x7fffffff)
        for value in (2, 0x100000001, -1):
            with self.assertRaisesRegex(ValueError, 'unsupported tohost'):
                completion_code(value)


if __name__ == '__main__':
    unittest.main()
