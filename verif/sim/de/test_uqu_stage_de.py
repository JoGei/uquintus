"""DE native execution intent, readiness, early faults and standard XIF issue."""
import itertools
import json
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from de_model import DEModel, inputs
from decode_model import RULES, decode
from compressed_model import expand


def word(opcode=0x33, rd=3, rs1=1, rs2=2, funct3=0, upper=0):
    return upper << 25 | rs2 << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode


class DETest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.p = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.model = DEModel(self.p)
        self.rng = random.Random(int(os.environ['RANDOM_SEED']))
        self.checks = 0

    async def compare(self, i):
        expected = self.model.evaluate(i)
        for name, value in expected.items():
            actual = int(getattr(self.dut, name+'_o').value)
            assert actual == value, (name, hex(actual), hex(value), i, self.model.__dict__)
        self.checks += 1
        return expected

    async def check(self, i=None, edge=False, **changes):
        i = inputs(**changes) if i is None else dict(i, **changes)
        self.dut.clk_i.value = 0
        for name, value in i.items():
            getattr(self.dut, 'rst_ni' if name == 'rst_n' else name+'_i').value = value
        await Timer(1, units='ns')
        before = await self.compare(i)
        if edge:
            self.dut.clk_i.value = 1
            self.model.edge(i)
            await Timer(1, units='ns')
            await self.compare(i)
        return before

    async def reset(self):
        await self.check(rst_n=0, edge=True)

    def report(self):
        self.logger.info('%d DE observations checked: %s', self.checks, self.p)


