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

    async def cycle(self, item=None, comb_result=False, **controls):
        item = item or token()
        g = dict(GLOBALS, **controls)
        for field in FIELDS:
            getattr(self.dut, field + '_i').value = item[field]
        for field, value in g.items():
            getattr(self.dut, 'rst_ni' if field == 'rst_n' else field + '_i').value = value
        await Timer(1, units='ns')
        if comb_result:
            # A completed coprocessor may expose its result combinationally
            # upon seeing permission, without waiting for a clock edge.
            assert not g['xif_result_valid']
            assert int(self.dut.xif_result_ready_o.value) == 1
            assert not int(self.dut.we0_o.value)
            g['xif_result_valid'] = int(self.dut.xif_commit_valid_o.value) and not int(self.dut.xif_commit_kill_o.value)
            self.dut.xif_result_valid_i.value = g['xif_result_valid']
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
                        dcsr=c.words[0x7B0], dpc=c.words[0x7B1],
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
        for kind in (0, 1, 2, 6 if self.params["XIF"] else 3):
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
        for kind in (0, 1, 2, 6 if self.params["XIF"] else 3):
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
            item = token(kind=self.rng.choice((0, 1, 2, 6 if self.params["XIF"] else 3)), result=self.rng.getrandbits(32),
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


class XIFTest(WBTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        if not self.params['XIF']:
            r = await self.cycle(token(kind=3), xif_result_valid=1, xif_result_we=1,
                                 xif_result_data=0xBAD, xif_kill_valid=1)
            assert r['exception_fire'] and not r['xif_commit_valid'] and not r['xif_result_ready']
        else:
            for n in range(96):
                rd = self.rng.randrange(16 if self.params['ISA_E'] else 32)
                pair = bool(self.params['XIF_DUALWRITE'] and n % 3 == 0)
                if pair:
                    rd &= ~1
                item = token(kind=3, xif_id=n % 8, rd=rd, rd_we=0)
                # Permission does not depend on controller/result readiness.
                r = await self.cycle(item, ready=0, xif_kill_valid=1, xif_kill_id=(n+1) % 8)
                assert r['xif_commit_valid'] and not r['xif_commit_kill'] and not r['valid']
                assert not r['xif_kill_ready']
                # One pending younger kill can pass while this WB waits.
                r = await self.cycle(item, ready=0, xif_kill_valid=1, xif_kill_id=(n+1) % 8)
                assert r['xif_kill_ready'] and r['xif_commit_kill']
                packet = dict(xif_result_valid=1, xif_result_id=n % 8,
                              xif_result_hartid=GLOBALS['hart_id'], xif_result_rd=rd,
                              xif_result_we=3 if pair else n % 2,
                              xif_result_data=self.rng.getrandbits(64 if self.params['XIF_DUALWRITE'] else 32))
                for _ in range(self.rng.randrange(1, 6)):
                    assert not (await self.cycle(item))['xif_commit_valid']
                # Neither a foreign hart nor a younger ID can complete WB.
                for bad in (dict(xif_result_id=(n+1) % 8), dict(xif_result_hartid=0)):
                    r = await self.cycle(item, **dict(packet, **bad))
                    assert not r['valid'] and r['xif_result_ready'] and not r['we0']
                for _ in range(self.rng.randrange(1, 5)):
                    r = await self.cycle(item, ready=0, **packet)
                    assert r['valid'] and not r['retire'] and not r['we0'] and not r['we1']
                before = self.model.csr.instret
                r = await self.cycle(item, **packet)
                assert r['retire'] and r['xif_result_ready'] and not r['xif_commit_valid']
                assert self.model.csr.instret == before + 1
                assert bool(r['we1']) == bool(pair and rd)
                assert r['result_valid'] == bool(packet['xif_result_we'] & 1 and rd)
            # First-cycle completion is legal with simultaneous permission.
            r = await self.cycle(token(kind=3, rd=2, xif_id=7), comb_result=True,
                                 xif_result_id=7, xif_result_rd=2, xif_result_we=1,
                                 xif_result_data=0xDEADBEEF)
            assert r['retire'] and r['xif_commit_valid'] and r['we0']
            # A pre-permission owning flush kills without waiting for a result.
            r = await self.cycle(token(kind=3, xif_id=1), flush=1)
            assert r['xif_commit_valid'] and r['xif_commit_kill'] and not r['retire']
            # Existing core exception sends kill instead of commit permission.
            r = await self.cycle(token(kind=3, xif_id=2, exception_valid=1, exception_cause=2))
            assert r['exception_fire'] and r['xif_commit_kill'] and not r['xif_result_ready']
            # Malformed destinations must never silently modify core state.
            malformed = [dict(rd=2, xif_result_rd=3, xif_result_we=1)]
            if self.params['ISA_E']:
                malformed.append(dict(rd=16, xif_result_rd=16, xif_result_we=1))
            if self.params['XIF_DUALWRITE']:
                malformed.extend((dict(rd=3, xif_result_rd=3, xif_result_we=3),
                                  dict(rd=2, xif_result_rd=2, xif_result_we=2)))
            for packet in malformed:
                rd = packet.pop('rd')
                r = await self.cycle(token(kind=3, rd=rd), xif_result_valid=1, **packet)
                assert r['xif_commit_valid'] and not r['valid'] and not r['exception_valid']
                assert r['xif_result_ready'] and not r['we0'] and not r['we1']
                # A violated external protocol is recovered by coordinated reset,
                # not by turning the packet into a coprocessor execution trap.
                await self.cycle(rst_n=0, valid=0)
            # Reset wins over all standard-channel activity.
            r = await self.cycle(token(kind=3), rst_n=0, xif_result_valid=1, xif_kill_valid=1)
            assert not r['xif_commit_valid'] and not r['xif_result_ready']
        self.report('XIF')
        self.drop_objection()


class DebugTest(WBTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        # Debug CSRs are inaccessible outside Debug Mode, even in M.
        for a in range(0x7B0, 0x7B4):
            assert (await self.csr(a, op=2, zero=1))['exception_fire']
        if not self.params['DEBUG']:
            assert not (await self.cycle(valid=0, debug_enter=1, debug_pc=0x1000))['debug_enter']
            assert (await self.cycle(token(kind=4), debug_mode=1))['exception_fire']
        else:
            await self.csr(0x340, 0x12345678, rd=0)
            saved = {a: self.model.csr.words[a] for a in (0x300, 0x341, 0x342, 0x343)}
            # Already-arbitrated external entry wins over a defensive IRQ collision.
            r = await self.cycle(valid=0, flush=1, debug_enter=1, debug_pc=0x12346,
                                 debug_cause=3, trap=1, trap_pc=0xBAD, priv_m=0 if self.params['ISA_UMODE'] else 1)
            assert r['debug_enter'] and not r['retire']
            assert saved == {a: self.model.csr.words[a] for a in saved}
            assert self.model.csr.words[0x7B0] >> 6 & 7 == 3
            debug = dict(debug_mode=1)
            before = self.model.csr.cycle, self.model.csr.instret
            for _ in range(8):
                await self.cycle(**debug)
            assert before == (self.model.csr.cycle, self.model.csr.instret)
            # WARL constants/cause survive all-ones writes, then restore controls.
            await self.csr(0x7B0, 0xFFFFFFFF, **debug)
            value = self.model.csr.words[0x7B0]
            assert value & 0x40000410 == 0x40000410 and not value & (1 << 11)
            assert value >> 6 & 7 == 3 and not value & (1 << 9)
            await self.csr(0x7B1, 0xABCDEF03, **debug)
            assert self.model.csr.words[0x7B1] == (0xABCDEF02 if self.params['ISA_C'] else 0xABCDEF00)
            await self.csr(0x7B2, 0xDEADBEEF, **debug)
            assert (await self.csr(0x7B2, op=2, zero=1, **debug))['wdata0'] == 0xDEADBEEF
            assert (await self.csr(0x7B3, **debug))['debug_exception']
            # Explicit counter writes remain usable while implicit counts stop.
            await self.csr(0xB00, 100, **debug)
            await self.csr(0xB02, 200, **debug)
            assert (await self.csr(0xB00, op=2, zero=1, **debug))['wdata0'] == 100
            assert self.model.csr.instret == 200
            # Debug exceptions and EBREAK terminate debug code without trap CSR writes.
            saved = {a: self.model.csr.words[a] for a in (0x300, 0x341, 0x342, 0x343, 0x7B0, 0x7B1)}
            r = await self.cycle(token(exception_valid=1, exception_cause=5, exception_tval=0xBAD), **debug)
            assert r['debug_exception'] and not r['exception_fire'] and not r['retire']
            r = await self.cycle(token(kind=5), **debug)
            assert r['debug_ebreak'] and not r['debug_enter'] and not r['retire']
            assert saved == {a: self.model.csr.words[a] for a in saved}
            # Resume with step set, returning to U when implemented. DRET clears MPRV.
            await self.csr(0x300, 1 << 17, **debug)
            await self.csr(0x7B0, 0x9004 if self.params['ISA_UMODE'] else 0x8007, **debug)
            r = await self.cycle(token(kind=4), **debug)
            assert r['dret'] and not r['mret'] and not r['we0']
            assert not self.model.csr.words[0x300] & (1 << 17)
            before = self.model.csr.instret
            await self.cycle(token(result=42, rd=3))
            assert self.model.csr.instret == before + 1
            # Parent supplies actual next PC, including branch/trap targets, on step reentry.
            await self.cycle(valid=0, debug_enter=1, debug_pc=0x9000, debug_cause=4)
            assert self.model.csr.words[0x7B1] == 0x9000
            # Enable ebreak M/U and return. Accepted breakpoint entry itself freezes counters.
            await self.csr(0x7B0, 0x9003, **debug)
            await self.cycle(token(kind=4), **debug)
            for priv in ((1, 0) if self.params['ISA_UMODE'] else (1,)):
                before = self.model.csr.cycle, self.model.csr.instret
                r = await self.cycle(token(kind=5, pc=0x8002), priv_m=priv)
                assert r['debug_enter'] and not r['exception_fire'] and not r['retire']
                assert before == (self.model.csr.cycle, self.model.csr.instret)
                assert self.model.csr.words[0x7B0] >> 6 & 7 == 1
                await self.cycle(token(kind=4), **debug)
            # With ebreak controls clear, the same instruction is a normal breakpoint trap.
            await self.cycle(valid=0, debug_enter=1, debug_pc=0xA000)
            await self.csr(0x7B0, 3, **debug)
            await self.cycle(token(kind=4), **debug)
            r = await self.cycle(token(kind=5, pc=0x5000))
            assert r['exception_fire'] and r['exception_cause'] == 3 and not r['debug_enter']
            assert r['exception_tval'] == 0
        self.report('Debug')
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def xif(_dut):
    await uvm_root().run_test(XIFTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def debug(_dut):
    await uvm_root().run_test(DebugTest)


class MemoryTest(WBTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        for store in (False, True):
            item = token(rd_we=int(not store), result=0x1000, pc=0x9000)
            for _ in range(4):
                r = await self.cycle(item, lsu=1)
                assert not r['valid'] and not r['retire'] and not r['result_valid']
            # Raw bus response can retire/write at this edge, never bypass.
            r = await self.cycle(item, lsu=1, lsu_res_valid=1, lsu_res_data=0xDEADBEEF)
            assert r['retire'] and not r['result_valid']
            assert r['wdata0'] == (0 if store else 0xDEADBEEF)
            # A response held by the LSU becomes a registered forwarding source.
            for ready in (0, 0, 1):
                r = await self.cycle(item, lsu=1, lsu_res_valid=1, lsu_res_registered=1,
                                     lsu_res_data=0x89ABCDEF, ready=ready)
                assert r['result_valid'] == int(not store)
            r = await self.cycle(item, lsu=1, lsu_res_valid=1, lsu_res_exception_valid=1,
                lsu_res_exception_cause=7 if store else 5, lsu_res_exception_tval=0x1000, ready=0)
            assert r['exception_valid'] and not r['exception_fire'] and not r['we0']
            r = await self.cycle(item, lsu=1, lsu_res_valid=1, lsu_res_registered=1,
                lsu_res_exception_valid=1, lsu_res_exception_cause=7 if store else 5,
                lsu_res_exception_tval=0x1000)
            assert r['exception_fire'] and not r['retire']
            assert self.model.csr.words[0x341] == 0x9000
        self.drop_objection()


@cocotb.test()
async def memory(_dut):
    await uvm_root().run_test(MemoryTest)
