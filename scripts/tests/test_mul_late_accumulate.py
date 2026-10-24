"""All-input proof of the late-C layer; product generation is proved separately."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
YOSYS = shutil.which(os.environ.get('YOSYS', 'yosys'))


class LateAccumulateTests(unittest.TestCase):
    @unittest.skipUnless(YOSYS, 'Yosys is required for combinational SAT')
    def test_arbitrary_two_rows_and_addend(self):
        with tempfile.TemporaryDirectory() as tmp:
            top = Path(tmp)/'proof.v'
            top.write_text('''module proof(input [63:0] a,b,input [31:0] c,input en,output ok);
wire [63:0] actual;
wire [63:0] expected=a+b+(en?{32'd0,c}:64'd0);
uqu_mul_finish lo(.row_a_i(a),.row_b_i(b),.high_i(1'b0),.accumulate_i(en),.addend_i(c),.result_o(actual[31:0]));
uqu_mul_finish hi(.row_a_i(a),.row_b_i(b),.high_i(1'b1),.accumulate_i(en),.addend_i(c),.result_o(actual[63:32]));
assign ok=actual==expected; endmodule
''')
            result = subprocess.run([YOSYS, '-Q', '-p',
                f'read_verilog {ROOT}/src/uquintus/uqu_mul_finish.v {top}; prep -top proof -flatten; sat -verify -prove ok 1'],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(result.returncode, 0, result.stdout[-5000:])
            self.assertIn('SUCCESS', result.stdout)