class NativeTest(DETest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        hits = set()
        for rule in RULES:
            for _ in range(24):
                encoding = (self.rng.getrandbits(32) & ~rule.mask) | rule.match
                d, name = decode(encoding, self.p)
                if name and not d['illegal']:
                    hits.add(name)
                await self.check(instr=encoding, original_instr=encoding,
                    pc=self.rng.getrandbits(30)*4, rs0=self.rng.getrandbits(32),
                    rs1=self.rng.getrandbits(32), rs2=self.rng.getrandbits(32))
        # Independent checks on the most important payload bindings.
        r = await self.check(instr=word(), rs0=10, rs1=20)
        assert (r['a'], r['b'], r['rd'], r['fu']) == (10, 20, 3, 0)
        r = await self.check(instr=word(0x23, rd=0, funct3=2), rs0=0x1000, rs1=0xBEEF)
        assert r['lsu'] and r['mem_we'] and r['b'] == 0 and r['store_data'] == 0xBEEF
        r = await self.check(instr=word(0x73, funct3=2), rs0=0)
        assert r['wb_kind'] == 1 and r['csr_src'] == 0 and not r['csr_src_zero']
        r = await self.check(instr=word(0x73, rs1=0, funct3=2), rs0=0xBAD)
        assert r['csr_src_zero']
        if self.p['ISA_C']:
            r = await self.check(instr=0x000000EF, original_instr=0x2001,
                                 compressed=1, pc=0x1002)
            assert r['pass_data'] == 0x1004
        self.logger.info('Legal native classes reached: %s', sorted(hits))
        self.report()
        self.drop_objection()


class HazardsTest(DETest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        for encoding in (word(), word(0x23, rd=4, funct3=2), 0x00208463,
                         0x000080E7, word(0x73, funct3=1),
                         word(0x73, funct3=5), word(0x43, upper=0x0C)):
            for ready, guaranteed in itertools.product(range(8), repeat=2):
                for downstream in (0, 1):
                    await self.check(instr=encoding, rs_ready=ready,
                                     rs_ex_guaranteed=guaranteed, ready=downstream)
        # Native ALU sources can rely on a future EX bypass, but branches/CSRs
        # must have their values in DE. No fault waits for ordinary sources.
        r = await self.check(instr=word(), rs_ready=0, rs_ex_guaranteed=3)
        assert r['valid'] and r['rs_captured'] == 0 and not r['a'] and not r['b']
        r = await self.check(instr=0x00208463, rs_ready=0, rs_ex_guaranteed=7)
        assert not r['valid'] and not r['branch_resolve']
        r = await self.check(instr=word(0x73, funct3=1), rs_ready=0, rs_ex_guaranteed=7)
        assert not r['valid']
        r = await self.check(instr=word(), exception_valid=1, exception_cause=1,
                             exception_tval=0xDEAD, rs_ready=0)
        assert r['valid'] and r['exception_valid'] and r['rs_used'] == 0
        self.report()
        self.drop_objection()


class CompressedTest(DETest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        if not self.p['ISA_C']:
            for raw in (0x0085, 0x9002, 0x9082, 0):
                r = await self.check(instr=raw, original_instr=raw, compressed=1)
                assert r['exception_valid'] and r['exception_cause'] == 2
            self.drop_objection()
            return
        expand_if = self.p['MUA_C_IMPL'] == 0 and self.p['MUA_C_DECOMPRESS_STAGE'] == 0
        for index in range(2048):
            raw = self.rng.getrandbits(16)
            raw = raw & ~3 | (index % 3)
            expanded, _ = expand(raw, True)
            fetch_fault = index % 13 == 0
            i = inputs(instr=expanded['instr'] if expand_if else raw,
                original_instr=raw, compressed=1, pc=0x1002,
                rs0=self.rng.getrandbits(32), rs1=self.rng.getrandbits(32),
                rs_ready=self.rng.randrange(8), rs_ex_guaranteed=self.rng.randrange(8),
                permit=self.rng.randrange(2), ready=self.rng.randrange(2),
                exception_valid=int(fetch_fault or expand_if and expanded['illegal']),
                exception_cause=1 if fetch_fault else 2,
                exception_tval=0x2000 if fetch_fault else raw)
            r = await self.check(i)
            assert not r['xif_issue_valid']  # No raw 16-bit offload on the 32-bit issue channel.
            if fetch_fault:
                assert r['exception_valid'] and r['exception_cause'] == 1
                assert r['exception_tval'] == 0x2000
            elif expanded['illegal']:
                assert r['exception_valid'] and r['exception_cause'] == 2
                assert r['exception_tval'] == raw
        # Illegal native E operands remain native faults, never XIF overrides.
        for raw in (0x0805, 0x0801, 0x0842, 0xC042):
            expanded, _ = expand(raw, True)
            r = await self.check(instr=expanded['instr'] if expand_if else raw,
                                 original_instr=raw, compressed=1)
            assert not r['xif_issue_valid']
            assert bool(r['exception_valid']) == bool(self.p['ISA_E'])
        self.report()
        self.drop_objection()


class ControlTest(DETest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        for instr in (0x73, 0x00100073, 0x30200073, 0x7B200073, 0x10500073,
                      0x0000000F, 0x0000100F, 0x000000EF, 0x000080E7):
            for machine, debug, tw, permit, ready in itertools.product(range(2), repeat=5):
                await self.check(instr=instr, priv_m=machine, debug_mode=debug, tw=tw,
                                 permit=permit, ready=ready, rs0=0x2002)
        # Misalignment belongs to the branch instruction, while its target is
        # retained for mtval. An untaken branch must not fault on its target.
        r = await self.check(instr=0x00208063, rs0=1, rs1=1, pc=0x1002)
        assert bool(r['exception_valid']) == bool(not self.p['ISA_C'])
        await self.check(instr=0x00208063, rs0=1, rs1=2, pc=0x1002)
        # Resolution is qualified by transfer, never repeated while held.
        for _ in range(8):
            r = await self.check(instr=0x000000EF, ready=0, edge=True)
            assert not r['branch_resolve']
        r = await self.check(instr=0x000000EF, ready=1, edge=True)
        assert r['branch_resolve']
        await self.check(valid=0, edge=True)
        for fault in (0, 1):
            for permit, flush in itertools.product(range(2), repeat=2):
                await self.check(instr=0x73, exception_valid=fault, exception_cause=5,
                                 exception_tval=0xBAD, permit=permit, flush=flush, rs_ready=0)
        if self.p['ISA_ZFINX']:
            for frm in range(8):
                r = await self.check(instr=word(0x53, funct3=7), frm=frm)
                assert bool(r['exception_valid']) == bool(frm > 4)
        # Illegal-instruction diagnostics retain original, not expanded bits.
        await self.check(instr=0, original_instr=0xDEAD1234, compressed=1)
        self.report()
        self.drop_objection()


class XIFTest(DETest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        custom = word(0x0B, rd=4)
        if not self.p['XIF']:
            r = await self.check(instr=custom, xif_issue_ready=1, xif_issue_accept=1,
                                 xif_register_ready=1, edge=True)
            assert r['exception_valid'] and not r['xif_issue_valid']
            self.report()
            self.drop_objection()
            return
        # Backpressure with partial operands, then producer departure. Already
        # presented rs_valid/data must remain stable in continuous hazard mode.
        i = inputs(instr=custom, ready=0, rs_ready=1)
        r = await self.check(i, edge=True)
        assert r['xif_issue_valid'] and r['xif_register_rs_valid'] == 1
        r = await self.check(i, rs_ready=0, rs0=0xBAD, edge=True)
        assert r['xif_register_rs_valid'] == 1 and r['xif_register_rs'] & 0xFFFFFFFF == i['rs0']
        for _ in range(4):
            await self.check(i, rs_ready=3, edge=True)
        # Handshake response is sampled once. Acceptance does not depend on
        # EX capacity, and unused rs3 does not need to become ready.
        accepted = dict(i, rs_ready=3, xif_issue_ready=1, xif_register_ready=1,
                        xif_issue_accept=1, xif_issue_register_read=3,
                        xif_issue_writeback=1)
        await self.check(accepted, edge=True)
        for _ in range(5):
            r = await self.check(accepted, rs_ready=0, edge=True)
            assert r['xif_issued'] and r['xif_accepted'] and not r['xif_issue_valid']
            assert r['valid'] and r['wb_kind'] == 3 and not r['exception_valid']
        await self.check(accepted, ready=1, edge=True)
        await self.check(valid=0, edge=True)
        # Rejections require a standard kill notification too. Hold the fault
        # until parent/WB acknowledges cleanup; never repeat the issue.
        rejected = inputs(instr=custom, ready=0, xif_issue_ready=1,
                          xif_register_ready=1, xif_cleanup_ready=0)
        await self.check(rejected, edge=True)
        r = await self.check(rejected, edge=True)
        assert r['exception_valid'] and r['xif_cleanup_valid'] and not r['valid']
        r = await self.check(rejected, xif_cleanup_ready=1, edge=True)
        assert r['valid'] and r['exception_valid']
        await self.check(rejected, xif_cleanup_ready=0, ready=1, edge=True)
        await self.check(valid=0, edge=True)
        # Every advertised destination mode, including ignored x0/x1 pair,
        # odd paired destinations, and RV32E boundary violations.
        for destination in (0, 2, 3, 14, 15, 16, 30, 31):
            for writeback in range(1 << (1+self.p['XIF_DUALWRITE'])):
                await self.reset()
                req = inputs(instr=word(0x0B, rd=destination), ready=0,
                    xif_issue_ready=1, xif_register_ready=1, xif_issue_accept=1,
                    xif_issue_writeback=writeback)
                await self.check(req, edge=True)
                r = await self.check(req, xif_cleanup_ready=0)
                bad = bool(writeback & 2 and destination % 2 or
                           self.p['ISA_E'] and writeback and destination >= 16)
                assert bool(r['exception_valid']) == bad
        # Used-register checks must not reject literal/unused high fields.
        # An E-aware coprocessor rejects a used high source; defensively kill
        # any response which accepts it instead, even if it claims data ready.
        if self.p['ISA_E']:
            for used, accepted in ((0,1),(1,0),(1,1)):
                await self.reset()
                req = inputs(instr=word(0x0B, rd=4, rs1=31), ready=0,
                    xif_issue_ready=1, xif_register_ready=1,
                    xif_issue_register_read=used, xif_issue_accept=accepted)
                await self.check(req, edge=True)
                r = await self.check(req, xif_cleanup_ready=0)
                assert bool(r['exception_valid']) == bool(used)
                assert bool(r['xif_cleanup_valid']) == bool(used)
        # A coprocessor may not accept an operand it still lacks. Defensive
        # rejection containment must not let stale source bits reach execution.
        await self.reset()
        req = inputs(instr=custom, ready=0, rs_ready=0, xif_issue_ready=1,
            xif_register_ready=1, xif_issue_register_read=1, xif_issue_accept=1)
        await self.check(req, edge=True)
        r = await self.check(req, xif_cleanup_ready=0)
        assert r['exception_valid'] and r['xif_cleanup_valid'] and not r['rd_pending']
        # IF can mark an extension-expanded compressed instruction for offload
        # even if its expansion matches an ordinary native instruction.
        await self.reset()
        forced = inputs(instr=word(0x13, rd=4), original_instr=0x6001,
            compressed=1, xif_force=1, ready=0, xif_issue_ready=1,
            xif_register_ready=1, xif_issue_accept=1, xif_issue_writeback=1)
        r = await self.check(forced, edge=True)
        if self.p['ISA_C']:
            assert r['xif_issue_valid'] and not r['native']
            r = await self.check(forced)
            assert r['wb_kind'] == 3 and r['next_pc'] == 0x1002
        else:
            assert r['exception_valid'] and not r['xif_issue_valid']
        # No issue on a prior fetch fault, native E violation, drain or flush.
        await self.reset()
        for values in (dict(exception_valid=1), dict(permit=0), dict(flush=1), dict(xif_id_valid=0)):
            r = await self.check(instr=custom, **values)
            assert not r['xif_issue_valid']
        # Flush exposes accepted-ID status before the edge for parent kills,
        # then drops local tracking. The parent owns the actual kill arbiter.
        req = inputs(instr=custom, ready=0, xif_issue_ready=1, xif_register_ready=1,
                     xif_issue_accept=1)
        await self.check(req, edge=True)
        r = await self.check(req, flush=1, edge=True)
        assert r['xif_issued'] and not r['valid'] and not r['xif_issue_valid']
        await self.check(valid=0, edge=True)
        self.report()
        self.drop_objection()


class RandomizedTest(DETest):
    async def run_phase(self):
        self.raise_objection()
        await self.reset()
        for _ in range(5000):
            rule = self.rng.choice(RULES)
            instr = ((self.rng.getrandbits(32) & ~rule.mask) | rule.match
                     if self.rng.randrange(4) else self.rng.getrandbits(32))
            await self.check(instr=instr, original_instr=self.rng.getrandbits(32),
                pc=self.rng.getrandbits(32) & ~1, compressed=self.rng.randrange(2),
                rs0=self.rng.getrandbits(32), rs1=self.rng.getrandbits(32), rs2=self.rng.getrandbits(32),
                rs_ready=self.rng.randrange(8), rs_ex_guaranteed=self.rng.randrange(8),
                valid=self.rng.randrange(2), ready=self.rng.randrange(2), permit=self.rng.randrange(2),
                flush=int(self.rng.randrange(16) == 0), priv_m=self.rng.randrange(2),
                debug_mode=self.rng.randrange(2), tw=self.rng.randrange(2), frm=self.rng.randrange(8),
                exception_valid=int(self.rng.randrange(16) == 0), exception_cause=self.rng.randrange(32),
                exception_tval=self.rng.getrandbits(32))
        self.report()
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def native(_dut):
    await uvm_root().run_test(NativeTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def hazards(_dut):
    await uvm_root().run_test(HazardsTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def compressed(_dut):
    await uvm_root().run_test(CompressedTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def control(_dut):
    await uvm_root().run_test(ControlTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def xif(_dut):
    await uvm_root().run_test(XIFTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)
