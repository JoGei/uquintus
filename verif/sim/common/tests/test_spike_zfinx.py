"""Independent ISA checker must reject wrong FP effects, masks and operands."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from spike import BOOT_INSNS, MASK, Mismatch, compare, validate_profile
from spike_zfinx import channels, operation, read_fp_trace, coverage
from elf_image import ELFImage, Segment
from test_rvfi_trace import instruction


class ZfinxReferenceTests(unittest.TestCase):
    def fixture(self, dynamic=False):
        pc=0x80000000
        self.image=ELFImage(pc,0,(Segment(pc,b'\0'*64,64,7),),{'tohost':pc+32})
        state=dict(mstatus=0x1800,misa=0x40100100,fflags=0,frm=4 if dynamic else 0,
                   fcsr=128 if dynamic else 0)
        def commit(address,insn,registers=None,csrs=None):
            return dict(hart=5,mode=3,pc=address,insn=insn,registers=registers or {},
                        csrs=csrs or {},memory=[],before=dict(pc=address,mode=3,csrs=dict(state)),
                        after=dict(pc=address+4,mode=3,csrs=dict(state)))
        refs=[commit(0x1000+4*i,insn) for i,insn in enumerate(BOOT_INSNS)]
        rows=[]
        for i,(insn,value) in enumerate(((0x3f8000b7,0x3f800000),(0x40000137,0x40000000),(0x404001b7,0x40400000))):
            rows.append(instruction(i,pc+4*i,insn=insn,rd_addr=i+1,rd_wdata=value))
            refs.append(commit(pc+4*i,insn,{i+1:value}))
        insn=(3<<27)|(2<<20)|(1<<15)|((7 if dynamic else 0)<<12)|(4<<7)|0x43
        row=instruction(3,pc+12,insn=insn,rs1_addr=1,rs1_rdata=0x3f800000,
                        rs2_addr=2,rs2_rdata=0x40000000,rd_addr=4,rd_wdata=0x40a00000)
        row['csrs']={name:dict(rmask=read,wmask=write,rdata=state[name],wdata=state[name])
                     for name,(read,write) in dict(fflags=(31,31),fcsr=(255 if dynamic else 31,31),
                                                  **({'frm':(7,0)} if dynamic else {})).items()}
        rows.append(row)
        refs += [commit(pc+12,insn,{4:0x40a00000}),commit(pc+16,0x13)]
        fp={(0,3):dict(epoch=0,order=3,pc=pc+12,insn=insn,rs3_addr=3,rs3_rdata=0x40400000,
                       rm=4 if dynamic else 0)}
        return rows,refs,fp

    def test_fma_third_source_and_effective_rounding_are_checked(self):
        rows,refs,fp=self.fixture(True)
        self.assertEqual(compare(rows,refs,self.image,zfinx=True,fp_records=fp),4)
        for name,value in (('rs3_addr',2),('rs3_rdata',0),('rm',0),('pc',0),('insn',0)):
            broken=deepcopy(fp);broken[(0,3)][name]=value
            with self.subTest(name=name),self.assertRaises(Mismatch):
                compare(rows,refs,self.image,zfinx=True,fp_records=broken)
        for broken in (None,{},dict(fp,**{} )|{(0,4):fp[(0,3)]}):
            with self.assertRaises((Mismatch,ValueError)):
                compare(rows,refs,self.image,zfinx=True,fp_records=broken)
        for path,value in ((('rvfi_rd_wdata',),0),(('rvfi_rs1_addr',),2),
                           (('csrs','fflags','wmask'),0),(('csrs','frm','rdata'),0),
                           (('csrs','fcsr','wdata'),0),(('csrs','fcsr','rmask'),31)):
            broken=deepcopy(rows);target=broken[3]
            for key in path[:-1]:target=target[key]
            target[path[-1]]=value
            with self.subTest(path=path),self.assertRaises(Mismatch):
                compare(broken,refs,self.image,zfinx=True,fp_records=fp)

    def test_reference_aliases_and_non_fp_state_cannot_be_forgiven(self):
        before=dict(mstatus=0,misa=0x40000100,fflags=0,frm=0,fcsr=0)
        for after,effects in ((dict(before,fflags=1),{}),
                              (dict(before,mstatus=0x2000),{}),
                              (dict(before,misa=0x40000120),{}),
                              (dict(before,fflags=1,fcsr=1),{})):
            with self.assertRaises(ValueError):channels(0x13,False,before,after,effects)
        after=dict(before,fflags=5,frm=2,fcsr=69)
        masks=channels(0x00331073,False,before,after,{1:5,2:2}) # CSRRW fcsr,x6,rd=x0
        self.assertEqual(masks,dict(fcsr=(0,MASK),fflags=(0,31),frm=(0,7)))
        for effects in ({1:5},{1:4,2:2},{1:5,2:2,3:69}):
            with self.assertRaises(ValueError):channels(0x00331073,False,before,after,effects)
        with self.assertRaises(ValueError):channels(0x00331073,True,before,after,{})

    def test_decode_uses_fixed_isa_fields(self):
        for word,name,sources in ((0x00730553,'fadd',(6,7,0)),(0x58030553,'fsqrt',(6,0,0)),
                (0xe0031553,'fclass',(6,0,0)),(0xc0130553,'fcvt_wu_s',(6,0,0)),
                (0xd0030553,'fcvt_s_w',(6,0,0)),(0x48730543,'fmadd',(6,7,9))):
            desc=operation(word)
            self.assertEqual((desc['name'],desc['sources']),(name,sources))
        for word in (0x02730553,0x58730553,0xe0030553,0xf0030553,0x00032507,0x00732027):
            self.assertIsNone(operation(word))

    def test_pinned_reference_rejects_unsupported_e_high_register_probes(self):
        self.fixture()
        for word in (0x00780553,0x01030553,0x00730853,0x80730543):
            with self.subTest(word=hex(word)),self.assertRaisesRegex(ValueError,'high-register'):
                validate_profile([dict(type='reset'),instruction(insn=word)],dict(ISA_E=1),self.image)

    def test_coverage_counts_only_successful_fp_execution(self):
        rows,_,_=self.fixture(True)
        observed=coverage(rows)
        self.assertEqual(observed['operations'],{'fmadd':dict(count=1,static_rm={},dynamic_rm={'4':1})})
        self.assertEqual(observed['registers'],dict(rd=[4],rs1=[1],rs2=[2],rs3=[3]))
        self.assertEqual(observed['modes'],[3])
        rows[3].update(rvfi_trap=1,cause=2)
        observed=coverage(rows)
        self.assertEqual(observed['operations'],{})
        self.assertEqual(observed['traps'],{'2':1})

    def test_companion_is_strict_and_rejects_duplicate_or_malformed_records(self):
        _,_,fp=self.fixture()
        row=fp[(0,3)]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fp.jsonl'
            path.write_text(json.dumps(row)+'\n')
            self.assertEqual(read_fp_trace(path),fp)
            for rows in ((row,row),(dict(row,rm=8),),(dict(row,rs3_addr=0),),
                         (dict(row,unexpected=0),)):
                path.write_text(''.join(json.dumps(value)+'\n' for value in rows))
                with self.assertRaises(ValueError):read_fp_trace(path)
