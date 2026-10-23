# EX operand capture and DE retention

This implements the core-integration specialization identified in the
[forwarding/fetch timing audit](forwarding-fetch-path.md#next-candidate-expose-the-ex-capture-invariant-to-synthesis).
The instruction-fetch address experiment remains rejected and reverted.

## Shorten the captured-operand path

The parent already stores each operand and its captured-valid bit at DE/EX.
Once captured, that word is authoritative; a later producer matching the same
architectural register must not replace it. Previously even these words passed
through the hazard unit's EX consumer mux and slot/reset/use qualification before
entering arithmetic. STA could also trace unused later-forwarding routes through
the multiplier and back into DE/IF.

`uqu_core` now selects a captured word directly from `ex_rs_data_q`. Only an
uncaptured source uses the existing hazard resolver. Its readiness still comes
from the resolver, and a resolved source is captured if EX is held. No execution
unit can consume an unavailable value, and no request or architectural effect
is authorized by an unqualified candidate word.

The core derives `EX_DEFERRED_OPERANDS` at elaboration from existing parameters:

```text
MUA_FORWARDING &&
    ((!MUA_FORWARD_EX_TO_DE && MUA_FORWARD_MEM_TO_EX) ||
     (!MUA_FORWARD_MEM_TO_DE &&
      (MUA_FORWARD_MEM_TO_EX || MUA_FORWARD_WB_TO_EX)))
```

When false, DE cannot emit an EX-entry guarantee for an unavailable source.
Every used EX operand must therefore be captured at admission. EX data then
connects directly to the parent registers, and unused later bypass logic and
capture-update paths are optimized away. Occupancy/reset/use still qualify
readiness. When true, the original later-forwarding paths remain available,
with a direct fast path for operands that have already been captured.

The standalone hazard module and its interface are unchanged. There is no new
MUA selector, operand bank, pipeline boundary, admission delay, forwarding-path
override or timing exception.

## What DE retention changes

`MUA_DE_OPERAND_RETENTION=1` captures a ready operand while its DE instruction
waits for another source or downstream capacity. Subsequent cycles can use that
holding register. With retention disabled, DE resolves the source afresh from
GPR storage or an enabled producer route.

Both policies still permit immediate forwarding on the first ready cycle and
can admit an unresolved EX source under a valid future-bypass guarantee.
Retention does not turn that guarantee into a captured value. Consequently,
the derived EX specialization applies to both policies equally. Already held
DE values can have shorter paths, while a fresh operand still needs its
immediate-resolution path. An unconditional extra retention/capture cycle would
change execution timing and is not introduced here.

## Behavioral and structural checks

The `operand_capture` core program exercises adjacent and separated producers,
load consumers, store data and a dependent branch. A slow DIV holds EX while
DE waits with another ready source, covering retained and continuously resolved
operands. The independent retirement oracle checks each architectural result;
the program also checks final memory contents and suppresses a wrong-path store.

Core regressions check on every cycle that admission has either a captured value
or a matching guarantee for each used EX source. Captured EX sources are checked
against their parent-held values even while other producers move through MEM/WB.
Runtime counts record deferred-admission coverage. The directed core stream
exercises deferred admissions in fourteen of the sixteen capable forwarding/
retention profiles. Targeted hazard-unit guarantee tests cover the two
MEM-staying-only profiles that stream does not trigger; all capture-only profiles
record zero deferred admissions.

Additional evidence includes:

- Local DE SAT proofs of `valid_o -> ((rs_ex_used_o & ~rs_captured_o) == 0)`
  with zero guarantee inputs, covering IF/DE decompression and direct compressed
  decode. The extended proofs enable RV32E, native M/Zfinx, three-source XIF and
  paired writes, with arbitrary initial XIF state.
- Generic, memory-mapped whole-core RV32IMC ancestry checks with retention both
  off and on. In the evaluated capture-only configurations, `ex_a`, `ex_b` and `ex_result` have no
  combinational primary-input ancestry, including reset, IRQ and data-response
  inputs; MEM/WB destination registers are absent from their sequential-boundary
  ancestors. Every resolved EX word aliases its parent operand register.
- In configurations admitting deferred operands, the WB matching dependency is
  still present where required. Each structural run passes `check -assert` and
  `scc -expect 0`.

These checks establish local capture/selection contracts and structural removal
of the reported route. They are not a whole-core formal ISA proof or an SDC
waiver for other paths.

## Measurements and provenance

**48 core configurations / 840 test cases pass**, including all sixteen
forwarding combinations with retention off/on, the forwarding master disabled,
both multiplier presets, XIF, PMP and native Zfinx with deferred operands. The
RV32E and latch-register-file profiles run the directed capture program. Two
additional hazard guarantee cases cover MEM-staying-only forwarding, for
**842 passing core/component cases**. Early test-driver failures are superseded
by successful reruns in the final validation manifest; all accepted run-input
hashes match the final sources.

All four fixed-ELF CoreMark performance runs pass CRC validation with exactly
463,144 measured cycles, 314,834 retired instructions and CPI 1.471074. The
optimization and the retention selection preserve this workload's cycle count.

Matched Sky130 HD implementations evaluate both multiplier choices with retention
off and on. Retention-off baselines are the accepted CSR-cleanup runs; immutable
copies of that RTL provide fresh retention-on baselines. All evaluations retain
the same 20 ns target, 4 ns data-I/O budgets, 0–1 ns reset window, geometry,
density, libraries, tools and two threads per run. Buffer/repair policy is unchanged.
Results are ideal-clock, placement-estimated evaluations before CTS and routing.

| Multiplier | DE retention | Before Tmin (ns) | After Tmin (ns) | Before Fmax (MHz) | After Fmax (MHz) | Before cell area (µm²) | After cell area (µm²) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Dadda | Off | 27.639 | 26.696 | 36.181 | 37.458 | 462,084 | 453,051 |
| Dadda | On | 26.214 | 25.848 | 38.148 | 38.688 | 456,975 | 457,581 |
| Inferred parallel | Off | 26.788 | 26.679 | 37.330 | 37.483 | 463,434 | 455,845 |
| Inferred parallel | On | 27.762 | 26.934 | 36.021 | 37.128 | 467,114 | 460,784 |

The optimization improves estimated Fmax in all four comparisons: +3.53%,
+1.42%, +0.41% and +3.07%, respectively. Logical cell area falls by 1.95%,
1.64% and 1.36% in three builds; retained Dadda grows by 0.13%. The comparison
checks byte-identical supplied SDC, identical parameters/tools/physical settings
within each pair, and that `uqu_core.v` is the only changed RTL source.

Retention is a separate trade-off: in the optimized Dadda preset it gains about
3.28% frequency at about 1.00% area cost. With inferred multiplication it adds
about 1.08% area and lowers frequency by about 0.95%. The measured CoreMark
cycle count is identical. Keep the retention default unchanged; these limited
measurements do not select universal or suite-wide Pareto presets.

All four runs complete placement and legalization with +0.305 ns hold slack and
zero slew, capacitance or fanout violations. **All still fail the 20 ns setup
target**, with worst setup slacks of −6.696, −5.848, −6.679 and −6.934 ns in
table order. The flow failure status is preserved rather than waived.

## Remaining first paths

The first paths now start at `ex_a_sel_q[0]` or `ex_b_sel_q[0]`, rather than WB
destination matching or reset feeding EX candidate arithmetic. They end at
`imem_req_o`, except retained Dadda, whose first endpoint is an IF fetch-result
register data-enable pin.

The core's generic PC/register/immediate operand selectors still feed the shared
EX input ports used by ALU, MUL/DIV and FPU. Native MUL/DIV decode always selects
RS1/RS2. A subsequent investigation can separate functional-unit operand wiring
so ALU-specific source selection cannot enter the multiplier's candidate cone,
while preserving the shared arithmetic slice. This is a new candidate for
measurement, not an added timing exception or an implemented change here.

Configurations, source hashes, structural JSON, SAT scripts/logs, regression
records, fixed-ELF CoreMark runs and physical reports are retained under
[`build/investigations/ex-operand-capture/`](../../../../build/investigations/ex-operand-capture/).
