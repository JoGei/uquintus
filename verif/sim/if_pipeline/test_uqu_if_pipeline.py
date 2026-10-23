"""Real IF -> parent-owned IF/DE -> real DE, including branch feedback."""
import json
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'common'))
from compressed_model import assemble, compressed
from response_queue import ResponseQueue


class PipelineTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.c = self.params['ISA_C']
        self.expand_if = self.c and self.params['MUA_C_IMPL']==0 and self.params['MUA_C_DECOMPRESS_STAGE']==0
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.words = {}
        self.errors = set()
        self.responses = ResponseQueue()
        self.response = None
        self.previous_bus = None
        self.slot = None
        self.transfers = []
        self.branches = []
        self.fetches = []

    def put(self,pc,entries):
        image = {}
        for value,size in entries:
            for offset,byte in enumerate(value.to_bytes(size,'little')):
                image[pc+offset] = byte
            pc += size
        for address in {address&~3 for address in image}:
            self.words[address] = sum(image.get(address+k,0)<<(8*k) for k in range(4))

    async def cycle(self,**changes):
        i = dict(rst_n=1,boot_addr=0x1000,flush=0,redirect_valid=0,redirect_addr=0,
                 fetch_enable=1,if_permit=1,de_permit=1,ready=1,pmp_allow=1)
        i.update(changes)
        d = self.dut
        d.clk_i.value = 0
        for name,value in i.items():
            getattr(d,'rst_ni' if name=='rst_n' else name+'_i').value = value
        d.imem_gnt_i.value = 0
        d.imem_rvalid_i.value = 0
        d.imem_rdata_i.value = self.rng.getrandbits(32)
        d.imem_err_i.value = 1
        returning = self.response is not None and self.response[0]==0
        d.imem_rvalid_i.value = int(returning)
        if returning:
            _,data,error = self.response
            d.imem_rdata_i.value = data
            d.imem_err_i.value = error
        await Timer(1,units='ns')
        req,addr = int(d.imem_req_o.value),int(d.imem_addr_o.value)
        if self.previous_bus and i['rst_n']:
            assert (req,addr)==(1,self.previous_bus)
        grant = req and self.rng.randrange(3)!=0
        d.imem_gnt_i.value = int(grant)
        await Timer(1,units='ns')
        names = ('if_transfer','if_pc','if_instr','if_original','if_compressed','if_exception',
                 'slot_valid','slot_instr','slot_original','slot_compressed','valid','pc',
                 'original_instr','compressed','link','branch_resolve','branch_taken',
                 'branch_target','correction','exception_valid','exception_cause','exception_tval',
                 'pmp_valid','pmp_addr')
        o = {name:int(getattr(d,name+'_o').value) for name in names}
        external = not i['rst_n'] or i['flush'] or i['redirect_valid']
        if i['rst_n']:
            assert o['slot_valid']==int(self.slot is not None)
            if self.slot:
                assert (o['slot_instr'],o['slot_original'],o['slot_compressed'])==self.slot[:3]
        fire = bool(o['valid'] and i['ready'])
        if fire:
            assert self.slot is not None and not external
            self.transfers.append((o['pc'],o['original_instr'],o['compressed'],o['link'],
                                   o['exception_valid'],o['exception_cause'],o['exception_tval']))
        if o['branch_resolve']:
            assert fire and not o['exception_valid']
            self.branches.append((o['pc'],o['branch_taken'],o['branch_target']))
        if o['branch_taken']:
            assert o['branch_resolve']
        if o['correction']:
            assert fire and not o['if_transfer']
        incoming = None
        if o['if_transfer']:
            original = o['if_original']
            expansion = compressed(original) if o['if_compressed'] and self.expand_if else None
            if not o['if_exception']:
                assert o['if_instr']==(expansion[1] if expansion else original)
            incoming = (o['if_instr'],original,o['if_compressed'],o['if_pc'])
        if external or o['correction']:
            self.slot = None
        elif fire or self.slot is None:
            self.slot = incoming
        else:
            assert incoming is None,'overwrote held IF/DE'
        if o['pmp_valid']:
            self.fetches.append(o['pmp_addr'])
        if not i['rst_n']:
            self.responses.clear()
        else:
            self.responses.advance(returning)
            if grant:
                self.responses.issue(self.rng.randrange(5),self.words.get(addr,0x00010001 if self.c else 0x13),int(addr in self.errors))
        self.response = self.responses.head
        self.previous_bus = addr if req and not grant and i['rst_n'] else None
        d.clk_i.value = 1
        await Timer(1,units='ns')
        return o

    async def reset(self):
        await self.cycle(rst_n=0)

    async def until(self,predicate,**changes):
        for _ in range(2048):
            o = await self.cycle(**changes)
            if predicate(o):
                return o
        raise AssertionError('IF/DE pipeline timeout')


