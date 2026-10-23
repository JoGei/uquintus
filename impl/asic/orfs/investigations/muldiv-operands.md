# Direct register operands for MUL/DIV

This experiment implements the first candidate from the [producer-selection audit](producer-selection.md). It removes ALU PC/immediate selection from the MUL/DIV input path, without changing functional-unit result selection or adding pipeline state.

## Datapath change

`uqu_core` supplies its resolved EX RS1 and RS2 values directly to `uqu_stage_ex.muldiv_a_i` and `muldiv_b_i`. These connect to the existing `uqu_muldiv` request operands. The ALU and FPU keep their existing selected `a_i`/`b_i` connections. No top-level core ports or configuration parameters change.

Legal native M instructions always use RS1/RS2. The audit's six local DE contract proofs establish the corresponding operand-selector values for RV32I/E and all three compressed-decode arrangements; those DE sources are unchanged by this experiment. Captured and deferred operands still use the same core-owned hazard/forwarding resolution and readiness qualification. Execution, cancellation, result retention and retirement timing stay unchanged.

```text
Before: resolved RS1/RS2 → ALU PC/immediate selection → MDU
After:  resolved RS1/RS2 ────────────────────────────→ MDU
```

This change does not remove all arithmetic selection. Iterative MUL/DIV keeps its operation/phase steering, and the EX-owned arithmetic slice still selects between ALU and MDU operands. Direct register inputs can shorten initial capture, multiplication's first iteration and division's initial magnitude preparation. Subsequent iterations use internal state registers, so this change does not shorten their state-to-arithmetic feedback path or reduce the iteration count. Dadda and inferred one-cycle multiplication are the primary timing targets because their complete product computation follows the removed selectors.

## Comparison method

The two physical configurations remain RV32IMC with bimodal/BTB 16/16, six replay halfwords, IF decompression, all forwarding enabled, continuous DE operand resolution, a flip-flop GPR file, one-cycle Dadda or inferred multiplication, and iterative division with factor one. The baselines are the accepted two-outstanding-fetch implementations `impl-core-20261023T200429Z-fee3172c` and `impl-core-20261023T200429Z-3a0d2d02`.

Both candidates use the same Sky130 HD library, tools, mapping/buffering policy, 20 ns constraint, 4 ns data-I/O budget, 0–1 ns reset window, floorplan, placement settings and two worker threads as their respective baselines. Report contexts, parameter dictionaries and SDC bytes must match; only `uqu_core.v` and `uqu_stage_ex.v` may differ among recorded RTL source hashes. These are repaired placement estimates with ideal clocks, before CTS and routing. A finite estimated Fmax does not mean the 20 ns target has closed.

## Verification method

EX directed tests use MUL/DIV source values that deliberately disagree with the ALU input bus. Randomized EX and parent-pipeline tests vary the two buses independently, alongside operand waits, downstream backpressure, exceptions, reset and cancellation. All four multiplier modes and iterative factors 1, 2, 4, 8, 16 and 32 are exercised. The parent fixture owns the new operand payload registers; EX itself gains none.

The core matrix covers all 16 combinations of the four forwarding routes with both continuous resolution and operand retention, forwarding globally disabled, RV32E, both physical multiplier presets, all compressed-decode arrangements, disabled M and native Zfinx. The existing retirement oracle checks arithmetic outcomes; the operand-capture checks distinguish configurations that admit deferred operands from configurations that require capture before EX.

Four flattened core checks cover captured/deferred EX inputs and both DE retention modes. They verify that neither MDU operand depends combinationally on the current EX PC/immediate selectors, PC or immediate payload, and that no combinational strongly connected component exists. In the captured profiles, MDU operands alias the EX operand registers directly. These structural checks do not claim whole-core formal equivalence.

CoreMark and Embench `nsichneu`, `crc32` and `aha-mont64` reuse the same ELF images, compiler provenance and memory timing as the baselines, for both multipliers. All reported benchmark metrics, including measured cycles, retired instructions and BPU statistics, must match exactly.

The scripts, configurations, JUnit results, source provenance, structural netlists and benchmark comparisons are retained in [`build/investigations/muldiv-operands/`](../../../../build/investigations/muldiv-operands/). Disposable simulator object directories from this experiment are removed after successful runs to limit disk usage; logs and results remain.

## Measured results and decision

| Multiplier | Version | Tmin (ns) | Estimated Fmax (MHz) | Setup WNS (ns) | Logical cell area (µm²) |
| --- | --- | ---: | ---: | ---: | ---: |
| Dadda | Baseline | 24.184 | 41.349 | -4.184 | 449,344.7 |
| Dadda | Direct register inputs | 23.007 | 43.465 | -3.007 | 445,732.5 |
| Inferred | Baseline | 24.627 | 40.606 | -4.627 | 456,734.3 |
| Inferred | Direct register inputs | 24.873 | 40.204 | -4.873 | 456,318.9 |

Dadda gains 5.115% estimated Fmax and reduces logical cell area by 0.804%. Inferred multiplication loses 0.990% estimated Fmax and reduces area by 0.091%. The direct-input topology is retained: it gives Dadda a measured timing/area improvement and expresses the native M operand contract directly. This is a mixed physical result, not a general claim of higher frequency for every multiplier or configuration. No iterative-mode Fmax improvement is established by these two physical runs.

The new first critical paths start at resolved EX source registers, `ex_rs[0][0]` for Dadda and `ex_rs[1][0]` for inferred multiplication, and end at `imem_req_o`. They no longer start at `ex_a_sel_q[0]`. The remaining arithmetic-to-DE-control-flow-to-IF route still limits the clock. Both candidates have positive hold slack of 0.305 ns and zero placement, slew, capacitance and fanout violations; both remain failed flow results because setup misses the 20 ns target.

The candidate databases are `impl-core-20261023T211811Z-894b8440` (Dadda) and `impl-core-20261023T211811Z-d812e0f9` (inferred). The comparison script verified equal parameter dictionaries, full report contexts and SDC bytes, the two expected RTL changes, and candidate source hashes against the workspace.

All eight benchmark executions pass with identical baseline metrics. Each multiplier records CoreMark at 463,144 cycles / 314,834 retired instructions (CPI 1.471074), `nsichneu` at 6,395,103 / 2,237,992 (2.857518), `crc32` at 4,702,616 / 4,353,735 (1.080134), and `aha-mont64` at 5,009,282 / 4,532,531 (1.105184).

All 70 regression runs pass: 836 core testcases across 44 profiles, 39 EX testcases across 13 profiles, and 26 parent-pipeline testcases across 13 profiles (901 total). No testcase fails or skips. All four structural checks and core/EX/parent-fixture lint pass. Deferred EX admissions are observed with both DE retention modes; configurations that forbid deferred admission record none. A permitted deferred route need not be exercised by every instruction or profile. The aggregate HTML report was refreshed with zero collection issues.
