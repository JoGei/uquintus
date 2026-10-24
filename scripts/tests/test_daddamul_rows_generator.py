"""The EX/MEM cut must preserve the unsplit partial-product/Dadda product exactly."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gen_daddamul
import gen_daddamul_rows as gen

ROOT = Path(__file__).resolve().parents[2]
YOSYS = shutil.which(os.environ.get('YOSYS', 'yosys'))


class DaddaRowsTests(unittest.TestCase):
    def test_checked_in_rows_match_generator(self):
        self.assertEqual(gen.OUTPUT.read_text(), gen.generate())

    def test_canonical_reducer_definitions_are_unchanged(self):
        candidate = gen.generate().split('\nendmodule\n',1)[1].replace('uqu_daddamul_rows','uqu_daddamul')
        reference = gen_daddamul.generate().split('\nendmodule\n',1)[1]
        self.assertEqual(candidate,reference)

    @unittest.skipUnless(YOSYS, 'Yosys required for combinational equivalence')
    def test_reconstructed_product_matches_unsplit_for_all_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'proof.v'
            p.write_text('module proof(input [31:0] a,b, input sa,sb, output ok);\n'
                'wire [63:0] expected, actual, ra, rb;\n'
                'uqu_daddamul ref_mul(.a_i(a),.b_i(b),.signed_a_i(sa),.signed_b_i(sb),.product_o(expected));\n'
                'uqu_daddamul_rows rows(.a_i(a),.b_i(b),.signed_a_i(sa),.signed_b_i(sb),.row_a_o(ra),.row_b_o(rb));\n'
                'uqu_mul_finish lo(.row_a_i(ra),.row_b_i(rb),.high_i(1\'b0),.accumulate_i(1\'b0),.addend_i(32\'d0),.result_o(actual[31:0]));\n'
                'uqu_mul_finish hi(.row_a_i(ra),.row_b_i(rb),.high_i(1\'b1),.accumulate_i(1\'b0),.addend_i(32\'d0),.result_o(actual[63:32]));\n'
                'assign ok=expected==actual; endmodule\n')
            rtl=ROOT/'src/uquintus'
            script=(f'read_verilog "{rtl}/uqu_daddamul.v" "{rtl}/uqu_daddamul_rows.v" '
                    f'"{rtl}/uqu_mul_finish.v" "{p}"; prep -top proof -flatten; '
                    'opt -full; check -assert; sat -verify -prove ok 1 -show-inputs')
            result=subprocess.run([YOSYS,'-p',script],text=True,stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout)
            self.assertIn('SUCCESS',result.stdout)