class BranchesTest(PipelineTest):
    async def run_phase(self):
        self.raise_objection()
        if self.c:
            entries = [(1,2),(assemble('jal',rd=1,imm=8),4),(0,4),(0x2011,2),
                       (0,2),(1,2),(assemble('bne',imm=8),4),(assemble('beq',imm=8),4),
                       (0,4),(0x00100093,4)]
            expected = [(0x1000,1,1,0),(0x1002,entries[1][0],0,0x1006),
                        (0x100A,0x2011,1,0x100C),(0x100E,1,1,0),
                        (0x1010,entries[6][0],0,0),(0x1014,entries[7][0],0,0),
                        (0x101C,0x00100093,0,0)]
        else:
            entries = [(0x13,4),(assemble('jal',rd=1,imm=8),4),(0,4),
                       (assemble('bne',imm=8),4),(assemble('beq',imm=8),4),(0,4),(0x00100093,4)]
            expected = [(0x1000,0x13,0,0),(0x1004,entries[1][0],0,0x1008),
                        (0x100C,entries[3][0],0,0),(0x1010,entries[4][0],0,0),
                        (0x1018,0x00100093,0,0)]
        self.put(0x1000,entries)
        await self.reset()
        await self.until(lambda o:len(self.transfers)==1)
        first_branch = expected[1][1]
        await self.until(lambda o:o['slot_valid'] and o['slot_original']==first_branch,de_permit=0)
        for _ in range(12):
            o = await self.cycle(de_permit=0)
            assert not o['branch_resolve']
            if self.params['MUA_BRANCH_PREDICTOR']==0:
                assert not o['pmp_valid']
        for _ in range(4096):
            await self.cycle(ready=int(self.rng.random()<0.75),de_permit=int(self.rng.random()<0.85))
            assert [entry[:4] for entry in self.transfers]==expected[:len(self.transfers)]
            assert not any(entry[4] for entry in self.transfers),'wrong-path instruction escaped'
            if len(self.transfers)==len(expected):
                break
        else:
            raise AssertionError('branch stream did not finish')
        assert len(self.branches)==(4 if self.c else 3)
        assert sum(entry[1] for entry in self.branches)==(3 if self.c else 2)
        self.drop_objection()


class FaultsTest(PipelineTest):
    async def run_phase(self):
        self.raise_objection()
        self.words[0x1000] = 0x00014002 if self.c else 0
        await self.reset()
        await self.until(lambda o:o['slot_valid'],de_permit=0)
        for _ in range(8):
            await self.cycle(de_permit=0)
        await self.until(lambda o:bool(self.transfers))
        assert self.transfers[0][0]==0x1000 and self.transfers[0][4:]==(1,2,0x4002 if self.c else 0)
        # A fetch access fault takes priority over an illegal compressed word.
        self.errors.add(0x2000)
        self.words[0x2000] = 0x00004002
        await self.cycle(redirect_valid=1,redirect_addr=0x2000,de_permit=0)
        before = len(self.transfers)
        await self.until(lambda o:o['slot_valid'],de_permit=0)
        for _ in range(8):
            await self.cycle(de_permit=0)
        await self.until(lambda o:len(self.transfers)>before)
        assert self.transfers[-1][0]==0x2000 and self.transfers[-1][4:]==(1,1,0x2000)
        self.drop_objection()


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def branches(dut):
    await uvm_root().run_test('BranchesTest')


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def faults(dut):
    await uvm_root().run_test('FaultsTest')
