"""WB with a real parent MEM/WB slot, GPR file and privilege transition stub."""

import json
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from wb_model import FIELDS, GLOBALS, WBModel, token


class ParentTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.model = WBModel(self.params)
        self.slot = None
        self.priv = 1
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.retired = self.faulted = self.writes = 0

    def check_gprs(self, probes):
        for n, address in enumerate(probes):
            expected = 0 if self.params['ISA_E'] and address >= 16 else self.model.gprs[address]
            if expected is not None:
                assert int(getattr(self.dut, f'rdata{n}_o').value) == expected, (address, expected)

    async def cycle(self, incoming=None, ready=1, reset=False, flush=False, **events):
        d = self.dut
        item = self.slot or token()
        g = dict(GLOBALS, valid=int(self.slot is not None), ready=ready, rst_n=int(not reset),
                 flush=int(flush), priv_m=self.priv, **events)
        g['event_priv_m'] = self.priv
        d.in_valid_i.value = int(incoming is not None)
        for field in FIELDS:
            getattr(d, 'in_'+field+'_i').value = (incoming or token())[field]
        for field in GLOBALS:
            if field not in ('valid', 'ready', 'priv_m', 'event_priv_m', 'lsu') and not field.startswith('lsu_res_'):
                getattr(d, 'rst_ni' if field == 'rst_n' else field+'_i').value = g[field]
        d.commit_ready_i.value = ready
        probes = (self.rng.randrange(32), self.rng.randrange(32))
        d.raddr0_i.value, d.raddr1_i.value = probes
        await Timer(1, units='ns')
        expected, _ = self.model.evaluate(item, g)
        for name, value in expected.items():
            if value is None or name == 'lsu_res_ready':
                continue
            if name == 'result' and not expected['result_valid']:
                continue
            port = 'wb_'+name+'_o' if name in ('valid', 'ready') else name+'_o'
            assert int(getattr(d, port).value) == value, (name, value, item, g)
        redirect = any(expected[n] for n in ('exception_fire', 'mret', 'dret', 'debug_enter', 'debug_exception', 'debug_ebreak'))
        accepting = bool(expected['ready'] and not redirect)
        assert int(d.in_ready_o.value) == accepting
        accepted = incoming is not None and accepting
        self.check_gprs(probes)
        old_mpp = bool(self.model.csr.words[0x300] & 0x1800)
        old_prv = self.model.csr.words[0x7B0] & 3 == 3
        d.clk_i.value = 1
        await Timer(1, units='ns')
        d.clk_i.value = 0
        self.model.step(item, g)
        if reset or flush or g['trap'] or redirect:
            self.slot = None
        elif expected['ready']:
            self.slot = incoming if accepted else None
        if reset or g['trap'] or expected['exception_fire'] or expected['debug_enter']:
            self.priv = 1
        elif expected['dret']:
            self.priv = int(old_prv)
        elif expected['mret']:
            self.priv = int(old_mpp)
        self.retired += expected['retire']
        self.faulted += expected['exception_fire']
        self.writes += expected['we0']
        await Timer(1, units='ns')
        assert int(d.priv_m_o.value) == self.priv
        assert int(d.mstatus_o.value) == self.model.csr.words[0x300]
        assert int(d.mepc_o.value) == self.model.csr.words[0x341]
        self.check_gprs(probes)
        return accepted, expected

    async def initialize(self):
        self.dut.clk_i.value = 0
        await self.cycle(reset=True)

    async def execute(self, item, wait=0):
        accepted, _ = await self.cycle(incoming=item, ready=0)
        assert accepted and self.slot is item
        for _ in range(wait):
            _, event = await self.cycle(ready=0)
            assert not event['retire'] and not event['exception_fire'] and not event['we0']
        _, event = await self.cycle()
        assert self.slot is None and (event['retire'] or event['exception_fire'])
        return event

    async def stream(self, items, stalls=False):
        sent = done = cycles = 0
        before = self.retired
        for _ in range(100000):
            incoming = items[sent] if sent < len(items) else None
            if stalls and self.rng.randrange(4) == 0:
                incoming = None
            accepted, event = await self.cycle(incoming=incoming, ready=self.rng.randrange(2) if stalls else 1)
            assert not event['exception_fire'], event
            if accepted:
                sent += 1
            done += event['retire']
            cycles += 1
            if done == len(items):
                assert sent == done and self.slot is None
                assert self.retired-before == len(items)
                return cycles
        raise AssertionError('WB pipeline did not drain')


