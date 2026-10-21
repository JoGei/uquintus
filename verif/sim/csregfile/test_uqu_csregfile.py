"""CSR accesses, implicit events, and optional storage against architectural words."""

import json
import os
import random
from pathlib import Path
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from csregfile_model import CSRModel, INPUTS, MASK


class CSRTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.model = CSRModel(self.params)
        self.checks = 0
        self.rng = random.Random(int(os.environ['RANDOM_SEED']) ^ 0x435352)

    def observe(self, i):
        expected = dict(mstatus=self.model.words[0x300], mie=self.model.words[0x304],
                        mip=(i['irq_software'] << 3) | (i['irq_timer'] << 7) | (i['irq_external'] << 11),
                        mtvec=self.model.words[0x305], mepc=self.model.words[0x341],
                        frm=self.model.words[2], fflags=self.model.words[1],
                        dcsr=self.model.words[0x7B0], dpc=self.model.words[0x7B1],
                        pmpcfg=sum(c << (8*n) for n, c in enumerate(self.model.configs)))
        for name, value in expected.items():
            actual = int(getattr(self.dut, name + '_o').value)
            assert actual == value, f'{name}: expected {value:#x}, actual {actual:#x}; inputs={i}'
        # Do not resolve uninitialized payloads belonging to other entries on
        # four-state simulators; only initialized address slices are defined.
        raw_addresses = self.dut.pmpaddr_o.value.binstr
        for entry, address in enumerate(self.model.addresses):
            if not self.params['ISA_PMP']:
                address = 0
            if address is not None:
                high = len(raw_addresses) - 32*entry
                actual = int(raw_addresses[high-32:high], 2)
                assert actual == address, (entry, address, actual)

    async def cycle(self, **signals):
        i = dict(INPUTS, **signals)
        for name, value in i.items():
            getattr(self.dut, 'rst_ni' if name == 'rst_n' else name + '_i').value = value
        await Timer(1, units='ns')
        expected, _ = self.model.query(i)
        for name, value in expected.items():
            if value is not None:
                actual = int(getattr(self.dut, 'csr_' + name + '_o').value)
                assert actual == value, f'CSR {name}: expected {value:#x}, actual {actual:#x}; inputs={i}'
        self.dut.clk_i.value = 1
        await Timer(1, units='ns')
        self.dut.clk_i.value = 0
        self.model.step(i)
        await Timer(1, units='ns')
        self.observe(i)
        self.checks += 1
        return expected

    async def initialize(self):
        self.dut.clk_i.value = 0
        await self.cycle(rst_n=0, csr_valid=1, csr_commit=1, csr_op=1, csr_addr=0x340,
                         csr_src=MASK, trap=1, mret=1, retire=1, fp_flags_valid=1, fp_flags=31)
        # Address payloads are deliberately unreset; initialize them before use.
        if self.params['ISA_PMP']:
            for entry in range(16):
                await self.write(0x3B0+entry, 0x1000+entry*0x400, rd_zero=1)

    async def read(self, addr, **kwargs):
        return await self.cycle(csr_valid=1, csr_addr=addr, **kwargs)

    async def write(self, addr, value, op=1, rd_zero=0, **kwargs):
        return await self.cycle(csr_valid=1, csr_commit=1, csr_addr=addr, csr_op=op,
                                csr_src=value, csr_src_zero=0, csr_rd_zero=rd_zero, **kwargs)

    def report(self, name):
        self.logger.info('%s CSR cycle checks: %d, parameters=%s', name, self.checks, self.params)


