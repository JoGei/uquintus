"""ELF-bound expectations cannot silently forgive missing/extra/reordered traps."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elf_image import ELFImage, Segment, expected_traps, validate_trap_sequence


class ELFTrapTests(unittest.TestCase):
    def image(self, rows, symbols=None, flags=0):
        data = struct.pack('<'+'I'*len(rows), *rows)
        return ELFImage(0x80000000, flags, (
            Segment(0x80000000, b'\x13\0\0\0'*4, 16, 5),
            Segment(0x80001000, data, len(data), 4)),
            symbols if symbols is not None else dict(uqu_expected_traps=0x80001000,
                uqu_expected_traps_end=0x80001000+len(data)))

    def test_default_strict_and_valid_ordered_table(self):
        self.assertEqual(expected_traps(self.image([], symbols={})), [])
        expected = [(0x80000000,11,0), (0x80000004,4,0x80001001)]
        self.assertEqual(expected_traps(self.image([v for row in expected for v in row])), expected)
        validate_trap_sequence(expected, expected[:1])
        validate_trap_sequence(expected, expected, complete=True)
        for observed, complete in (([],True),(expected[:1],True),(expected*2,False),
                                   (list(reversed(expected)),False), ([(0x80000000,3,0)],False)):
            with self.subTest(observed=observed), self.assertRaises(ValueError):
                validate_trap_sequence(expected, observed, complete)
        with self.assertRaises(ValueError): validate_trap_sequence([], expected)

    def test_rejects_malformed_boundaries_sites_causes_and_conflicts(self):
        for image in (self.image([0x80000000,11,0], dict(uqu_expected_traps=0x80001000)),
                      self.image([0x80000000,11]), self.image([0x80000002,11,0]),
                      self.image([0x80001000,11,0]), self.image([0x80000000,7,0]),
                      self.image([0x80000000,11,0,0x80000000,3,0])):
            with self.subTest(image=image), self.assertRaises(ValueError): expected_traps(image)
        self.assertEqual(expected_traps(self.image([0x80000002,2,0], flags=1)), [(0x80000002,2,0)])
