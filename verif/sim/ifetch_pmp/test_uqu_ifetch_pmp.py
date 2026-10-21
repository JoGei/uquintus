"""One core-owned PMP feeds real IF/MEM engines with independent transactions."""
import json
import os
from pathlib import Path
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from ifetch_model import MASK, completion, word_address
from pmp_model import OFF, NA4, NAPOT, LEGAL_PERMISSIONS, config, napot, permitted


class CorePMPTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.enabled = json.loads(os.environ['UQU_COMPONENT_PARAMS'])['ISA_PMP']
        self.policy = dict(pmpcfg=0,pmpaddr=0)

    def configure(self, configs, addresses):
        self.policy = dict(pmpcfg=sum(c << (8*n) for n,c in enumerate(configs)),
                           pmpaddr=sum(a << (32*n) for n,a in enumerate(addresses)))

    async def cycle(self, **changes):
        i = dict(rst_n=1, if_valid=0, if_addr=0, if_priv_m=0, if_flush=0,
                 if_permit=1, if_result_ready=0, mem_valid=0, mem_addr=0,
                 mem_priv_m=0, mem_we=0, mem_op=2, mem_wdata=0,
                 mem_flush=0, mem_permit=1, mem_result_ready=0,
                 imem_gnt=0, imem_rvalid=0, imem_rdata=0, imem_err=1,
                 dmem_gnt=0, dmem_rvalid=0, dmem_rdata=0, dmem_err=1)
        i.update(self.policy)
        i.update(changes)
        self.dut.clk_i.value = 0
        for name,value in i.items():
            getattr(self.dut,'rst_ni' if name=='rst_n' else name+'_i').value = value
        await Timer(1,units='ns')
        r = {name:int(getattr(self.dut,name+'_o').value) for name in (
            'if_ready','if_allow','if_busy','if_result_valid','if_result_addr',
            'if_result_data','if_result_error','mem_ready','mem_allow','mem_busy',
            'mem_result_valid','mem_result_data','mem_exception_valid',
            'mem_exception_cause','mem_exception_tval','imem_req','imem_addr',
            'dmem_req','dmem_we','dmem_addr','dmem_wdata','dmem_be')}
        self.dut.clk_i.value = 1
        await Timer(1,units='ns')
        return r

    async def reset(self):
        await self.cycle(rst_n=0)
        r = await self.cycle()
        assert r['if_ready'] and r['mem_ready']

    async def pair(self, configs, addresses, if_addr=0x1002, mem_addr=0x1030,
                   if_machine=False, mem_machine=False, write=False,
                   if_error=False, mem_error=False):
        await self.reset()
        self.configure(configs,addresses)
        if_allowed = permitted(self.enabled,configs,addresses,word_address(if_addr),2,4,if_machine)
        mem_allowed = permitted(self.enabled,configs,addresses,mem_addr,2,2 if write else 1,mem_machine)
        r = await self.cycle(if_valid=1,if_addr=if_addr,if_priv_m=int(if_machine),
            mem_valid=1,mem_addr=mem_addr,mem_priv_m=int(mem_machine),
            mem_we=int(write),mem_wdata=0xCAFEBABE)
        assert (r['if_allow'],r['mem_allow']) == (if_allowed,mem_allowed)
        assert r['if_ready'] and r['mem_ready']
        # Different live addresses/permissions must not change captured decisions.
        self.configure([0]*16,[0]*16)
        r = await self.cycle(imem_gnt=int(if_allowed),dmem_gnt=int(mem_allowed))
        assert (r['imem_req'],r['dmem_req']) == (if_allowed,mem_allowed)
        if if_allowed:
            assert r['imem_addr'] == word_address(if_addr) and not r['if_result_valid']
        else:
            assert r['if_result_valid'] and r['if_result_error']
        if mem_allowed:
            assert (r['dmem_addr'],r['dmem_we'],r['dmem_be']) == (mem_addr,int(write),15)
            assert r['dmem_wdata'] == (0xCAFEBABE if write else 0)
        else:
            assert r['mem_result_valid'] and r['mem_exception_valid']
        r = await self.cycle(imem_rvalid=int(if_allowed),imem_rdata=0x11223344,imem_err=int(if_error),
                             dmem_rvalid=int(mem_allowed),dmem_rdata=0xAABBCCDD,dmem_err=int(mem_error))
        assert r['if_result_valid'] == (not if_allowed)
        assert r['mem_result_valid'] == (not mem_allowed)
        if_expected = completion(if_addr,0x11223344,not if_allowed,if_error)
        mem_failed = not mem_allowed or mem_error
        for index in range(4):
            r = await self.cycle(if_result_ready=int(index==3),mem_result_ready=int(index==0))
            assert r['if_result_valid']
            assert (r['if_result_addr'],r['if_result_data'],r['if_result_error']) == if_expected
            if index==0:
                assert r['mem_result_valid'] and r['mem_exception_valid'] == mem_failed
                assert r['mem_result_data'] == (0 if write or mem_failed else 0xAABBCCDD)
                assert r['mem_exception_cause'] == ((7 if write else 5) if mem_failed else 0)
                assert r['mem_exception_tval'] == (mem_addr if mem_failed else 0)
            else:
                assert r['mem_ready'] and not r['mem_busy'] and not r['mem_result_valid']
        r = await self.cycle()
        assert r['if_ready'] and r['mem_ready'] and not r['if_busy'] and not r['mem_busy']