class DirectedTest(CSRTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        # Exhaust the 12-bit address map in both privileges, including every
        # reserved hole, absent feature, machine CSR and constant-zero alias.
        for privilege in (1, 0):
            for address in range(4096):
                await self.read(address, priv_m=privilege)
        # All six Zicsr forms, source values versus source *encoding*, and rd=x0.
        for address in (0x340, 0x300, 0x305, 0x301, 0x344, 0xF14, 0xC00, 0x100, 3):
            for op in range(8):
                for source, zero in ((0, 1), (0, 0), (31, 0), (MASK, 0)):
                    for rd_zero in (0, 1):
                        await self.cycle(csr_valid=1, csr_commit=1, csr_addr=address,
                                         csr_op=op, csr_src=source, csr_src_zero=zero,
                                         csr_rd_zero=rd_zero)
        # All writable status fields; unsupported MPP values map to M.
        for mpp in range(4):
            await self.write(0x300, (MASK & ~0x1800) | (mpp << 11))
            expected = (0x88 | 0x220000 | (0 if mpp == 0 else 0x1800)) if self.params['ISA_UMODE'] else 0x1888
            assert int(self.dut.mstatus_o.value) == expected
        for mode in range(4):
            for base in (0, 0x12345678, 0xFFFFFFFC):
                await self.write(0x305, base | mode)
                assert int(self.dut.mtvec_o.value) == base | int(mode == 1)
        for pc in (0, 1, 2, 3, 0xFFFFFFFF):
            await self.write(0x341, pc)
            assert int(self.dut.mepc_o.value) == pc & (~1 if self.params['ISA_C'] else ~3)
        # Writes to hardwired zero banks are legal machine accesses, not storage.
        for address in list(range(0x323, 0x340)) + list(range(0xB03, 0xB20)) + list(range(0xB83, 0xBA0)):
            await self.write(address, MASK)
            assert (await self.read(address))['rdata'] == 0
        for value in (0, 5, MASK):
            await self.write(0x306, value)
            for address in (0xC00, 0xC80, 0xC02, 0xC82, 0xC03, 0xC83, 0xC01, 0xC81):
                await self.read(address, priv_m=0)
        for levels in range(8):
            irq = dict(irq_software=levels & 1, irq_timer=(levels >> 1) & 1,
                       irq_external=(levels >> 2) & 1)
            await self.write(0x304, MASK, **irq)
            await self.write(0x344, MASK, **irq)
            await self.read(0x344, **irq)
        # Held evaluation, discarded writes, and stale control without valid.
        original = self.model.words[0x340]
        for _ in range(8):
            await self.cycle(csr_valid=1, csr_addr=0x340, csr_op=1, csr_src=123, csr_src_zero=0)
            assert self.model.words[0x340] == original
        await self.write(0x340, MASK, flush=1)
        await self.cycle(csr_commit=1, csr_addr=0x340, csr_op=1, csr_src=MASK)
        assert self.model.words[0x340] == original
        await self.cycle(rst_n=0)
        await self.read(0x300)
        self.report('Directed')
        self.drop_objection()


class CountersTest(CSRTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        await self.write(0x320, 5)
        for low, high in ((0xB00, 0xB80), (0xB02, 0xB82)):
            await self.write(high, MASK)
            await self.write(low, MASK)
        for _ in range(10):
            await self.cycle(retire=1)
        assert self.model.cycle == self.model.instret == (1 << 64)-1
        await self.write(0x320, 0, retire=1)
        await self.cycle(retire=1)
        assert self.model.cycle == self.model.instret == 0
        # Explicit half writes suppress increment/retirement for that counter.
        await self.write(0xB80, 0x12345678, retire=1)
        await self.write(0xB00, MASK, retire=1)
        assert self.model.cycle == 0x12345678FFFFFFFF
        await self.cycle(retire=1)
        assert self.model.cycle == 0x1234567900000000
        await self.write(0xB82, 0xABCDEF12, retire=1)
        await self.write(0xB02, MASK, retire=1)
        assert self.model.instret == 0xABCDEF12FFFFFFFF
        await self.cycle(retire=1)
        assert self.model.instret == 0xABCDEF1300000000
        for inhibit in (0, 1, 4, 5):
            await self.write(0x320, inhibit)
            for _ in range(12):
                for address in (0xB00, 0xB80, 0xB02, 0xB82, 0xC00, 0xC80, 0xC02, 0xC82):
                    await self.read(address, retire=self.rng.randrange(2))
        # An invalid/flushed access cannot inhibit or explicitly change counters.
        await self.write(0x320, MASK, priv_m=0)
        await self.write(0xB00, 17, flush=1, retire=1)
        await self.read(0xB00)
        self.report('Counters')
        self.drop_objection()


class EventsTest(CSRTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        for privilege in (1, 0) if self.params['ISA_UMODE'] else (1,):
            for mie in (0, 1):
                for interrupt, causes in ((0, (0, 1, 2, 3, 4, 5, 6, 7, 8, 11)), (1, (3, 7, 11))):
                    for cause in causes:
                        await self.write(0x300, (mie << 3) | (1 << 17) | (1 << 21))
                        await self.cycle(trap=1, trap_pc=0x1234567B, trap_interrupt=interrupt,
                                         trap_cause=cause, trap_tval=0xDEADBEEF, priv_m=privilege,
                                         mret=1, csr_valid=1, csr_commit=1, csr_addr=0x340,
                                         csr_op=1, csr_src=MASK, csr_src_zero=0)
                        assert self.model.words[0x340] == 0
                        assert (await self.read(0x342))['rdata'] == (interrupt << 31) | cause
                        await self.read(0x343)
                        await self.cycle(mret=1, retire=1)
                        assert bool(self.model.words[0x300] & 8) == bool(mie)
                        if self.params['ISA_UMODE'] and not privilege:
                            assert not int(self.dut.mstatus_o.value) & (1 << 17)
        # MRET has priority over a coincident ordinary CSR write.
        await self.write(0x340, MASK, mret=1)
        assert self.model.words[0x340] == 0
        if self.params['ISA_UMODE']:
            await self.cycle(mret=1, priv_m=0)
        if self.params['DEBUG']:
            await self.write(0x300, 8)
            saved = {a: self.model.words[a] for a in (0x300, 0x341, 0x342, 0x343)}
            # An already accepted debug entry excludes both machine trap/MRET
            # effects even under defensive event collisions and owning flush.
            await self.cycle(debug_enter=1, debug_pc=0x1234567A, debug_cause=3,
                             trap=1, trap_pc=0xBAD, mret=1, flush=1)
            assert saved == {a: self.model.words[a] for a in saved}
            assert (await self.read(0x7B0, debug_mode=1))['rdata'] >> 6 & 7 == 3
            await self.cycle(debug_mode=1, dret=1)
        # Accrued flags, aliases, explicit-write priority and independent frm.
        for flags in (1, 2, 4, 8, 16):
            await self.cycle(fp_flags_valid=1, fp_flags=flags)
        assert int(self.dut.fflags_o.value) == (31 if self.params['ISA_ZFINX'] else 0)
        for value in (0, 0xA5, MASK):
            await self.write(3, value)
            await self.read(1)
            await self.read(2)
            await self.read(3)
        await self.write(1, 0, fp_flags_valid=1, fp_flags=31)
        await self.write(2, 4, fp_flags_valid=1, fp_flags=3)
        await self.cycle(flush=1, fp_flags_valid=1, fp_flags=16)
        await self.read(3, priv_m=0)
        self.report('Events')
        self.drop_objection()


class PMPTest(CSRTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        # All words/entries, six real cfg bits, and reserved permission mapping.
        for pattern in (0, 0x1A1A1A1A, 0x7F7F7F7F, 0x02020202):
            for address in range(0x3A0, 0x3A4):
                await self.write(address, pattern)
                await self.read(address)
        for entry in range(16):
            await self.write(0x3B0+entry, self.rng.getrandbits(32))
            await self.read(0x3B0+entry)
        # Locking an OFF entry locks its own address/configuration. Other
        # bytes in the same pmpcfg word must remain independently writable.
        await self.write(0x3A0, 0x80)
        await self.write(0x3B0, MASK)
        await self.write(0x3A0, MASK)
        if self.params['ISA_PMP']:
            assert self.model.configs[0] == 0x80
            assert self.model.configs[1] == 0x9F
        # Reset clears config/locks but preserves unreset address payloads.
        snapshot = list(self.model.addresses)
        await self.cycle(rst_n=0)
        if self.params['ISA_PMP']:
            assert self.model.addresses == snapshot
        # Each locked TOR region also freezes its predecessor's address.
        for entry in range(1, 16):
            await self.cycle(rst_n=0)
            await self.write(0x3B0+entry-1, entry*0x100)
            await self.write(0x3B0+entry, entry*0x100+0x80)
            await self.write(0x3A0+entry//4, 0x88 << (8*(entry%4)))
            await self.write(0x3B0+entry-1, MASK)
            await self.write(0x3B0+entry, MASK)
            await self.write(0x3A0+entry//4, 0)
            if self.params['ISA_PMP']:
                assert self.model.addresses[entry-1] == entry*0x100
                assert self.model.configs[entry] == 0x88
        # Every disabled address remains a legal machine zero CSR; later
        # unimplemented entries/config words are unmapped, not aliases.
        for address in (0x3A4, 0x3AF, 0x3C0, 0x3EF):
            assert (await self.read(address))['exception_valid']
        for address in (0x3A0, 0x3A3, 0x3B0, 0x3BF):
            assert (await self.read(address, priv_m=0))['exception_valid']
        self.report('PMP')
        self.drop_objection()


class RandomizedTest(CSRTest):
    async def run_phase(self):
        self.raise_objection()
        await self.initialize()
        addresses = [0x001, 0x002, 0x003, 0x300, 0x301, 0x304, 0x305, 0x306,
                     0x310, 0x320, 0x340, 0x341, 0x342, 0x343, 0x344,
                     0xB00, 0xB80, 0xB02, 0xB82, 0xC00, 0xC02, 0xC01,
                     0xF11, 0xF14, 0x7B0] + list(range(0x3A0, 0x3A4)) + list(range(0x3B0, 0x3C0))
        for _ in range(4096):
            i = dict(csr_valid=int(self.rng.randrange(8) != 0), csr_commit=self.rng.randrange(2),
                     csr_addr=self.rng.choice(addresses), csr_op=self.rng.randrange(8),
                     csr_src=self.rng.getrandbits(32), csr_src_zero=self.rng.randrange(2),
                     csr_rd_zero=self.rng.randrange(2), csr_instr=self.rng.getrandbits(32),
                     priv_m=self.rng.randrange(2) if self.params['ISA_UMODE'] else 1,
                     flush=int(self.rng.randrange(16) == 0), retire=self.rng.randrange(2),
                     irq_software=self.rng.randrange(2), irq_timer=self.rng.randrange(2),
                     irq_external=self.rng.randrange(2), trap=int(self.rng.randrange(32) == 0),
                     trap_pc=self.rng.getrandbits(32), trap_interrupt=self.rng.randrange(2),
                     trap_cause=self.rng.choice((0, 1, 2, 3, 4, 5, 6, 7, 8, 11)),
                     trap_tval=self.rng.getrandbits(32), mret=int(self.rng.randrange(32) == 0),
                     fp_flags_valid=self.rng.randrange(2), fp_flags=self.rng.randrange(32))
            await self.cycle(**i)
        # Read every mutable word after random traffic so an erroneous write
        # cannot remain hidden merely because the random test never read it.
        for address in addresses:
            await self.read(address)
        self.report('Randomized')
        self.drop_objection()


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def counters(_dut):
    await uvm_root().run_test(CountersTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def events(_dut):
    await uvm_root().run_test(EventsTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def pmp(_dut):
    await uvm_root().run_test(PMPTest)


@cocotb.test(timeout_time=1000, timeout_unit='us')
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)
