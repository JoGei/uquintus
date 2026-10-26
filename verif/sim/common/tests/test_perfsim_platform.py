"""Independent byte-interval/CSR and memory-policy checks for native adapters."""
from pathlib import Path
import json
import random
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT/'verif/perfsim'),str(ROOT/'verif/sim/common')]
from memory import load,validate
from config_frontend import load_configurations
from csregfile_model import CSRModel,INPUTS
from pmp_model import permitted

CPP=r'''
#include "uqu_arch.h"
#include "uqu_memory.h"
#include <iostream>
int main(){unsigned mode;std::cin>>mode;
 if(mode==0){uqu::Architecture a;a.pmp=true;unsigned n;std::cin>>n;
  while(n--){unsigned machine,address,size,access;std::cin>>machine>>address>>size>>access;
   for(auto& x:a.cfg){unsigned value;std::cin>>value;x=value;}
   for(auto& x:a.addr)std::cin>>x;a.privilege=machine?3:0;
   std::cout<<a.permitted(address,1u<<size,access)<<'\n';}}
 if(mode==1){uqu::Architecture a;a.pmp=true;unsigned n;std::cin>>n;
  while(n--){unsigned privilege,instruction,value;std::cin>>privilege>>instruction>>value;a.privilege=privilege;
   auto r=a.access(instruction,value);std::cout<<r.illegal<<' '<<r.read<<' '<<r.write<<' '<<r.value<<'\n';}}
 if(mode==2){uqu::MemoryPort p;p.configure({1,0,1},{1,4,2},4,16,1,7);unsigned n;std::cin>>n;
  while(n--){unsigned edge,address,write;std::cin>>edge>>address>>write;auto grant=p.next_grant(edge);
   std::cout<<grant<<' '<<p.accept(address,write,grant)<<' '<<p.hits<<' '<<p.misses<<'\n';}}
}
'''

class PlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.folder=Path(cls.tmp.name)
        source=cls.folder/'policy.cpp';source.write_text(CPP);cls.binary=cls.folder/'policy'
        subprocess.run(['c++','-std=c++17','-O2','-I'+str(ROOT/'verif/perfsim/models'),str(source),'-o',str(cls.binary)],check=True)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def evaluate(self,mode,rows):
        text=f'{mode} {len(rows)}\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n'
        return [list(map(int,row.split())) for row in subprocess.check_output([str(self.binary)],input=text,text=True).splitlines()]

    def test_pmp_against_byte_interval_oracle(self):
        rng=random.Random(381);rows=[];expected=[]
        for _ in range(4000):
            cfg=[rng.randrange(256)&0x9f for _ in range(16)]
            addresses=[rng.randrange(0,1024) for _ in range(16)]
            if rng.randrange(20)==0:addresses[0]=0xffffffff;cfg[0]=0x9f
            machine=rng.randrange(2);address=rng.randrange(0,4096);size=rng.randrange(3);access=rng.choice((1,2,4))
            rows.append([machine,address,size,access,*cfg,*addresses])
            expected.append([int(permitted(True,cfg,addresses,address,size,access,machine))])
        self.assertEqual(self.evaluate(0,rows),expected)

    def test_csr_permissions_warl_and_locks_against_existing_scoreboard(self):
        params=load_configurations(['rv32i_pmp'],contract='map_dse')[0]['config']
        oracle=CSRModel(params);rng=random.Random(349);rows=[];expected=[]
        # Initialize all unreset PMP payloads before reading/locking them.
        sequence=[(0x3b0+i,1,0,1,rng.getrandbits(32),3) for i in range(16)]
        addresses=[0x300,0x301,0x304,0x305,0x306,0x310,0x320,0x340,0x341,0x342,0x343,0x344,0xf11,0xf14,0x30a,0x31a,0xc01,0x999,*range(0x3a0,0x3a4),*range(0x3b0,0x3c0)]
        sequence += [(rng.choice(addresses),rng.choice((1,2,3,5,6,7)),rng.randrange(2),rng.randrange(2),rng.getrandbits(32),rng.choice((0,3))) for _ in range(3000)]
        for address,op,rd,rs,value,priv in sequence:
            instruction=(address<<20)|(rs<<15)|(op<<12)|(rd<<7)|0x73
            i=dict(INPUTS,csr_valid=1,csr_commit=1,csr_addr=address,csr_op=op,csr_src=(rs if op&4 else value),
                   csr_src_zero=int(rs==0),csr_rd_zero=int(rd==0),priv_m=int(priv==3),hart_id=0)
            response,_=oracle.query(i)
            expected.append([response['exception_valid'],response['read'],response['write'],response['rdata']])
            rows.append([priv,instruction,value]);oracle.step(i)
        self.assertEqual(self.evaluate(1,rows),expected)

    def test_cache_stub_and_grants_against_independent_model(self):
        rng=random.Random(9);rows=[];expected=[];tags={};busy=last=hits=misses=0;edge=1
        for _ in range(1000):
            edge+=rng.randrange(1,4);address=rng.randrange(0,32)*4;write=rng.randrange(2)
            rows.append([edge,address,write]);grant=max(edge,busy)
            while [1,0,1][(grant-1)%3]==0:grant+=1
            tag=address//16;index=tag%4;hit=tags.get(index)==tag
            if hit:hits+=1;delay=1
            else:
                misses+=1;delay=7;busy=grant+delay
                if not write:tags[index]=tag
            last=max(grant+delay,last+1);expected.append([grant,last,hits,misses]);edge=grant
        self.assertEqual(self.evaluate(2,rows),expected)

    def test_profiles_and_identity(self):
        base=load_configurations(['rv32e'],contract='map_dse')[0]
        self.assertIn('rv32e',base['resolved']['functional']['isa'])
        self.assertEqual(base['resolved']['functional']['etiss']['misa']&0x110,0x10)
        for name in ('variable','cache-stub'):
            profile=load(ROOT/'config/perfsim/memory'/f'{name}.yml')
            row=load_configurations(['rv32e'],contract='map_dse',memory=profile)[0]
            self.assertEqual(row['resolved']['functional_id'],base['resolved']['functional_id'])
            self.assertNotEqual(row['model']['id'],base['model']['id'])
        with self.assertRaisesRegex(ValueError,'PMP fetch-fault'):
            load_configurations(['rv32i_pmp'],contract='map_dse',memory=load(ROOT/'config/perfsim/memory/variable.yml'))
        from model import render
        generated=render(base['model'])
        self.assertIn('EventDecode: {uRead2, uPass, uEvent}',generated)
        self.assertIn('Returns: {uPass, uEvent}',generated)
        self.assertIn('CsrReg: {uPass, uRead1, uCsrA, uCsrResult}',generated)
        bad=load();bad['dmem']['grant_pattern']=[0,0]
        with self.assertRaises(ValueError):validate(bad)

    def test_register_usage_is_independent_of_forwarding_edges(self):
        from perfsim import operand_masks
        # Augmented unused fields are zero; immediate CSR source is a zimm,
        # while a regular register source remains architectural even if its
        # timing-graph connector has been replaced by the hazard resource.
        schema=dict(trace=dict(instructions=[dict(id=1,mappings=[
            dict(traceValue='rs1',description='$bitfield{rs1}'),
            dict(traceValue='rs2',description='0'),dict(traceValue='rd',description='$bitfield{rd}')]),
            dict(id=2,mappings=[dict(traceValue='rs1',description='0'),
            dict(traceValue='rd',description='$bitfield{rd}')])]))
        self.assertEqual(operand_masks(schema),{'1':5,'2':4})

if __name__=='__main__':unittest.main()
