"""Independent expectations for the deliberately small verification custom ISA."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from xif_model import custom,result


class CustomOracleTests(unittest.TestCase):
    def setUp(self):
        self.params=dict(ISA_E=0,XIF_NUM_RS=3,XIF_DUALWRITE=1)

    @staticmethod
    def insn(rd=6,a=1,b=2,op=0): return b << 20 | a << 15 | op << 12 | rd << 7 | 0x0b

    def test_scalar_ternary_pair_and_no_register_results(self):
        for op,used,writes,values in ((0,3,1,(4,0)),(1,7,1,(15,0)),
                (2,0,0,(0,0)),(3,3,3,(4,0xfffffff8)),(4,1,1,(0xfffffffe,0)),(5,4,1,(11,0))):
            desc=custom(self.insn(op=op),self.params)
            self.assertEqual((desc['used'],desc['writes']),(used,writes))
            self.assertEqual(result(desc,(0xfffffffe,6,11)),values)

    def test_configuration_and_used_register_ranges(self):
        for insn,changes in ((self.insn(op=1),dict(XIF_NUM_RS=2)),
                (self.insn(op=3),dict(XIF_DUALWRITE=0)),(self.insn(rd=7,op=3),{}),
                (self.insn(rd=16),dict(ISA_E=1)),(self.insn(a=31),dict(ISA_E=1)),
                (self.insn(op=6),{}),(0x5b,{})):
            self.assertIsNone(custom(insn,dict(self.params,**changes)))
        e=dict(self.params,ISA_E=1)
        self.assertIsNotNone(custom(self.insn(rd=31,a=31,b=31,op=2),e))
        self.assertIsNotNone(custom(self.insn(b=31,op=4),e))
        self.assertIsNotNone(custom(self.insn(rd=14,op=3),e))
        self.assertIsNotNone(custom(self.insn(rd=0,op=3),e))