class StreamTest(ParentTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        count = 16 if self.params['ISA_E'] else 32
        items = [token(result=0x1000+i, rd=i%count, pc=0x8000+4*i) for i in range(64)]
        assert await self.stream(items) == 65
        program = [token(kind=1, csr_addr=0x340, csr_op=1, csr_src=0x12345678, csr_src_zero=0, rd=2),
                   token(kind=1, csr_addr=0x340, csr_op=2, csr_src_zero=1, rd=3),
                   token(rd_we=0, rd=31, result=0xDEAD)]
        for i in range(256):
            if i % 3:
                program.append(token(rd=self.rng.randrange(count), result=self.rng.getrandbits(32),
                                     rd_we=self.rng.randrange(2), fflags_valid=self.params['ISA_ZFINX'],
                                     fflags=self.rng.randrange(32)))
            else:
                address = self.rng.choice((0x340, 0x305, 0x301, 0xB00, 0xB02, 0x320))
                program.append(token(kind=1, rd=self.rng.randrange(count), csr_addr=address,
                                     csr_op=self.rng.choice((1, 2, 3, 5, 6, 7)),
                                     csr_src=self.rng.getrandbits(32), csr_src_zero=0))
        await self.stream(program, stalls=True)
        assert self.model.gprs[3] is not None
        # Read every known GPR to validate committed state, including registers
        # last written many stalls/CSR accesses earlier and immutable x0.
        for a in range(count):
            self.dut.raddr0_i.value = a
            await Timer(1, units='ns')
            if self.model.gprs[a] is not None:
                assert int(self.dut.rdata0_o.value) == self.model.gprs[a]
        self.logger.info('Parent WB stream: 64 consecutive + 259 mixed tokens, %d GPR writes', self.writes)
        self.drop_objection()


class TrapsTest(ParentTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        await self.execute(token(result=0xCAFEBABE, rd=1))
        # Faulting CSR must preserve its destination and ordinary CSR state,
        # retain trap PC identity while held, and enter the trap only once.
        before = self.model.gprs[1]
        event = await self.execute(token(kind=1, csr_addr=0xF14, csr_op=1,
                                         csr_src=0xFFFFFFFF, csr_src_zero=0, rd=1,
                                         pc=0x9002, instr=0xDEADC0DE), wait=7)
        assert event['exception_cause'] == 2 and self.model.gprs[1] == before
        assert self.model.csr.words[0x343] == 0xDEADC0DE
        # Flush a held CSR: no write, no retirement, no destination update.
        scratch = self.model.csr.words[0x340]
        accepted, _ = await self.cycle(incoming=token(kind=1, csr_addr=0x340, csr_op=1,
                                                     csr_src=0xBAD, csr_src_zero=0, rd=1), ready=0)
        assert accepted
        await self.cycle(ready=0)
        _, event = await self.cycle(flush=True)
        assert not event['retire'] and self.model.csr.words[0x340] == scratch
        assert self.model.gprs[1] == before
        # MRET commits CSR restoration and retirement together. This parent
        # stub changes privilege using the pre-edge MPP, as the real controller must.
        if self.params['ISA_UMODE']:
            await self.execute(token(kind=1, csr_addr=0x300, csr_op=1, csr_src=0x80,
                                     csr_src_zero=0, rd=0))
            event = await self.execute(token(kind=2, rd=31), wait=3)
            assert event['mret'] and self.priv == 0
            # Illegal user CSR enters M, with MPP recording the interrupted U.
            await self.execute(token(kind=1, csr_addr=0x300, csr_op=2, rd=1, pc=0xA002), wait=2)
            assert self.priv == 1 and not int(self.dut.mstatus_o.value) & 0x1800
        else:
            assert (await self.execute(token(kind=2)))['mret'] and self.priv == 1
        # A drained external interrupt updates CSR state without retirement.
        before = self.retired
        await self.cycle(trap=1, trap_pc=0xB002, trap_interrupt=1, trap_cause=11)
        assert self.retired == before and self.model.csr.words[0x342] == 0x8000000B
        await self.execute(token(result=0x1234, rd=2))
        saved_gpr = self.model.gprs[1]
        await self.cycle(reset=True)
        self.dut.raddr0_i.value = 1
        await Timer(1, units='ns')
        assert int(self.dut.rdata0_o.value) == saved_gpr
        await self.execute(token(result=0x5678, rd=2))
        self.logger.info('Parent WB traps/flush/MRET/privilege/reset passed')
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def pipeline(_dut):
    await uvm_root().run_test(StreamTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def traps(_dut):
    await uvm_root().run_test(TrapsTest)


class ExtensionParentTest(ParentTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        if self.params['XIF']:
            # Real parent slot stalls; both physical GPR ports update together.
            for n in range(24):
                rd = 2 + 2*(n % (7 if self.params['ISA_E'] else 15))
                pair = bool(self.params['XIF_DUALWRITE'] and n % 2 == 0)
                await self.execute(token(rd=rd, result=0x11110000+n))
                await self.execute(token(rd=rd+1, result=0x22220000+n))
                item = token(kind=3, xif_id=n % 8, rd=rd)
                assert (await self.cycle(incoming=item, ready=0))[0]
                _, r = await self.cycle(ready=0)
                assert r['xif_commit_valid'] and not r['retire']
                for _ in range(3):
                    accepted, r = await self.cycle(incoming=token(rd=1, result=0xBAD))
                    assert not accepted and not r['retire'] and not r['xif_commit_valid']
                packet = dict(xif_result_valid=1, xif_result_id=n % 8, xif_result_rd=rd,
                              xif_result_we=3 if pair else 1,
                              xif_result_data=((0xA000+n) << 32 | (0xB000+n)) if pair else 0xB000+n)
                for _ in range(3):
                    _, r = await self.cycle(ready=0, **packet)
                    assert r['result'] == 0xB000+n and not r['we0'] and not r['we1']
                    self.dut.raddr0_i.value = rd
                    self.dut.raddr1_i.value = rd+1
                    await Timer(1, units='ns')
                    self.check_gprs((rd, rd+1))
                _, r = await self.cycle(**packet)
                assert r['we0'] and bool(r['we1']) == pair and self.slot is None
                # Explicit post-edge probes verify both words, including port 1.
                self.dut.raddr0_i.value = rd
                self.dut.raddr1_i.value = rd+1
                await Timer(1, units='ns')
                self.check_gprs((rd, rd+1))
                # Normal younger instruction resumes after completion.
                await self.execute(token(rd=1, result=n))
        if self.params['DEBUG']:
            # Enter after draining, execute debug code via the ordinary GPR/CSR
            # paths, then DRET through WB. No direct register debug backdoor.
            _, r = await self.cycle(debug_enter=1, debug_pc=0x8000, debug_cause=3)
            assert r['debug_enter']
            debug = dict(debug_mode=1)
            async def execute_debug(item):
                assert (await self.cycle(incoming=item, ready=0, **debug))[0]
                _, result = await self.cycle(**debug)
                assert self.slot is None
                return result
            counts = self.model.csr.cycle, self.model.csr.instret
            await execute_debug(token(rd=5, result=0xABCDEF01))
            await execute_debug(token(kind=1, rd=0, csr_addr=0x7B2, csr_op=1,
                                      csr_src=0x1234, csr_src_zero=0))
            r = await execute_debug(token(kind=1, rd=6, csr_addr=0x7B2, csr_op=2, csr_src_zero=1))
            assert r['wdata0'] == 0x1234
            assert counts == (self.model.csr.cycle, self.model.csr.instret)
            saved = self.model.csr.words[0x341], self.model.csr.words[0x342]
            r = await execute_debug(token(exception_valid=1, exception_cause=5))
            assert r['debug_exception'] and not r['exception_fire']
            assert saved == (self.model.csr.words[0x341], self.model.csr.words[0x342])
            await execute_debug(token(kind=1, rd=0, csr_addr=0x7B0, csr_op=1, csr_src_zero=0,
                                      csr_src=4 if self.params['ISA_UMODE'] else 7))
            r = await execute_debug(token(kind=4))
            assert r['dret'] and self.priv == (0 if self.params['ISA_UMODE'] else 1)
            await self.execute(token(rd=5, result=42))
            # Controller chooses next PC and reentry after exactly one retired instruction.
            _, r = await self.cycle(debug_enter=1, debug_cause=4, debug_pc=0x9000)
            assert r['debug_enter'] and self.model.csr.words[0x7B1] == 0x9000
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def extensions(_dut):
    await uvm_root().run_test(ExtensionParentTest)
