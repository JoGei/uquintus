"""Concurrent IF/MEM PMP permissions against a byte-by-byte interval model."""

import json
import os
import random
from pathlib import Path
import sys

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from pmp_model import OFF, TOR, NA4, NAPOT, LEGAL_PERMISSIONS, config, napot, region, permitted


class PMPTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.params = json.loads(os.environ['UQU_COMPONENT_PARAMS'])
        self.enabled = self.params['ISA_PMP']
        self.checks = 0

    async def check(self, configs, addresses, address, size, access, machine,
                    expected=None, if_request=None, if_expected=None):
        self.dut.pmpcfg_i.value = sum(cfg << (8 * i) for i, cfg in enumerate(configs))
        self.dut.pmpaddr_i.value = sum(addr << (32 * i) for i, addr in enumerate(addresses))
        self.dut.mem_addr_i.value = address
        self.dut.mem_size_i.value = size
        self.dut.mem_access_i.value = access
        self.dut.mem_priv_m_i.value = machine
        if_address, if_size, if_machine = if_request or (address, size, machine)
        self.dut.if_addr_i.value = if_address
        self.dut.if_size_i.value = if_size
        self.dut.if_priv_m_i.value = if_machine
        replay_address = address & ~3
        self.dut.replay_addr_i.value = replay_address
        self.dut.replay_priv_m_i.value = machine
        await Timer(1, units='ns')
        replay_model = sum(int(permitted(self.enabled, configs, addresses, (replay_address+4*k)&0xffffffff,
                                         2, 4, machine) if self.params['MUA_BTB_IDATA_DEPTH'] and
                                         (k == 0 or self.params['ISA_C']) else True) << k for k in range(2))
        assert int(self.dut.replay_allow_o.value) == replay_model
        mem_model = permitted(self.enabled, configs, addresses, address, size, access, machine)
        if_model = permitted(self.enabled, configs, addresses, if_address, if_size, 4, if_machine)
        if self.enabled:
            if expected is not None:
                assert mem_model == expected, 'directed MEM expectation disagrees with model'
            if if_expected is not None:
                assert if_model == if_expected, 'directed IF expectation disagrees with model'
        actual = (int(self.dut.if_allow_o.value), int(self.dut.mem_allow_o.value))
        assert actual == (if_model, mem_model), (
            f'enabled={self.enabled}, IF={if_request or (address, size, machine)}, '
            f'MEM=({address:#x},size={size},access={access:03b},M={machine}): '
            f'expected IF/MEM={(if_model, mem_model)}, actual={actual}; '
            f'configs={configs}, addresses={addresses}')
        self.checks += 1


class DirectedTest(PMPTest):
    async def run_phase(self):
        self.raise_objection()
        # Every entry position, mode, legal permission combination, L bit,
        # privilege and access type. Nonzero OFF predecessor supplies TOR low.
        for entry in range(16):
            for mode in range(4):
                for permissions in LEGAL_PERMISSIONS:
                    for locked in (0, 1):
                        cfg, addr = [0] * 16, [0] * 16
                        cfg[entry] = config(mode, permissions, locked)
                        if mode == TOR:
                            addr[entry] = 0x1100 >> 2
                            if entry:
                                addr[entry - 1] = 0x1000 >> 2
                        elif mode == NA4:
                            addr[entry] = 0x1000 >> 2
                        else:
                            addr[entry] = napot(0x1000, 256)
                        for machine in (0, 1):
                            for access in (1, 2, 4, 3):
                                await self.check(cfg, addr, 0x1000, 2, access, machine)
                                await self.check(cfg, addr, 0x1100, 0, access, machine)

        # All encoded NAPOT sizes, including regions extending beyond the bus
        # and encodings with all address bits set. No 34-bit bound truncation.
        for trailing in range(33):
            for high in (0, 1):
                encoded = (1 << trailing) - 1
                if high and trailing < 31:
                    encoded |= 1 << 31
                cfg, addr = [0] * 16, [0] * 16
                cfg[15], addr[15] = config(NAPOT, 7, True), encoded
                selected = region(cfg, addr, 15)
                candidates = {0, 3, 4, 0x7FFFFFFF, 0xFFFFFFFC, 0xFFFFFFFF,
                              selected.start - 1, selected.start, selected.stop - 1,
                              selected.stop}
                for address in sorted(x for x in candidates if 0 <= x < 1 << 32):
                    for machine in (0, 1):
                        await self.check(cfg, addr, address, 0, 1, machine)

        # TOR at zero, reversed/empty bounds and high encoded bounds; predecessor
        # contributes regardless of its configuration/address mode.
        for lower, upper in ((0, 0), (0x100, 0x100), (0x101, 0x100),
                             (0x3FFFFFFF, 0x40000000),
                             (0x40000000, 0x40000001),
                             (0, 0xFFFFFFFF)):
            cfg, addr = [0] * 16, [0] * 16
            cfg[1], addr[0], addr[1] = config(TOR, 7, True), lower, upper
            for address in (0, 0x3FF, 0x400, 0x403, 0x404, 0xFFFFFFFC, 0xFFFFFFFF):
                for machine in (0, 1):
                    await self.check(cfg, addr, address, 0, 1, machine)

        # Interface validity, nonwrapping top-of-bus operations, no alignment
        # enforcement here (the LSU handles alignment separately).
        cfg, addr = [0] * 16, [0] * 16
        cfg[0], addr[0] = config(NAPOT, 7, True), 0xFFFFFFFF
        for address in (0, 1, 2, 3, 0xFFFFFFFC, 0xFFFFFFFD, 0xFFFFFFFE, 0xFFFFFFFF):
            for size in range(4):
                for access in range(8):
                    for machine in (0, 1):
                        await self.check(cfg, addr, address, size, access, machine)
        self.logger.info('Directed PMP checks: %d (ISA_PMP=%d)', self.checks, self.enabled)
        self.drop_objection()


