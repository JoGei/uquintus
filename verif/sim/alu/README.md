# Base integer ALU

[uqu_alu.v](../../../src/uquintus/uqu_alu.v) implements the ten RV32I/E integer
ALU operations in one execution cycle. It handles logic, variable shifts,
comparison/result selection, and result retention. The parent EX stage owns
the shared `uqu_arith` instance used by both ALU and MUL/DIV.

The local [standalone wrapper](uqu_alu_tb.v) supplies that instance. The
[shared-parent regression](../exec_arith/README.md) connects the real ALU and
MUL/DIV as siblings around one external arithmetic instance. The [EX component](../ex/README.md) now integrates these units with
[parent-owned boundary registers](../ex_pipeline/README.md) and is integrated
in the [processor core](../core/README.md).

## Request and result

| Port | Meaning |
| --- | --- |
| `clk_i`, `rst_ni` | Clock and active-low synchronous reset; only held-result validity is reset. |
| `flush_i` | Cancel the owning instruction and suppress transfers while asserted. |
| `req_valid_i`, `req_ready_o` | Request transfer on their conjunction at a rising edge. |
| `req_op_i[3:0]` | Normalized operation code from the table below. |
| `req_a_i[31:0]`, `req_b_i[31:0]` | Selected operands; register/immediate and PC selection belongs upstream. |
| `res_valid_o`, `res_ready_i` | Result transfer on their conjunction at a rising edge. |
| `res_data_o[31:0]` | Destination value; zero when invalid and stable while valid and blocked. |

| `req_op_i` | Operation | Result |
| --- | --- | --- |
| `0000` | ADD | Low 32 bits of A + B |
| `0001` | SLL | A shifted left by B[4:0] |
| `0010` | SLT | 1 if signed A < signed B; otherwise 0 |
| `0011` | SLTU | 1 if unsigned A < unsigned B; otherwise 0 |
| `0100` | XOR | A xor B |
| `0101` | SRL | A shifted right logically by B[4:0] |
| `0110` | OR | A or B |
| `0111` | AND | A and B |
| `1000` | SUB | Low 32 bits of A - B |
| `1101` | SRA | A shifted right arithmetically by B[4:0] |

The low three bits match the base instruction's `funct3`; bit three distinguishes
SUB and SRA. Decode must normalize that modifier. For example, an ADDI immediate's
instruction bit 30 must not accidentally select SUB. Reserved internal operation
codes produce zero as a deterministic fallback. Decode remains responsible for
rejecting illegal instructions; this fallback does not grant them ISA semantics.

Upstream operand selection can use ADD for AUIPC (PC + immediate), LUI
(zero + immediate), and LSU effective-address generation (base + offset).
Branch comparison and control-flow targets remain in DE. There are no
architectural carry/overflow flags, register-file selection, memory operations,
or instruction decoding inside the ALU.

A request can transfer its result at the same rising edge, allowing consecutive
single-cycle operations. Result valid is independent of result ready. If the
result is blocked, the ALU captures it at the request edge and stops using the
arithmetic slice. It accepts no new request until the held result drains; a
waiting request can start in the next cycle. EX must track accepted requests
so a held instruction is not issued again. Reset or owning-instruction flush
suppresses both transfers and clears held-result validity at the active edge;
the data register need not reset.

## Shared arithmetic

| Port | Meaning |
| --- | --- |
| `arith_use_o` | The accepted request needs the external arithmetic instance this cycle. |
| `arith_a_o[32:0]`, `arith_b_o[32:0]` | Extended operands; zero when inactive. |
| `arith_sub_o`, `arith_carry_in_o` | Subtraction control and raw carry-in for `uqu_arith`. |
| `arith_result_i[32:0]` | Same-cycle extended arithmetic result from the parent. |
| `arith_carry_out_i` | Same-cycle carry beyond bit 32; subtraction carry means no borrow. |

These ports match the MUL/DIV arithmetic connection. **EX owns the instance and
its input mux.** It selects the owning instruction's operands and controls and
returns result/carry to both units. EX issues only the selected unit and holds
ownership throughout a multi-cycle instruction. Neither unit contains slice
zero; there is no arithmetic handshake, internal borrowing port on ALU, or
per-step arbitration. Even ALU-only integrations must supply the external
instance with its combinational return path.

ADD, SUB, SLT, and SLTU use shared arithmetic. SLT sign-extends both operands
and examines the 33-bit subtraction's sign, avoiding 32-bit signed overflow.
SLTU zero-extends operands and uses inverted no-borrow carry. ADD/SUB retain the
low 32 bits. Logic and shifts do not request the arithmetic instance.

One right barrel shifter implements all variable shifts: fixed bit-reversal
wiring surrounds it for SLL, while a guard/sign bit selects logical or arithmetic
right fill. Only B[4:0] affects the shift amount. All operations have one-cycle
result availability, including shifts and comparisons.

## Running tests

```sh
make test COMPONENT=alu CONFIG=rv32i
make lint COMPONENT=alu CONFIG=rv32i
make test COMPONENT=alu TEST=randomized SEED=42
make test COMPONENT=exec_arith CONFIG=rv32im
```

Use the [shared runner](../common/README.md) and externally provisioned tools.
The ALU has no hardware parameters: its datapath is identical for RV32I and
RV32E, and the manifest explicitly selects no parameter overrides.

Cocotb/pyuvm suites compare against mathematical Python results in the shared
[RV32 arithmetic models](../common/rv32_arithmetic.py). `directed` covers signed
extrema, carry/borrow boundaries, logic patterns, every source-bit/shift-amount
combination, ignored upper shift bits, and reserved operation fallback.
`randomized` varies all operations, operands, and backpressure. `control`
checks reset/flush before acceptance and on retained results, pending requests,
consecutive one-cycle transfers, and recovery without stale results. Timing
closure remains open. Full-pipeline forwarding/control is integrated and
exercised separately by the [core regression](../core/README.md).
