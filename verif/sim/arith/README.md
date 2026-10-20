# Shared arithmetic component

RTL: [src/uquintus/uqu_arith.v](../../../src/uquintus/uqu_arith.v), module
`uqu_arith`. This is a combinational, fixed-width extended add/sub datapath for
the ALU and iterative MUL/DIV chain. The parent EX stage owns their shared
first instance. Operands are 33 bits; the component
has no clock, reset, state, or instruction handshake. The width is internal
datapath headroom for the RV32 processor, not a configurable architectural width.

| Port | Width | Meaning |
| --- | --- | --- |
| `a_i`, `b_i` | 33 each | Unsigned bit patterns for arithmetic; callers perform any required extension. |
| `sub_i` | 1 | Select subtraction instead of addition. |
| `carry_i` | 1 | Raw adder carry-in; drive one for ordinary subtraction. |
| `result_o` | 33 | Low 33 bits of the result. |
| `carry_o` | 1 | Carry beyond bit 32; in subtraction, one means no borrow. |
| `borrow_o` | 1 | Subtraction underflow; always zero during addition. |

| `sub_i` | `carry_i` | Operation |
| --- | --- | --- |
| 0 | 0 | A + B |
| 0 | 1 | A + B + 1 |
| 1 | 1 | A - B |
| 1 | 0 | A - B - 1 |

`carry_o` describes the full **33-bit** operation. For example, zero-extended
32-bit `0xffffffff + 1` produces `result_o = 33'h100000000` and `carry_o = 0`.
The surrounding ALU chooses its 32-bit architectural result and comparison
semantics. MUL/DIV fixed-shift wiring, operand selection, state, sign handling,
and execution control belong to the enclosing units.

For a signed RV32 operand `x`, the enclosing setup logic obtains `abs(x)` using
`a_i = 0`, `b_i = {x[31], x}`, and `sub_i = carry_i = x[31]`. Nonnegative
inputs pass through addition with zero; negative inputs use subtraction from
zero. The magnitude is read from `result_o`; the 33-bit datapath can represent
`abs(-2^31) = 2^31`. Unsigned operands instead use `b_i = {1'b0, x}` with
`sub_i = carry_i = 0`. This uses the existing add/sub interface and surrounding
operand/control muxes, without an absolute-value opcode or extra negation unit.

The component manifest is [config/sim/arith.yml](../../../config/sim/arith.yml).
It has no configurable parameters and uses the existing shared Make helper:

```sh
make test COMPONENT=arith CONFIG=rv32i
make test COMPONENT=arith TEST=chained
make test COMPONENT=arith TEST=absolute
make test COMPONENT=arith TEST=randomized SEED=42
make lint COMPONENT=arith
```

Supply tools and Python dependencies as described in
[shared simulation infrastructure](../common/README.md). Directed tests cover
mode/carry combinations, boundaries, the 33rd bit, and walking carry/borrow
chains. Randomized checks use mathematical Python sums/differences. Chained
tests use the DUT's carry outputs to compute two-limb, 66-bit results and compare
them against whole-number arithmetic. Absolute-value tests exercise signed and
unsigned RV32 operand preparation, including the most-negative signed value,
using those input controls and Python's mathematical `abs` as the reference.
Every test runs through pyuvm phases.
