# Shared instruction and trap-value pipeline storage

## Decision

EX, MEM and WB each store one 32-bit `*_instr_tval_q` word instead of separate
original-instruction and exception-value words. The existing saved exception
flag tags the contents. A token without an inherited exception needs its
original encoding for any later illegal-instruction report, including CSR
legality in WB. Once an exception exists, its trap value takes priority and
the hardware no longer needs that token's original encoding.

This removes three 32-bit banks without adding tags, cycles or reset state.
Per-stage PCs and resolved successor PCs are unchanged. IF/DE still carries the
original and selected expanded/native instruction needed by compressed decoding.
The architectural contract is [D-318 and Section 3.13](../../../../docs/uqu_spec.arch.md#313-native-core-integration).

The SystemVerilog core wrapper preserves original encodings in three passive
observation registers using the same enabled valid replacements. RVFI and FP
observations use this history, including on trapped instructions whose hardware
word now contains an address or zero. No observation register drives the core;
Bender target `rtl` excludes the wrapper. The core's instruction identity
remains visible in simulation without requiring duplicate silicon storage.

## Lifecycle and fault handling

| Boundary | Captured word |
| --- | --- |
| DE/EX | DE trap value if DE reports an exception; otherwise original fetched instruction. |
| EX/MEM | EX trap value if EX reports an exception; otherwise the held EX instruction word. |
| MEM/WB | MEM trap value if MEM reports an exception; otherwise the held MEM instruction word. |

The saved exception flag travels on the same edge as the word. A boundary writes
only for an enabled valid replacement, so stalls preserve both contents and
meaning. Flush/reset invalidates occupied slots without clearing payload banks.
EX/MEM/WB stage interfaces are unchanged: instruction and inherited trap-value
inputs receive the same shared word, and the existing exception priority chooses
the meaningful interpretation. Inherited faults suppress local execution and
architectural effects.

An LSU request accepted in MEM carries its instruction into WB. A later bus
fault gets its address from the independently owned LSU response state. A CSR
instruction retains its original encoding through WB legality checking. Neither
case overwrites instruction bits before its final possible consumer.

## Storage audit

Yosys process lowering, memory mapping, flattening and optimization count actual
generic flip-flop output bits. They exclude all verification instrumentation.
Both elaborations have zero combinational strongly connected components.

| Configuration | Before | Shared payload | Difference |
| --- | ---: | ---: | ---: |
| RV32I (`rv32i`) | 2,711 FF bits | 2,615 FF bits | −96 |
| RV32IMC, split MUL, BP/BTB16/16 H6 | 6,379 FF bits | 6,283 FF bits | −96 |

The corresponding Sky130 mapped RV32IMC netlists contain 6,364 and 6,268
flip-flop cells. Mapping folds some additional constant bits compared with the
generic audit; the change is still exactly 96 cells, all enabled FFs.

## Matched Sky130 synthesis

The comparison uses `rv32imc_bimodal_idata_dadda_mac_div1`: two-row PP/Dadda/BK
with late C in MEM/EX2, DIV factor one, all forwarding enabled, continuous DE
resolution, FF GPRs, IF decompression, BP16/BTB16 and six packed target halfwords.
Both runs use Sky130 HD TT at 1.80 V/25 °C, the same Yosys/ABC/OpenROAD tools and
qualified ORFS scripts, 20 ns clock, 4 ns general I/O delays, reset arrival
0–1 ns, 0.1 ns clock uncertainty and 0.01 pF output load. Only processor file
`src/uquintus/uqu_core.v` changes in the synthesis inputs.

Measurements below are mapped, unplaced estimates with ideal interconnect.
They must not be compared directly with repaired-placement frequency numbers
from the multiplier or fetch timing investigations. No false paths, multicycle
exceptions or new timing constraints are introduced by this experiment.

| Mapped, unplaced metric | Separate words | Shared word |
| --- | ---: | ---: |
| Standard-cell area | 409,288.79 µm² | 405,083.51 µm² |
| Cell count | 33,911 | 33,459 |
| Flip-flop count | 6,364 | 6,268 |
| Setup WNS at 20 ns | −6.633 ns | −13.943 ns |
| Estimated Fmax | 37.55 MHz | 29.46 MHz |

Mapped area falls 1.03%. The raw timing loss is dominated by high-fanout
register-enable distribution, not a new long arithmetic computation: the
candidate's worst `dmem_rvalid_i` → MEM multiplier `high_q` enable path has
9.54 ns and 16.23 ns cell delays at gates driving 198 and 233 loads. The
baseline's worst path also has an 18.63 ns delay at a 277-load enable gate.
Placement and timing repair must buffer these nets before judging whether the
storage change is useful. Both raw estimates violate the 20 ns target.

## Repaired placement result

Both mapped netlists were resumed through ORFS placement and final setup/hold
repair using the same 1,240 × 1,240 µm die, 1,200 × 1,200 µm core, density 0.65
and two workers. The original mapped netlists were reused rather than remapped;
`place.py` retains the exact commands and reads the standard project timing and
physical observations. Synthesis records remain separate from these placement
results.

| Repaired placement, before CTS | Separate words | Shared word |
| --- | ---: | ---: |
| Standard-cell area | 443,849.44 µm² | 444,950.49 µm² |
| Buffer count | 4,782 | 5,341 |
| Minimum estimated clock period | 20.684 ns | 20.701 ns |
| Estimated Fmax | 48.345 MHz | 48.306 MHz |
| Setup WNS at 20 ns | −0.684 ns | −0.701 ns |
| Hold worst slack | +0.305 ns | +0.305 ns |
| Placement/electrical violations | 0 | 0 |

The 96-FF saving survives mapping, but it is **not a net physical area win in
this run**. Repaired area increases 0.248%, while Fmax changes −0.081%. Extra
buffering offsets the mapped area saving. The clock-period difference is
0.017 ns; no repeatability distribution was measured. Both
runs still miss the 50 MHz setup target, so their physical report status is
failed even though placement, hold and electrical checks pass. These are ideal
clock, placement-estimated RC results before CTS/routing and are not signoff.

The remaining worst path ends at `imem_req_o` in both designs: MUL/DIV state
starts the baseline path and saved WB kind starts the candidate path. The
unplaced enable-net penalty is repaired; the shared trap-value word does not
become the worst endpoint. Keep this change reviewable as a functional storage
cleanup, without claiming a placed PPA improvement or pruning per-stage PCs.

## Verification

All 189 full-core cases pass: 21 suites in each of RV32I, the split-MUL RV32IMC
preset, both alternate compressed strategies, PMP, XIF, DE operand retention,
iterative MUL and Zfinx. This includes the new `trap_payload` suite. It holds an
older load response while a younger misaligned access waits, then alternates
instruction-, address- and zero-valued traps, late CSR rejection, load/store bus
errors and a reset epoch with an instruction-access fault. C-enabled runs add a
reserved compressed instruction with its original halfword encoding. The
retirement/RVFI oracle checks original instruction bits against the independent
program image on synchronous traps as well as successful retirement.

The common Python suite runs 137 cases, with two optional-library skips and no
failures. Both generic core elaborations pass the zero-SCC structural check.

## Reproduction and evidence

```sh
make test PYTHON=.venv/bin/python COMPONENT=core CONFIG=rv32i
make test PYTHON=.venv/bin/python COMPONENT=core \
  CONFIG=rv32imc_bimodal_idata_dadda_mac_div1 TEST=trap_payload
make synth PYTHON=.venv/bin/python CONFIG=rv32imc_bimodal_idata_dadda_mac_div1 \
  PLATFORM=sky130hd CLOCK_PERIOD_NS=20 RESET_INPUT_DELAY_NS=1 JOBS=2 \
  ORFS_ROOT="$ORFS_ROOT" YOSYS_EXE="$YOSYS_EXE" OPENROAD_EXE="$OPENROAD_EXE"
```

`build/investigations/pipeline-payload/` retains the baseline source snapshot,
generic storage-audit scripts/netlists, paired synthesis logs, regression logs
and machine-readable `comparison.json` and `placement-comparison.json`. The
baseline snapshot is taken before the change; its initial source revision is
recorded in `baseline-git.txt`.

| Evidence | Run identifier |
| --- | --- |
| Baseline synthesis | `synth-core-20261024T220201Z-0ffa337c` in the baseline snapshot's build directory. |
| Shared-word synthesis | `synth-core-20261024T220416Z-c9d7d93d`. |
| Published baseline placement | `impl-core-20261024T220201Z-0ffa337c-payload-baseline`. |
| Published shared-word placement | `impl-core-20261024T220416Z-c9d7d93d-payload-candidate`. |

Published placement records under `build/uquintus-rv32imc_bimodal_idata_dadda_mac_div1/orfs_sky130hd/`
retain their original synthesis provenance and link to full source databases in
`source-run.txt`. The shared report includes both physical comparisons.
