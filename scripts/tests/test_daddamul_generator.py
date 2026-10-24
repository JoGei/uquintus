"""Check generated structure and weighted-bit conservation against integers."""
import importlib.util
from pathlib import Path
import random
import sys
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'gen_daddamul.py'
SPEC = importlib.util.spec_from_file_location('uqu_dadda_generator', SOURCE)
gen = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gen
SPEC.loader.exec_module(gen)


def packed(columns, bits, width):
    return sum(bits.get(ref, 0) << (row*2*width+col)
               for col, values in enumerate(columns) for row, ref in enumerate(values))


def weighted(heap, rows, width):
    mask = (1 << (2*width))-1
    return sum((heap >> (2*width*r)) & mask for r in range(rows)) & mask


class DaddaProductOracle:
    def check_product(self, width, a, b, sa, sb, stages):
        bits = {f'pp[{width*i+j}]': ((a >> i & 1) & (b >> j & 1)) ^
                ((sa and i == width-1) ^ (sb and j == width-1))
                for i in range(width) for j in range(width)}
        bits.update(signed_a=int(sa), signed_b=int(sb))
        bits['(signed_a | signed_b)'] = int(sa or sb)
        heap = packed(gen.initial_columns(width), bits, width)
        aa = a - ((1 << width) if sa and a >> (width-1) else 0)
        bb = b - ((1 << width) if sb and b >> (width-1) else 0)
        expected = aa*bb & ((1 << (2*width))-1)
        self.assertEqual(weighted(heap, max(map(len, gen.initial_columns(width))), width), expected)
        for stage in stages:
            bits = {f'heap_i[{r*2*width+c}]': heap >> (r*2*width+c) & 1
                    for c, h in enumerate(stage.input_heights) for r in range(h)}
            for counter in stage.counters:
                value = sum(bits[ref] for ref in counter.inputs)
                bits[counter.sum], bits[counter.carry] = value & 1, value >> 1
            heap = packed(stage.output_columns, bits, width)
            self.assertEqual(weighted(heap, stage.target, width), expected)


class DaddaGeneratorTests(DaddaProductOracle, unittest.TestCase):
    def test_checked_in_verilog_matches_canonical_generator(self):
        self.assertEqual(gen.OUTPUT.read_text(), gen.generate())

    def test_schedule_has_no_same_pass_counter_dependencies_or_lost_dots(self):
        stages = gen.stages_for()
        self.assertEqual([s.target for s in stages], [28, 19, 13, 9, 6, 4, 3, 2])
        self.assertEqual([sum(s.output_heights) for s in stages],
                         [1010, 857, 665, 497, 350, 242, 185, 126])
        for stage in stages:
            used = []
            for counter in stage.counters:
                self.assertTrue(all(ref.startswith('heap_i[') for ref in counter.inputs))
                used.extend(counter.inputs)
            used.extend(ref for col in stage.output_columns for ref in col if ref.startswith('heap_i['))
            expected = [f'heap_i[{64*r+c}]' for c, h in enumerate(stage.input_heights) for r in range(h)]
            self.assertCountEqual(used, expected)
            self.assertEqual(len(used), len(set(used)))
            self.assertLessEqual(max(stage.output_heights), stage.target)

    def test_exhaustive_small_and_random_rv32_signed_products(self):
        for width in (2, 3, 4):
            stages = gen.stages_for(width)
            for a in range(1 << width):
                for b in range(1 << width):
                    for sa, sb in ((0, 0), (1, 0), (0, 1), (1, 1)):
                        self.check_product(width, a, b, sa, sb, stages)
        rng = random.Random(0xDADDA)
        stages = gen.stages_for()
        for _ in range(256):
            a, b = rng.getrandbits(32), rng.getrandbits(32)
            for sa, sb in ((0, 0), (1, 0), (0, 1), (1, 1)):
                self.check_product(32, a, b, sa, sb, stages)


if __name__ == '__main__':
    unittest.main()
