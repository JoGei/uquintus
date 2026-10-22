"""Independent IRQ policy, ELF stimuli, reference input replay and corruption."""
from copy import deepcopy
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from elf_image import ELFImage,Segment
from interrupts import (pending_interrupt,check_interrupt_cycle,interrupt_plan,
                        InterruptStimulus,replay_masks)
import spike
from spike_irq import build_device
import test_spike


class InterruptTests(unittest.TestCase):
    def test_priority_masking_and_lower_privilege(self):
        for priv,status,mie,lines,cause in ((True,8,0x888,0x888,11),(True,8,0x888,0x88,3),
                (True,8,0x888,0x80,7),(True,0,0x888,0x888,None),
                (True,8,8,128,None),(False,0,0x888,0x800,11)):
            self.assertEqual(pending_interrupt(priv,status,mie,lines),cause)

    def test_native_checker_rejects_early_missing_wrong_priority_and_admission(self):
        observed=dict(ex_valid_q=0,mem_valid_q=0,wb_valid_q=0,trap_valid=1,trap_cause=11)
        args=dict(priv_m=True,mstatus=8,mie=0x888,lines=0x888,lsu_busy=False,de_fire=False)
        check_interrupt_cycle(observed,**args)
        for row,options in ((dict(observed,trap_cause=3),args),(dict(observed,ex_valid_q=1),args),
                (dict(observed,trap_valid=0),args),(observed,dict(args,mstatus=0)),
                (observed,dict(args,lsu_busy=True)),(observed,dict(args,de_fire=True))):
            with self.subTest(row=row,options=options),self.assertRaises(AssertionError):
                check_interrupt_cycle(row,**options)

    def test_elf_plan_validation(self):
        def image(words):
            data=struct.pack('<'+'I'*len(words),*words)
            return ELFImage(0x80000000,0,(Segment(0x80000000,b'\0'*32,32,5),
                Segment(0x80001000,data,len(data),4)),dict(uqu_interrupts=0x80001000,uqu_interrupts_end=0x80001000+len(data)))
        self.assertEqual(interrupt_plan(image([2,0x80000000,0x800,0])),[dict(kind=2,pc=0x80000000,mask=0x800)])
        for words in ([0,0x80000000,8,0],[1,0x80000000,1,0],[1,0x80000002,8,0],
                      [1,0x80000000,8,1],[1,0x80000000,8], [1,0x80000000,8,0]*2):
            with self.subTest(words=words),self.assertRaises(ValueError): interrupt_plan(image(words))
        with self.assertRaisesRegex(ValueError,'ISA_M'):
            interrupt_plan(image([3,0x80000000,8,0]),dict(ISA_M=0))

    def audit_fixture(self):
        plan=[dict(kind=1,pc=0x80000000,mask=0x888)]
        stimulus=InterruptStimulus(plan)
        stimulus.assert_next(10,1,dict(retired_pc=0x80000000))
        records=[dict(type='reset')]
        for index,cause in enumerate((11,3,7)):
            records += [dict(type='instruction'),dict(type='interrupt',pc=0x80000004+index*4,cause=cause)]
            stimulus.accept(0x80000004+index*4,cause,20+index*10,index+1)
        stimulus.finish()
        return plan,records,stimulus.evidence()

    def test_stimulus_acknowledges_only_selected_line_and_rejects_bad_evidence(self):
        plan,records,audit=self.audit_fixture()
        self.assertEqual(replay_masks(records,audit,plan),[0,0x888,0,0x88,0,0x80])
        for section,index,key,value in (('entries',0,'mask',0x800),('entries',0,'pc',0),
                ('entries',0,'cycle',1),('assertions',0,'pc',0),('assertions',0,'context',{})):
            broken=deepcopy(audit);broken[section][index][key]=value
            with self.subTest(key=key),self.assertRaises((ValueError,AssertionError)):
                replay_masks(records,broken,plan)
        stimulus=InterruptStimulus(plan)
        with self.assertRaises(AssertionError): stimulus.finish()
        stimulus.assert_next(0,0,{})
        with self.assertRaisesRegex(AssertionError,'order'):stimulus.accept(0,3,1,0)

    def test_reference_irq_has_no_instruction_record_and_checks_implicit_state(self):
        fixture=test_spike.SpikeTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        rows,refs=fixture.trap_fixture()
        ref=refs[5]
        ref.pop('trap');ref.update(interrupt=True,insn=None,irq_mask=0x888)
        for name in ('before','after'):
            ref[name]['csrs'].update(mie=0x888,mtvec=fixture.image.entry+32)
        ref['after']['csrs']['mcause']=0x8000000b
        row=dict(type='interrupt',epoch=0,pc=fixture.image.entry,cause=11,
                 target=fixture.image.entry+32,csrs=deepcopy(rows[0]['csrs']))
        row['csrs']['mcause']['wdata']=0x8000000b
        row['csrs']['mtvec'].update(rdata=fixture.image.entry+32,wdata=fixture.image.entry+32)
        actual=[row,rows[1]]
        self.assertEqual(spike.compare(actual,refs,fixture.image),2)
        for key,value in (('pc',0),('cause',3),('target',0)):
            broken=deepcopy(actual);broken[0][key]=value
            with self.subTest(key=key),self.assertRaises(spike.Mismatch):spike.compare(broken,refs,fixture.image)
        broken=deepcopy(actual);broken[0]['csrs']['mepc']['wdata']=0
        with self.assertRaises(spike.Mismatch):spike.compare(broken,refs,fixture.image)

    def test_reference_pin_acknowledgements_and_missing_sdk_fail_clearly(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'states'
            state='0x80000000\nM\n'+''.join('0x00000000\n' for _ in spike.SNAPSHOT_CSRS)
            path.write_text(state+'0x00000007\n'+state)
            self.assertEqual(len(spike.read_snapshots(path,1,[0x888])),2)
            with self.assertRaisesRegex(ValueError,'acknowledgement'):spike.read_snapshots(path,1,[8])
            with patch.dict(os.environ,dict(SPIKE_ROOT=temporary)):
                with self.assertRaisesRegex(ValueError,'headers'):build_device(Path(temporary),dict(resolved_executable='/external/spike'))
