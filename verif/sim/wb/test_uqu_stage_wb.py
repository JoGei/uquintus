"""WB commitment, forwarding eligibility and owned architectural CSR events."""

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


class WBTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.model = WBModel(self.params)
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.cycles = self.retired = self.faulted = 0

    async def cycle(self, item=None, **controls):
        item = item or token()
        g = dict(GLOBALS, **controls)
        for field in FIELDS:
            getattr(self.dut, field + '_i').value = item[field]
        for field, value in g.items():
            getattr(self.dut, 'rst_ni' if field == 'rst_n' else field + '_i').value = value
        await Timer(1, units='ns')
        result, _ = self.model.evaluate(item, g)
        for name, value in result.items():
            if value is not None:
                actual = int(getattr(self.dut, name + '_o').value)
                assert actual == value, f'{name}: expected={value}, actual={actual}, token={item}, control={g}'
        self.retired += result['retire']
        self.faulted += result['exception_fire']
        self.dut.clk_i.value = 1
        await Timer(1, units='ns')
        self.dut.clk_i.value = 0
        self.model.step(item, g)
        await Timer(1, units='ns')
        self.observe(g)
        self.cycles += 1
        return result

    def observe(self, g):
        c = self.model.csr
        expected = dict(mstatus=c.words[0x300], mie=c.words[0x304], mtvec=c.words[0x305],
                        mepc=c.words[0x341], frm=c.words[2], fflags=c.words[1],
                        mip=(g['irq_software'] << 3) | (g['irq_timer'] << 7) | (g['irq_external'] << 11),
                        pmpcfg=sum(cfg << (8*i) for i, cfg in enumerate(c.configs)))
        for field, value in expected.items():
            actual = int(getattr(self.dut, field + '_o').value)
            assert actual == value, (field, actual, value)
        raw = self.dut.pmpaddr_o.value.binstr
        for entry, value in enumerate(c.addresses):
            if not self.params['ISA_PMP']:
                value = 0
            if value is not None:
                high = len(raw)-entry*32
                assert int(raw[high-32:high], 2) == value

    async def initialize(self):
        self.dut.clk_i.value = 0
        await self.cycle(rst_n=0, ready=1, trap=1, trap_pc=0xBAD)
        if self.params['ISA_PMP']:
            for n in range(16):
                await self.csr(0x3B0+n, 0x1000+n*0x100, rd=0)

    async def csr(self, address, source=0, op=1, rd=1, zero=0, **controls):
        return await self.cycle(token(kind=1, rd=rd, csr_addr=address, csr_src=source,
                                      csr_op=op, csr_src_zero=zero), **controls)

    def report(self, name):
        self.logger.info('%s: %d WB cycles, %d retired, %d faults', name, self.cycles, self.retired, self.faulted)


