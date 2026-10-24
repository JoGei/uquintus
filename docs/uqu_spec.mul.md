# uquintus multiplication specification

**Status:** Agreed; implemented datapath and integration contract; MAC architectural encoding is unassigned. This specification complements [architecture, Section 3](uqu_spec.arch.md#3-classical-five-stage-pipeline). “Shall” denotes a requirement; measurement history and selection rationale belong in the [efficient multiplication investigation](../impl/asic/orfs/investigations/efficient-mul.md).

MEM is the core's second execution region as well as the LSU request stage. The canonical multiplier is `MUA_MUL: dadda_mac`: EX1 forms ordinary signed-corrected partial products and compresses them to two aligned 64-bit rows; MEM/EX2 fuses late C through a 3:2 layer and completes one carry-propagate addition. Native multiplication uses C=0. WB retains architectural retirement and precise exception ownership. This adds no sixth pipeline stage.

| Selection | EX1 | MEM/EX2 | Purpose |
| --- | --- | --- | --- |
| `dadda_mac` (default) | PP/Dadda compression to two rows | C insertion, final BK-mapped addition, half selection | Independent throughput and accumulator recurrence |
| `dadda` | Complete PP/Dadda/BK product | Pass through completed result | Lower native MUL dependency latency |
| `iterative` | `32/F` shared add/sub iterations | Pass through completed result | Size-oriented shared arithmetic baseline |

All choices shall support native MUL, MULH, MULHSU and MULHU independently, with architectural signedness and result-half selection. They shall not reuse a previous instruction’s product or terminate early based on operand values. For `iterative`, multiplication shall take exactly `32/F` EX computation cycles, where `F = MUA_MULDIV_ITERUNROLL` is 1, 2, 4, 8, 16 or 32. EX1-only `dadda` shall take one computation cycle; `dadda_mac` shall use one EX1 and one MEM/EX2 computation phase, subject to operand readiness and downstream backpressure. DIV/REM shall retain the architecture specification’s `ceil(2/F)+32/F+1` execution schedule and shared arithmetic ownership. `MUA_MUL_SPLIT` and the former Booth, Wallace, Sklansky, inferred parallel and early-C selections are removed; the [historical selection record](../impl/asic/orfs/investigations/efficient-mul.md#decision) preserves their evidence.

## Architectural result contract

| Instruction | A interpretation | B interpretation | Destination value |
| --- | --- | --- | --- |
| MUL | Either | Either | Product bits 31:0 |
| MULH | Signed | Signed | Product bits 63:32 |
| MULHSU | Signed | Unsigned | Product bits 63:32 |
| MULHU | Unsigned | Unsigned | Product bits 63:32 |
| Internal MAC control | Either | Either | `(A*B+C) mod 2^32` |

Each operation shall write one 32-bit destination through normal WB retirement. Multiplication shall not raise an arithmetic-overflow exception or modify hidden accumulator state. High-half operations shall preserve carries from lower columns. Native MUL/MULH variants shall ignore the C payload, including nonzero or unavailable C.

## Product construction

`scripts/gen_daddamul.py` defines the deterministic signed-corrected partial-product heap and Dadda reductions `28 → 19 → 13 → 9 → 6 → 4 → 3 → 2`. Carries are packed at their actual binary weights. Each pass consumes only its input dots, never a counter output from the same pass. `gen_daddamul_rows.py` renders those same reductions without the final addition. Checked-in `uqu_daddamul.v` and `uqu_daddamul_rows.v` are normal plain-Verilog build inputs; generators are not synthesis dependencies.

For signed-interpretation controls SA/SB, each bit `A[i]&B[j]` is complemented when `(SA && i==31) XOR (SB && j==31)`. Correction dots SA and SB enter weight 31 and SA OR SB enters weight 63, all modulo 2^64. No magnitude setup or output negation phase is needed. Preserve lower-column carries for all high-half instructions. A single full-product circuit covers all four native multiply operations.

The final synthesizable 64-bit `+` uses the established Yosys Brent–Kung mapping. Technology mapping and physical repair may restructure it; the source does not instantiate a fixed BK gate network.

## Parent-owned EX1→MEM/EX2 payload

| Field | Normal interpretation | Split interpretation |
| --- | --- | --- |
| `mem_data_q[31:0]` | EX result / LSU address | Row A low half |
| `mem_store_data_q[31:0]` | Store data | Row A high half |
| Additional 64-bit bank | Absent outside split multiplication | Row B |
| Separate C payload, 32 bits | Absent outside split multiplication | Captured or late-resolved accumulator |
| C source metadata | Absent outside split multiplication | Address, captured flag, accumulate tag |
| Existing instruction metadata plus phase/half tags | PC, destination, validity, exceptions | Same owning instruction |

`uqu_core` shall own every boundary register; `uqu_stage_ex` and `uqu_stage_mem` contain the combinational arithmetic and local handshake control. Reset/flush invalidates ownership; data payloads need no reset. Stalls shall hold payload and identity together. The extra row/C banks shall elaborate away for EX1-only, iterative and disabled-M configurations. A split multiply shall enable neither LSU requests nor PMP data queries. An older unresolved memory response in WB can still block MEM/EX2 transfer.

## Late C and arithmetic completion

The internal MAC control `UQU_MDU_MAC` computes `d=(a*b+c) mod 2^32`, with one destination. Its architectural encoding and software-visible ISA feature remain deferred; no native decoder emits it. The third integer read port is enabled for M plus `dadda_mac`, or for Zfinx / three-source XIF independently. No GPR read-port arbitration in EX2 is needed: C travels in the payload.

For aligned rows A/B and zero-extended selected C:

```text
S = A XOR B XOR C
K = ((A AND B) OR (A AND C) OR (B AND C)) << 1
result64 = S + K
```

EX2 shall implement one carry-save layer followed by one carry-propagate addition. Native MUL/MULH supplies C=0; MAC selects the low half. There is no serial product addition followed by another carry-propagate accumulation adder. `uqu_mul_finish` has one fixed interface without cut, compressor-family or final-adder selectors.

A/B shall be ready before EX1 computation. Captured C shall be authoritative; otherwise the hazard unit waits for its matching registered WB producer. Youngest-writer priority blocks stale older values. C availability gates MAC completion in MEM/EX2, while native MUL and known exceptions do not wait for C. Loads, CSRs, XIF and secondary XIF destinations retain conservative source admission. Global forwarding disable makes DE wait for architectural C. The dedicated WB→EX2 C route is independent of `MUA_FORWARD_WB_TO_EX`.

## Forwarding and recurrence

EX phase-one completion does not make a GPR result available. Intermediate rows shall never be forwarded as GPR values. Native split MUL first becomes available in MEM/EX2 through the configured MEM-to-DE / MEM-to-EX routes; conservative A/B dependency handling may add one stall relative to EX1-only MUL. Independent multiplies can occupy both phases and start each cycle when downstream is ready.

For back-to-back internal `MAC x3,x1,x2,x3` operations:

| Cycle | MAC1 | MAC2 | C supply |
| --- | --- | --- | --- |
| k | EX1 compression | DE | MAC2 may defer C |
| k+1 | MEM/EX2 completion | EX1 compression | A/B already ready |
| k+2 | Registered WB result | MEM/EX2 completion | WB→EX2 supplies MAC1 result |

This permits an initiation interval of one for C-only recurrence. A/B-dependent chains still wait for the preceding product. It does not imply one-cycle whole-program CPI.

## Verification requirements

Verification shall cover the following behavior. The generated compressor is checked against independent signed/unsigned integer multiplication, exhaustive small widths and randomized RV32 operands. Local Yosys miters prove full-product reconstruction and arbitrary-row late-C finishing. Component tests cover both product halves, wrapping arithmetic, missing C, native C suppression, backpressure, flush/reset and exception drain. `mac_pipeline` instantiates the real hazard, GPR, EX and MEM blocks to check C recurrence, A/B stalls, youngest-writer priority, captured operands and global-forwarding disable. Core tests verify native instruction behavior, delayed memory, precise faults, interrupts and unrelated ISA configurations. These leaf proofs and simulation checks do not constitute whole-core formal verification.