class PriorityTest(PMPTest):
    async def run_phase(self):
        self.raise_objection()
        # A higher-priority permission denial cannot fall back to a lower entry.
        # Nor can an unlocked entry be skipped to enforce a lower locked entry.
        for first in range(15):
            for second in range(first + 1, 16):
                for first_permissions, second_permissions in ((0, 7), (7, 0)):
                    for first_lock in (0, 1):
                        cfg, addr = [0] * 16, [0] * 16
                        cfg[first] = config(NA4, first_permissions, first_lock)
                        cfg[second] = config(NAPOT, second_permissions, True)
                        addr[first], addr[second] = 0x1000 >> 2, napot(0x1000, 256)
                        for machine in (0, 1):
                            for access in (1, 2, 4):
                                expected = bool(machine and not first_lock) or bool(
                                    first_permissions & access)
                                await self.check(cfg, addr, 0x1000, 2, access,
                                                 machine, expected)

        # The first match can be at the LAST byte. Even M/unlocked must fail
        # partial coverage, rather than select a later all-covering entry.
        for position in range(15):
            for region_base in (0x1000, 0x1004):
                for locked in (0, 1):
                    cfg, addr = [0] * 16, [0] * 16
                    cfg[position], addr[position] = config(NA4, 7, locked), region_base >> 2
                    cfg[15], addr[15] = config(NAPOT, 7, True), napot(0x1000, 16)
                    for machine in (0, 1):
                        for access in (1, 2, 4):
                            await self.check(cfg, addr, 0x1003, 1, access, machine, False)
                            await self.check(cfg, addr, 0x1002, 2, access, machine, False)

        # All OFF means no U permissions, not that PMP has been disabled.
        cfg, addr = [0] * 16, [0xFFFFFFFF] * 16
        for machine in (0, 1):
            for access in (1, 2, 4):
                await self.check(cfg, addr, 0x1000, 2, access, machine, bool(machine))
        self.logger.info('Priority PMP checks: %d (ISA_PMP=%d)', self.checks, self.enabled)
        self.drop_objection()


class RandomizedTest(PMPTest):
    async def run_phase(self):
        self.raise_objection()
        rng = random.Random(int(os.environ['RANDOM_SEED']) ^ 0x504D50)
        for _ in range(4096):
            cfg, addr = [], []
            # Mix overlapping small regions with arbitrary full-width bounds.
            anchor = rng.getrandbits(32) & ~0xFFF
            for _ in range(16):
                mode = rng.randrange(4)
                cfg.append(config(mode, rng.choice(LEGAL_PERMISSIONS), rng.randrange(2)))
                if rng.randrange(4) == 0:
                    addr.append(rng.getrandbits(32))
                elif mode == NAPOT:
                    length = 1 << rng.randrange(3, 33)
                    base = anchor & ~(length - 1)
                    addr.append(napot(base, length))
                else:
                    addr.append((anchor + rng.randrange(1024) * 4) >> 2)
            chosen = region(cfg, addr, rng.randrange(16))
            candidates = [rng.getrandbits(32), anchor + rng.randrange(4096),
                          rng.choice((chosen.start - 1, chosen.start, chosen.stop - 1,
                                      chosen.stop)) & 0xFFFFFFFF]
            for address in candidates:
                await self.check(cfg, addr, address, rng.randrange(3),
                                 rng.choice((1, 2, 3, 4)), rng.randrange(2))
        self.logger.info('Randomized PMP checks: %d (ISA_PMP=%d)', self.checks, self.enabled)
        self.drop_objection()