class DirectedTest(WBTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        for rd in range(32):
            for enabled in (0, 1):
                r = await self.cycle(token(rd=rd, rd_we=enabled, result=0x12340000+rd))
                assert r['we0'] == bool(enabled and rd and (not self.params['ISA_E'] or rd < 16))
        for kind in range(4):
            for rd in (0, 1, 15, 16, 31):
                for privileged in (0, 1):
                    await self.cycle(token(kind=kind, rd=rd, rd_we=0), priv_m=privileged)
        # CSR exchange/set/clear and suppression, including RO writes with a
        # non-x0 zero operand and legal constant-WARL writes to misa.
        for addr in (0x340, 0x300, 0x305, 0x306, 0x301, 0xC00, 0xF14, 0x310, 0xC01, 3):
            for op in range(8):
                for source, zero in ((0, 1), (0, 0), (31, 0), (0xFFFFFFFF, 0)):
                    for rd in (0, 1):
                        await self.csr(addr, source, op=op, zero=zero, rd=rd)
        # Existing exception must win over CSR/control checks and never update
        # ordinary destinations, even if all would otherwise be malformed.
        for kind in range(4):
            r = await self.cycle(token(kind=kind, rd=31, fflags_valid=1,
                                      exception_valid=1, exception_cause=7, exception_tval=0xBAD,
                                      pc=0x8002, csr_addr=0xFFF, csr_op=0))
            assert r['exception_cause'] == 7 and not r['retire'] and not r['we0']
            assert self.model.csr.words[0x342] == 7
        for flags in (1, 2, 4, 8, 16):
            r = await self.cycle(token(rd=0, fflags_valid=1, fflags=flags))
            assert bool(r['retire']) == bool(self.params['ISA_ZFINX'])
        if self.params['ISA_ZFINX']:
            assert int(self.dut.fflags_o.value) == 31
        # Counters count only actual retirement, including CSR and MRET, but
        # exclude synchronous trap entry and deliberately blocked cycles.
        await self.csr(0x320, 5, rd=0)
        await self.csr(0xB02, 0, rd=0)
        await self.csr(0xB82, 0, rd=0)
        await self.csr(0x320, 0, rd=0)
        before = self.model.csr.instret
        await self.cycle(token(rd=0))
        assert self.model.csr.instret == before+1
        r = await self.csr(0xB02, 100, rd=0)
        assert r['retire'] and self.model.csr.instret == 100
        await self.csr(0xB02, op=2, zero=1)
        await self.csr(0xB00, op=2, zero=1)
        self.report('Directed')
        self.drop_objection()


class ControlTest(WBTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        # Empty WB can fill while the controller withholds commitment.
        r = await self.cycle(valid=0, ready=0)
        assert r['ready'] and not r['valid']
        held = token(result=0xDEADBEEF, rd=3)
        before = self.model.csr.instret
        for _ in range(8):
            r = await self.cycle(held, ready=0)
            assert r['result_valid'] and r['result'] == held['result'] and not r['we0']
        assert self.model.csr.instret == before
        await self.cycle(held)
        assert self.model.csr.instret == before+1
        # CSR counter queries must not expose a changing speculative bypass.
        query = token(kind=1, csr_addr=0xB00, csr_op=2, csr_src_zero=1, rd=4)
        for _ in range(9):
            r = await self.cycle(query, ready=0)
            assert not r['result_valid'] and not r['we0']
        before = self.model.csr.cycle
        r = await self.cycle(query)
        assert r['wdata0'] == before and r['result'] == before
        # A fault can be reported indefinitely without trap-state mutation.
        fault = token(exception_valid=1, exception_cause=5, exception_tval=0xBAD,
                      pc=0x1234567A, fflags_valid=1)
        saved = (self.model.csr.words[0x341], self.model.csr.words[0x342])
        for _ in range(5):
            r = await self.cycle(fault, ready=0)
            assert r['exception_valid'] and not r['exception_fire']
            assert (self.model.csr.words[0x341], self.model.csr.words[0x342]) == saved
        await self.cycle(fault)
        assert self.model.csr.words[0x342] == 5
        # Owning flush cancels all token effects, while a separately accepted
        # global trap still updates architectural state during that flush.
        before = self.model.csr.words[0x340]
        await self.csr(0x340, 0xFFFFFFFF, flush=1)
        assert self.model.csr.words[0x340] == before
        await self.cycle(fault, flush=1)
        await self.cycle(held, flush=1, trap=1, trap_pc=0xF000, trap_interrupt=1, trap_cause=11)
        assert self.model.csr.words[0x342] == 0x8000000B
        # The arbiter sees faults independently of accepted-trap input. Such
        # collisions are defensive checks; the real controller must arbitrate
        # an older WB fault ahead of an interrupt before asserting trap_i.
        r = await self.cycle(fault, trap=1, trap_pc=0xF100, trap_interrupt=1, trap_cause=7)
        assert r['exception_valid'] and not r['valid'] and not r['exception_fire']
        await self.csr(0x300, 0x80, rd=0)
        saved_pc = self.model.csr.words[0x341]
        r = await self.cycle(token(kind=2, rd_we=1, rd=31))
        assert r['mret'] and r['retire'] and not r['we0']
        assert self.model.csr.words[0x341] == saved_pc
        if self.params['ISA_UMODE']:
            assert not int(self.dut.mstatus_o.value) & 0x1800
        # Reset dominates coincident token/FP/trap activity; afterward a new
        # instruction with identical payload may retire normally.
        await self.cycle(token(fflags_valid=1, fflags=31), rst_n=0, trap=1, trap_cause=11)
        assert self.model.csr.instret == 0
        for _ in range(64):
            assert (await self.cycle(held))['retire']
        self.report('Control')
        self.drop_objection()


class RandomizedTest(WBTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        addresses = (0x340, 0x300, 0x301, 0x304, 0x305, 0x306, 0x320, 0x341,
                     0x342, 0x343, 0x344, 0xB00, 0xB80, 0xB02, 0xB82,
                     0xC00, 0xC02, 0xF14, 0xC01, 1, 2, 3, 0x3A0, 0x3B0)
        for _ in range(2048):
            item = token(kind=self.rng.randrange(4), result=self.rng.getrandbits(32),
                         rd_we=self.rng.randrange(2), rd=self.rng.randrange(32),
                         pc=self.rng.getrandbits(32), instr=self.rng.getrandbits(32),
                         csr_addr=self.rng.choice(addresses), csr_op=self.rng.randrange(8),
                         csr_src=self.rng.getrandbits(32), csr_src_zero=self.rng.randrange(2),
                         fflags_valid=self.rng.randrange(2), fflags=self.rng.randrange(32),
                         exception_valid=int(self.rng.randrange(8) == 0), exception_cause=7,
                         exception_tval=self.rng.getrandbits(32))
            g = dict(ready=0, priv_m=self.rng.randrange(2) if self.params['ISA_UMODE'] else 1,
                     irq_software=self.rng.randrange(2), irq_timer=self.rng.randrange(2),
                     irq_external=self.rng.randrange(2))
            for _ in range(self.rng.randrange(4)):
                await self.cycle(item, **g)
            g['ready'] = 1
            g['valid'] = int(self.rng.randrange(8) != 0)
            g['flush'] = int(self.rng.randrange(8) == 0)
            if self.rng.randrange(32) == 0:
                g.update(trap=1, trap_pc=0x1000, trap_interrupt=1, trap_cause=3)
            await self.cycle(item, **g)
        for address in addresses:
            await self.csr(address, op=2, zero=1)
        self.report('Randomized')
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def control(_dut):
    await uvm_root().run_test(ControlTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)
