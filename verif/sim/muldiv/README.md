# Native multiply/divide component

[uqu_muldiv.v](../../../src/uquintus/uqu_muldiv.v) implements all eight RV32 M
operations. It owns the iterative state and fixed-shift wiring, borrows the
ALU's `uqu_arith` instance as slice zero, and generates only the remaining
`F - 1` arithmetic instances. The complete ALU and EX integration are still
pending. The local [Verilog wrapper](uqu_muldiv_tb.v) supplies the borrowed
instance for standalone tests.

```text
                        uqu_muldiv
  request --------> state, operand steering, fixed shifts --------> result
                           |              |
                    slice 0 ports    slices 1 .. F-1
                           |              |
                     ALU uqu_arith   internal uqu_arith instances
```

## Instruction handshake

| Port | Meaning |
| --- | --- |
| `clk_i`, `rst_ni` | Single clock; active-low synchronous reset. Only control validity is reset. |
| `flush_i` | Cancel the owning instruction, including any held result, at the next edge. Suppress transfers while asserted. |
| `req_valid_i`, `req_ready_o` | Request transfer occurs on their conjunction at a rising edge. |
| `req_op_i[2:0]` | M-extension instruction `funct3`, as listed below. |
| `req_a_i[31:0]`, `req_b_i[31:0]` | Source operands. Keep the request payload stable while valid and blocked. |
| `res_valid_o`, `res_ready_i` | Result transfer occurs on their conjunction at a rising edge. |
| `res_data_o[31:0]` | Selected destination value, stable while valid and blocked. Zero when invalid. |

| `req_op_i` | Instruction | Result |
| --- | --- | --- |
| `000` | MUL | Low 32 product bits |
| `001` | MULH | High 32 bits, signed × signed |
| `010` | MULHSU | High 32 bits, signed × unsigned |
| `011` | MULHU | High 32 bits, unsigned × unsigned |
| `100` | DIV | Signed quotient, rounded toward zero |
| `101` | DIVU | Unsigned quotient |
| `110` | REM | Signed remainder, with dividend's sign |
| `111` | REMU | Unsigned remainder |

The first execution cycle is the request-transfer cycle. A one-cycle operation
may transfer its request and result at the same edge. Multi-cycle operations
capture their request once and continue computing regardless of result
backpressure. A completed result is retained until accepted; the unit accepts
no further request while computing or holding a result. After draining, a new
operation can start in the next cycle. There is no independent busy output:
EX tracks its accepted instruction and pending result.

Reset or flush takes priority over all computation and transfers. The enclosing
EX controller must supply flush only when this unit's owning instruction is
being discarded. The unit does not decide interrupt or trap eligibility.

With `ISA_M = 0`, requests are never accepted and all outputs are zero. Decode
must reject M instructions in that configuration rather than issue them here.

## Borrowing the ALU arithmetic instance

| Port | Meaning |
| --- | --- |
| `arith_use_o` | This cycle needs the borrowed arithmetic instance. |
| `arith_a_o[32:0]`, `arith_b_o[32:0]` | Slice-zero operands, including the guard/sign bit. |
| `arith_sub_o`, `arith_carry_in_o` | Connect to `uqu_arith.sub_i` and `.carry_i`. |
| `arith_result_i[32:0]` | Connect from `uqu_arith.result_o`. |
| `arith_carry_out_i` | Connect from `uqu_arith.carry_o`; subtraction carry means no borrow. |

These are **combinational datapath connections**, with no ready/valid protocol.
EX reserves the ALU for the owning instruction. When `arith_use_o = 1`, the ALU
selects the MUL/DIV operands and controls and returns result/carry in the same
cycle. EX must not arbitrate or stall individual arithmetic steps; doing so
would violate fixed execution latency. Unrelated normal ALU operands must not
feed slice zero during those cycles. When `arith_use_o = 0`, the arithmetic
payload outputs are inactive zeros and the arithmetic response is ignored.

A typical ALU connection is:

