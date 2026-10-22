"""Reject corrupted timing evidence and compare sampled CSR results strictly."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from timing import check_counters, replay_samples
from test_rvfi_trace import instruction
import test_spike
import spike


class TimingTests(unittest.TestCase):
    def fixture(self):
        records=[dict(type='reset'), instruction(0,0x80000000), instruction(1,0x80000004)]
        first=dict(mcycle=2,minstret=0,mcountinhibit=0)
        middle=dict(mcycle=3,minstret=1,mcountinhibit=0)
        second=dict(mcycle=4,minstret=1,mcountinhibit=0)
        final=dict(mcycle=5,minstret=2,mcountinhibit=0)
        audit=dict(schema_version=1,status='passed',reset_cycle=1,checked_cycles=5,events=[
            dict(index=0,cycle=4,type='instruction',pc=0x80000000,before=first,after=middle,mip=0),
            dict(index=1,cycle=6,type='instruction',pc=0x80000004,before=second,after=final,mip=0)])
        return records,audit

    def test_clock_gaps_retirement_and_evidence_corruption(self):
        records,audit=self.fixture()
        samples=replay_samples(records,audit,{})
        self.assertEqual(samples[1]['mcycle'],4)
        for path,value in ((('events',0,'before','mcycle'),3),
                (('events',0,'after','minstret'),0),(('events',1,'cycle'),4),
                (('events',0,'mip'),8),(('events',1,'pc'),0),
                (('status',),'failed'),(('checked_cycles',),6),
                (('events',1,'after','mcountinhibit'),5)):
            broken=deepcopy(audit); target=broken
            for key in path[:-1]: target=target[key]
            target[path[-1]]=value
            with self.subTest(path=path),self.assertRaises(ValueError): replay_samples(records,broken,{})
        with self.assertRaises(AssertionError): check_counters(samples[0],dict(samples[0],mcycle=7))

    def test_inhibit_and_half_write_override(self):
        records,audit=self.fixture()
        records[1]['rvfi_insn']=0x3202d073  # CSRWI mcountinhibit,5
        audit['events'][0]['after']['mcountinhibit']=5
        records[2].update(rvfi_insn=0xb8029073,rvfi_rs1_addr=5,rvfi_rs1_rdata=0xffffffff)
        audit['events'][1].update(before=dict(mcycle=3,minstret=1,mcountinhibit=5),
            after=dict(mcycle=0xffffffff00000003,minstret=1,mcountinhibit=5))
        samples=replay_samples(records,audit,{})
        self.assertEqual(samples[1]['mcycle'],3)
        audit['events'][1]['after']['mcycle']+=1
        with self.assertRaisesRegex(ValueError,'post-state'): replay_samples(records,audit,{})

    def test_mip_read_can_see_pending_source_before_delivery(self):
        records,audit=self.fixture()
        records[2]=dict(type='interrupt',pc=0x80000004,cause=3)
        audit['events'][1]['type']='interrupt'
        audit['events'][1]['after']['minstret']=1
        for row in audit['events']: row['mip']=8
        irq=dict(assertions=[dict(cycle=3,mask=8)],entries=[dict(cycle=6,cause=3)])
        self.assertEqual([s['mip'] for s in replay_samples(records,audit,irq)],[8,8])
        audit['events'][0]['mip']=0
        with self.assertRaisesRegex(ValueError,'MIP'): replay_samples(records,audit,irq)

    def test_samples_do_not_take_values_from_rvfi_destination(self):
        records,audit=self.fixture()
        records[1].update(rvfi_insn=0xc00022f3,rvfi_rd_addr=5,rvfi_rd_wdata=2)
        first=replay_samples(records,audit,{})
        records[1]['rvfi_rd_wdata']=99
        self.assertEqual(replay_samples(records,audit,{}),first)

    def test_reference_checks_full_counter_read_write_halves_and_preservation(self):
        fixture=test_spike.SpikeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        pc=fixture.image.entry
        insn=0xb800d173  # CSRRWI x2,mcycleh,1
        before=dict.fromkeys(spike.SNAPSHOT_CSRS,0)
        before['mcycle']=0x200000003
        after=dict(before,mcycle=0x100000003)
        row=instruction(0,pc,insn=insn,rd_addr=2,rd_wdata=2)
        row['csrs']=dict(mcycle=dict(rmask=spike.MASK<<32,wmask=spike.MASK<<32,
                                    rdata=before['mcycle'],wdata=after['mcycle']))
        refs=[fixture.commit(0x1000+4*n,op) for n,op in enumerate(spike.BOOT_INSNS)]
        ref=fixture.commit(pc,insn,{2:2},csrs={0xb80:1})
        ref.update(before=dict(pc=pc,mode=3,csrs=before),after=dict(pc=pc+4,mode=3,csrs=after))
        refs += [ref,fixture.commit(pc+4,0x13)]
        self.assertEqual(spike.compare([row],refs,fixture.image),1)
        for path,value in ((('rvfi_rd_wdata',),99),(('csrs','mcycle','rdata'),0),
                (('csrs','mcycle','wdata'),0x100000004),(('csrs','mcycle','wmask'),spike.MASK)):
            broken=deepcopy(row);target=broken
            for key in path[:-1]: target=target[key]
            target[path[-1]]=value
            with self.subTest(path=path),self.assertRaises(spike.Mismatch): spike.compare([broken],refs,fixture.image)

    def test_sampled_debugger_states_acknowledgements_and_counter_width(self):
        fixture=test_spike.SpikeTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        values=dict.fromkeys(spike.SNAPSHOT_CSRS,0)
        values.update(mcycle=3,mcycleh=2)
        state='0x80000000\nM\n'+''.join(f'0x{v:08x}\n' for v in values.values())
        path=fixture.path/'samples.log'
        path.write_text('0x00000001\n'+state+state)
        states=spike.read_snapshots(path,1,sampled=True)
        self.assertEqual(states[0][0]['csrs']['mcycle'],0x200000003)
        path.write_text('0x00000002\n'+state+state)
        with self.assertRaisesRegex(ValueError,'acknowledgement'): spike.read_snapshots(path,1,sampled=True)
        self.assertEqual(spike.debug_commands(1,sampled=True).splitlines()[0],'mem 50000100')

    def test_failed_clock_evidence_fails_reference_and_junit_before_execution(self):
        fixture=test_spike.SpikeTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        path=fixture.path
        (path/'program.elf').write_bytes(b'ELF')
        (path/'results.xml').write_text('<testsuites><testsuite><testcase name="execute"/></testsuite></testsuites>')
        (path/'interrupts.json').write_text(json.dumps(dict(schema_version=1,plan=[],
            assertions=[],entries=[],completed=True)))
        (path/'timing.json').write_text(json.dumps(dict(status='failed')))
        rows=[dict(type='reset'),instruction(0,fixture.image.entry,insn=0xc00022f3)]
        with patch.object(spike,'load_elf',return_value=fixture.image), \
             patch.object(spike,'read_trace',return_value=rows), \
             patch.object(spike.subprocess,'run') as process:
            with self.assertRaisesRegex(ValueError,'clock counter evidence'):
                test_spike.check_reference(path,fixture.config,dict(profile='test',executable='/external/spike'))
            process.assert_not_called()
        self.assertEqual(json.loads((path/'spike.json').read_text())['status'],'failed')
        with self.assertRaisesRegex(RuntimeError,'failed or skipped'):
            test_spike.check_results(path/'results.xml',['execute'])
