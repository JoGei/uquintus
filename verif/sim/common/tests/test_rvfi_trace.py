"""Reject trace corruption before a software reference consumes the stream."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rvfi_trace import read_trace, RVFI_WIDTHS


def instruction(order=0, pc=0x1000, **updates):
    values = dict.fromkeys(RVFI_WIDTHS,0)
    values.update(order=order, insn=0x13, mode=3, ixl=1, pc_rdata=pc, pc_wdata=pc+4)
    values.update(updates)
    return dict(type='instruction',epoch=0,cause=0,tval=0,**{'rvfi_'+n:v for n,v in values.items()})


class TraceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'rvfi.jsonl'

    def parse(self, records):
        self.path.write_text(''.join(json.dumps(r)+'\n' for r in records))
        return read_trace(self.path)

    def test_irq_and_exception_handlers_and_reset(self):
        records = [dict(type='reset',epoch=0), instruction(),
            dict(type='interrupt',epoch=0,pc=0x1004,cause=11,target=0x202c),
            instruction(1,0x202c,intr=1), instruction(2,0x2030,trap=1,pc_wdata=0x3000),
            instruction(3,0x3000,intr=1), dict(type='reset',epoch=1),
            instruction() | dict(epoch=1)]
        self.assertEqual(self.parse(records),records)

    def test_duplicate_gap_and_missing_reset(self):
        for records in ([instruction()],
                        [dict(type='reset',epoch=0),instruction(),instruction(0,0x1004)],
                        [dict(type='reset',epoch=0),instruction(),instruction(2,0x1004)]):
            with self.subTest(records=records),self.assertRaises(ValueError):self.parse(records)

    def test_invalid_effects_and_widths(self):
        for updates in (dict(rd_wdata=1),dict(rs1_rdata=1),dict(trap=1,rd_addr=1),
                        dict(trap=1,mem_wmask=15),dict(mem_fault=1),dict(mem_fault_rmask=1),
                        dict(rd_addr=32),dict(order=-1),dict(insn=2**32),dict(trap=True),
                        dict(mem_rmask=1,mem_addr=1),dict(mem_rmask=1,mem_wmask=1)):
            with self.subTest(updates=updates),self.assertRaises(ValueError):
                self.parse([dict(type='reset',epoch=0),instruction(**updates)])

    def test_missing_handler_marker_and_pc_jump(self):
        for second in (instruction(1,0x1004,intr=1),instruction(1,0x2000)):
            with self.subTest(second=second),self.assertRaises(ValueError):
                self.parse([dict(type='reset',epoch=0),instruction(),second])

    def test_fault_masks_are_not_committed_memory(self):
        r = instruction(trap=1,mem_fault=1,mem_addr=0x4000,mem_fault_rmask=2)
        self.assertEqual(len(self.parse([dict(type='reset',epoch=0),r])),2)

    def test_bad_epoch_and_schema(self):
        for r in (dict(type='reset',epoch=1),dict(type='bogus',epoch=0),
                  dict(type='reset',epoch=0,extra=1)):
            with self.subTest(record=r),self.assertRaises(ValueError):self.parse([r])


if __name__=='__main__':
    unittest.main()