class PermissionsTest(CorePMPTest):
    async def run_phase(self):
        self.raise_objection()
        count = 0
        for permissions in LEGAL_PERMISSIONS:
            for locked in (False,True):
                for if_machine in (False,True):
                    for mem_machine in (False,True):
                        for write in (False,True):
                            configs = [config(NAPOT,permissions,locked)]+[0]*15
                            addresses = [napot(0x1000,0x1000)]+[0]*15
                            await self.pair(configs,addresses,if_machine=if_machine,
                                mem_machine=mem_machine,write=write,
                                if_error=count%3==0,mem_error=count%4==0)
                            count += 1
        # Different entries, highest entry, unmatched addresses and word normalization.
        configs = [config(NAPOT,3)]+[0]*14+[config(NA4,4,True)]
        addresses = [napot(0x2000,0x1000)]+[0]*14+[0x1000//4]
        await self.pair(configs,addresses,if_addr=0x1003,mem_addr=0x2000)
        await self.pair(configs,addresses,if_addr=0x1004,mem_addr=0x3000)
        await self.pair([config(OFF)]+[0]*15,[0]*16,
                         if_addr=MASK,mem_addr=0,if_machine=True,mem_machine=False)
        self.logger.info('%d permission combinations plus boundary cases; ISA_PMP=%d',count,self.enabled)
        self.drop_objection()


class ConcurrentTest(CorePMPTest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        configs = [config(NAPOT,4),config(NAPOT,3)]+[0]*14
        addresses = [napot(0x1000,0x1000),napot(0x2000,0x1000)]+[0]*14
        self.configure(configs,addresses)
        r = await self.cycle(if_valid=1,if_addr=0x1002,mem_valid=1,mem_addr=0x2000)
        assert r['if_ready'] and r['mem_ready'] and r['if_allow'] and r['mem_allow']
        r = await self.cycle(dmem_gnt=1)
        assert r['imem_req'] and r['imem_addr']==0x1000 and r['dmem_req']
        r = await self.cycle(dmem_rvalid=1,dmem_rdata=0x12345678,dmem_err=0)
        assert r['imem_req'] and not r['mem_result_valid']
        r = await self.cycle(mem_result_ready=1)
        assert r['imem_req'] and r['mem_result_valid'] and r['mem_result_data']==0x12345678
        # The LSU can accept another access while IF still waits for its first grant.
        r = await self.cycle(mem_valid=1,mem_addr=0x2004,mem_we=1,mem_wdata=0xCAFEBABE)
        assert r['imem_req'] and r['imem_addr']==0x1000 and r['mem_ready'] and r['mem_allow']
        r = await self.cycle(dmem_gnt=1)
        assert r['imem_req'] and r['dmem_req'] and r['dmem_we'] and r['dmem_addr']==0x2004
        assert r['dmem_wdata']==0xCAFEBABE and r['dmem_be']==15
        r = await self.cycle(dmem_rvalid=1,dmem_err=0,if_flush=1)
        assert r['imem_req'] and r['imem_addr']==0x1000 and not r['if_result_valid']
        r = await self.cycle(imem_gnt=1,if_flush=1)
        assert r['imem_req'] and r['imem_addr']==0x1000 and r['mem_result_valid']
        r = await self.cycle(imem_rvalid=1,imem_err=1,mem_result_ready=1)
        assert not r['if_result_valid'] and r['mem_result_valid'] and not r['mem_exception_valid']
        r = await self.cycle(if_valid=1,if_addr=0x1004)
        assert r['if_ready'] and r['mem_ready'] and not r['if_result_valid']
        r = await self.cycle(imem_gnt=1)
        assert r['imem_req'] and r['imem_addr']==0x1004
        await self.cycle(imem_rvalid=1,imem_rdata=0x87654321,imem_err=0)
        r = await self.cycle(if_result_ready=1)
        assert r['if_result_valid'] and not r['if_result_error']
        assert r['if_result_addr']==0x1004 and r['if_result_data']==0x87654321
        self.drop_objection()


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def permissions(_dut):
    await uvm_root().run_test(PermissionsTest)


@cocotb.test(timeout_time=1000,timeout_unit='us')
async def concurrent(_dut):
    await uvm_root().run_test(ConcurrentTest)