```verilog
uqu_arith u_arith (
    .a_i(muldiv_arith_use ? muldiv_arith_a : alu_a),
    .b_i(muldiv_arith_use ? muldiv_arith_b : alu_b),
    .sub_i(muldiv_arith_use ? muldiv_arith_sub : alu_sub),
    .carry_i(muldiv_arith_use ? muldiv_arith_carry_in : alu_carry_in),
    .result_o(shared_result),
    .carry_o(shared_carry),
    .borrow_o(shared_borrow)
);
```

Wire `shared_result` and `shared_carry` back to the corresponding MUL/DIV inputs.
The same instance continues to serve normal ALU addition/subtraction. At `F=1`,
MUL/DIV contains no data adder, subtractor, multiplier, or dedicated negation
unit in its iterative configuration; its six-bit iteration-counter addition
is control logic. At larger factors the additional instances are shared by
iterative MUL and DIV. During divider setup, slices zero and one instead receive
independent operands to prepare both magnitudes in parallel.

## Configuration and cycle counts

`MUA_MUL` is `iterative` (default), `parallel`, or `parallel+stages+2`.
`MUA_DIV` is `iterative`. `F = MUA_MULDIV_ITERUNROLL` defaults to eight and accepts
only 1, 2, 4, 8, 16, or 32. Labels and numeric RTL constants come from
[config/selectors.json](../../../config/selectors.json). The default M-enabled
configuration shares the iterative slices between MUL and DIV, giving four
MUL cycles and six DIV/REM cycles at factor eight.

| F | Iterative MUL cycles | DIV/DIVU/REM/REMU cycles |
| --- | --- | --- |
| 1 | 32 | 35 |
| 2 | 16 | 18 |
| 4 | 8 | 10 |
| 8 | 4 | 6 |
| 16 | 2 | 4 |
| 32 | 1 | 3 |

Parallel multiplication takes one cycle; its two-stage variant takes two.
These timings are operand independent, including zero, signed overflow, and
division by zero. Backpressure can delay result transfer but never result
availability. There is no cross-instruction fusion or saved-result reuse.

Iterative multiplication performs conditional add/subtract followed by a
combined accumulator/multiplier right shift. Sign extension of the multiplicand
and subtraction for a signed multiplier's final bit handle signed products
inside the 32 iterations, with no magnitude-setup phase.

Division uses magnitude preparation, restoring binary steps, and one completion
cycle to sign-correct the selected quotient or remainder. Its latency is
`ceil(2/F) + 32/F + 1`. Subtraction carry selects the trial remainder and next
quotient bit without a restoring addition. Division by zero returns all ones
for quotient or the original dividend for remainder. Signed `INT_MIN / -1`
returns `INT_MIN` and remainder zero, following the
[RISC-V M-extension specification](https://github.com/riscv/riscv-isa-manual/blob/main/src/unpriv/m-st-ext.adoc).

The two-stage parallel implementation computes the low-16-bit multiplicand's
partial product in stage one, stores it and the other required operands, then
computes and combines the upper partial product in stage two. It partitions
actual work across the register boundary; it does not add a delay after a
complete multiplier. Synthesis determines its cell implementation and timing.

## Running tests

```sh
make test COMPONENT=muldiv CONFIG=rv32im
make test COMPONENT=muldiv CONFIG=rv32im_iterative
make lint COMPONENT=muldiv CONFIG=rv32im_iterative
make test COMPONENT=muldiv CONFIG=rv32i   # Verify disabled behavior
```

Provide the same external tools and Python dependencies as the
[shared component runner](../common/README.md). The complete hardware presets
are in `config/`; edit a copy to exercise other factors or two-stage MUL, then
use `CONFIG=/path/to/profile.yml`. Every hardware parameter remains explicit.

The cocotb/pyuvm suites compare against Python integer arithmetic, independently
of the RTL algorithms. `directed` covers signs, extrema, division exceptions,
bit positions, and exact latency; `randomized` covers random operands and
result backpressure; `control` cancels at every execution cycle and while a
result is held, using both flush and reset, and checks subsequent recovery.
The wrapper includes the real borrowed arithmetic instance, so these tests also
exercise the full combinational chain. Disabled profiles explicitly check
inactive outputs rather than silently enabling M. Full-core verification,
formal proofs, and ASIC timing/area characterization remain pending.
