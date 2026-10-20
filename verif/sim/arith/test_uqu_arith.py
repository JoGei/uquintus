"""Check extended arithmetic against mathematical integer sums/differences."""

import os
import random

import cocotb
from cocotb.triggers import Timer
from pyuvm import uvm_root, uvm_test


class ArithTest(uvm_test):
    def build_phase(self):
        self.dut = cocotb.top
        self.width = len(self.dut.a_i)
        self.modulus = 1 << self.width
        self.mask = self.modulus - 1
        self.checks = 0

    async def check(self, a, b, subtract, carry):
        self.dut.a_i.value = a
        self.dut.b_i.value = b
        self.dut.sub_i.value = subtract
        self.dut.carry_i.value = carry
        await Timer(1, units="ns")

        if subtract:
            mathematical = a - b - (1 - carry)
            expected_borrow = int(mathematical < 0)
            expected_carry = 1 - expected_borrow
        else:
            mathematical = a + b + carry
            expected_borrow = 0
            expected_carry = int(mathematical >= self.modulus)
        expected = (mathematical % self.modulus, expected_carry, expected_borrow)
        actual = (int(self.dut.result_o.value), int(self.dut.carry_o.value),
                  int(self.dut.borrow_o.value))
        assert actual == expected, (
            f"A={a:#x}, B={b:#x}, sub={subtract}, carry={carry}: "
            f"expected (result,carry,borrow)={expected}, got {actual}")
        self.checks += 1
        return actual


class DirectedTest(ArithTest):
    async def run_phase(self):
        self.raise_objection()
        sign = 1 << (self.width - 1)
        values = sorted({0, 1, 2, self.mask, self.mask - 1, sign, sign - 1, sign + 1,
                         0xFFFFFFFF, 0xAAAAAAAA, 0x155555555})
        for a in values:
            for b in values:
                for subtract in (0, 1):
                    for carry in (0, 1):
                        await self.check(a, b, subtract, carry)

        # Walk carry/borrow chains across every bit, including the guard bit.
        for bit in range(1, self.width + 1):
            value = (1 << bit) - 1
            await self.check(value, 0, 0, 1)
            await self.check(0, value, 1, 1)
            await self.check(value, value, 1, 0)

        self.logger.info("Directed arithmetic checks: %d", self.checks)
        self.drop_objection()


class RandomizedTest(ArithTest):
    async def run_phase(self):
        self.raise_objection()
        rng = random.Random(int(os.environ["RANDOM_SEED"]))
        for _ in range(2048):
            a, b = rng.getrandbits(self.width), rng.getrandbits(self.width)
            for subtract in (0, 1):
                for carry in (0, 1):
                    await self.check(a, b, subtract, carry)
        self.logger.info("Randomized arithmetic checks: %d", self.checks)
        self.drop_objection()


class ChainedTest(ArithTest):
    async def run_phase(self):
        self.raise_objection()
        rng = random.Random(int(os.environ["RANDOM_SEED"]) ^ 0x41524954)
        wide_modulus = self.modulus * self.modulus
        # Use actual low-limb carry outputs as high-limb inputs, validating the
        # carry/no-borrow convention for arithmetic wider than one slice.
        for _ in range(256):
            a, b = rng.getrandbits(2 * self.width), rng.getrandbits(2 * self.width)
            for subtract in (0, 1):
                low, carry, _ = await self.check(a & self.mask, b & self.mask,
                                                 subtract, subtract)
                high, carry, borrow = await self.check(a >> self.width, b >> self.width,
                                                       subtract, carry)
                mathematical = a - b if subtract else a + b
                assert (high << self.width) | low == mathematical % wide_modulus
                assert carry == (int(a >= b) if subtract else
                                 int(mathematical >= wide_modulus))
                assert borrow == (int(a < b) if subtract else 0)
        self.logger.info("Chained arithmetic checks: %d", self.checks)
        self.drop_objection()


class AbsoluteTest(ArithTest):
    async def run_phase(self):
        self.raise_objection()
        rng = random.Random(int(os.environ["RANDOM_SEED"]) ^ 0x414253)
        operands = [0, 1, 2, 0x7FFFFFFF, 0x80000000, 0x80000001,
                    0xFFFFFFFE, 0xFFFFFFFF, 0xAAAAAAAA, 0x55555555]
        operands += [rng.getrandbits(32) for _ in range(2048)]
        for operand in operands:
            for signed in (False, True):
                negative = int(signed and bool(operand & (1 << 31)))
                extended = operand | (negative << 32)
                result, _, _ = await self.check(0, extended, negative, negative)
                value = operand - (1 << 32) if negative else operand
                assert result == abs(value), (
                    f"operand={operand:#010x}, signed={signed}: "
                    f"expected magnitude {abs(value):#x}, got {result:#x}")
        self.logger.info("Absolute-value arithmetic checks: %d", self.checks)
        self.drop_objection()


@cocotb.test(timeout_time=100, timeout_unit="us")
async def directed(_dut):
    await uvm_root().run_test(DirectedTest)


@cocotb.test(timeout_time=100, timeout_unit="us")
async def randomized(_dut):
    await uvm_root().run_test(RandomizedTest)


@cocotb.test(timeout_time=100, timeout_unit="us")
async def chained(_dut):
    await uvm_root().run_test(ChainedTest)


@cocotb.test(timeout_time=100, timeout_unit="us")
async def absolute(_dut):
    await uvm_root().run_test(AbsoluteTest)