class ConcurrentTest(PMPTest):
    async def run_phase(self):
        self.raise_objection()
        cfg, addr = [0] * 16, [0] * 16
        # Execute-only code and read/write data have deliberately opposite
        # permissions. Both outputs must reflect the same configuration at once.
        cfg[0], addr[0] = config(NAPOT, 4, True), napot(0x1000, 256)
        cfg[1], addr[1] = config(NAPOT, 3, True), napot(0x2000, 256)
        await self.check(cfg, addr, 0x2000, 2, 2, 0, True,
                         if_request=(0x1000, 2, 0), if_expected=True)
        await self.check(cfg, addr, 0x1000, 2, 1, 0, False,
                         if_request=(0x2000, 2, 0), if_expected=False)
        await self.check(cfg, addr, 0x1000, 2, 1, 0, False,
                         if_request=(0x1000, 2, 0), if_expected=True)
        await self.check(cfg, addr, 0x2000, 2, 1, 0, True,
                         if_request=(0x2000, 2, 0), if_expected=False)

        # Independently change each port while the other remains held. Include
        # different privileges, sizes, partial overlaps and invalid requests.
        requests = [(0x1000, 2, 0), (0x2000, 0, 0), (0x3000, 1, 0),
                    (0x3000, 2, 1), (0x10FF, 1, 1), (0xFFFFFFFF, 2, 1),
                    (0x1000, 3, 0)]
        for fixed in requests:
            for varied in requests:
                for access in (0, 1, 2, 3):
                    await self.check(cfg, addr, *varied[:2], access, varied[2],
                                     if_request=fixed)
                    await self.check(cfg, addr, *fixed[:2], access, fixed[2],
                                     if_request=varied)

        # The caller supplies effective privilege per port: a U-mode data
        # access in M-mode under MPRV must not inherit fetch's M-mode bypass.
        cfg[0], addr[0] = config(NAPOT, 0, False), napot(0x1000, 256)
        await self.check(cfg, addr, 0x1000, 2, 1, 0, False,
                         if_request=(0x1000, 2, 1), if_expected=True)
        await self.check(cfg, addr, 0x1000, 2, 1, 1, True,
                         if_request=(0x1000, 2, 0), if_expected=False)

        # Shared CSR inputs can change without any port handshake. Hold both
        # requests while changing mode, bounds, permissions and L in turn.
        cfg, addr = [0] * 16, [0] * 16
        for locked in (0, 1):
            for mode in (OFF, TOR, NA4, NAPOT):
                for permissions in LEGAL_PERMISSIONS:
                    for encoded in (0x400, 0x401, 0x800, 0xFFFFFFFF):
                        cfg[0], addr[0] = config(mode, permissions, locked), encoded
                        await self.check(cfg, addr, 0x2000, 2, 2, 1,
                                         if_request=(0x1000, 2, 0))

        # Random independent fetch/data requests exercise both region selectors
        # in the same cycle, rather than mirroring one port's address/control.
        rng = random.Random(int(os.environ['RANDOM_SEED']) ^ 0x504D5032)
        for _ in range(2048):
            cfg = [config(rng.randrange(4), rng.choice(LEGAL_PERMISSIONS),
                          rng.randrange(2)) for _ in range(16)]
            addr = [rng.getrandbits(32) for _ in range(16)]
            await self.check(cfg, addr, rng.getrandbits(32), rng.randrange(4),
                             rng.randrange(8), rng.randrange(2),
                             if_request=(rng.getrandbits(32), rng.randrange(4),
                                         rng.randrange(2)))
        self.logger.info('Concurrent PMP checks: %d (ISA_PMP=%d)', self.checks, self.enabled)
        self.drop_objection()


@cocotb.test(timeout_time=100, timeout_unit='us')
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test(timeout_time=100, timeout_unit='us')
async def priority(_dut):
    await uvm_root().run_test(PriorityTest)


@cocotb.test(timeout_time=100, timeout_unit='us')
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)


@cocotb.test(timeout_time=100, timeout_unit='us')
async def concurrent(_dut):
    await uvm_root().run_test(ConcurrentTest)
