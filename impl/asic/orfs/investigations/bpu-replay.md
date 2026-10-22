# BPU target-instruction replay characterization

This bounded experiment compares the bimodal predictor, direct-mapped
BTB and optional target-instruction sequences. It does not select Greek profiles
or perform the deferred general configuration search.

The results below describe the **historical fixed-instruction-slot RTL**, before
the halfword-capacity/packed-storage change. Historical depth `D` counted 32-bit
slots. The current `MUA_BTB_IDATA_HWORDS=2*D` preserves that byte budget for
RV32I; with C, instructions are packed and coverage varies with their lengths.
The preceding PPA numbers are not measurements of the new packed RTL.

## Fixed inputs and matrix

The 80 points independently cross direction-counter capacity 2/4/8/16, BTB capacity
2/4/8/16 and instruction-data depth 0/1/2/4/8. This includes the 16/16 configurations
at every depth and asymmetric table sizes. All other hardware parameters come
from `config/rv32i_bimodal_idata.yml`: RV32I, FF GPRs, enabled forwarding,
physical addressing and no PMP/FPU/XIF. A depth of four covers the tested ideal
RV32I continuation-refill interval. Depth eight tests whether retaining a longer
sequence still helps under the same one-cycle memory assumptions; slower-memory
experiments remain separate.

Use exactly one existing CoreMark performance ELF for every point. The native
Verilator backend validates its CRCs and completion, measures the same retired
workload window, and records instruction counts and passive BPU statistics.
Instruction and data memory both grant immediately and respond in one cycle.
This is workload validation, rather than a replacement for checked ISA tests.

The first Sky130 pilot targeted 20 ns. It completed placement but retained
5.680 ns of negative setup slack, with hold and electrical checks passing.
The comparison therefore uses a common 40 ns optimization target while keeping
the original fixed I/O budgets: 4 ns input/output delays, reset arrival 0–1 ns,
0.1 ns input transition/clock uncertainty, and 0.01 pF output loads. The experiment
supplies its SDC explicitly; the generic flow labels supplied SDCs `integration`,
but these are standalone characterization assumptions, not a SoC timing contract.
The 20 ns pilot is retained separately and excluded from the comparison.

All implementations use the existing speed mapping/wire-load/buffer-removal
policy, automatic pins, a 1240 × 1240 µm die, a 1200 × 1200 µm core and placement
density 0.65. Area means placed logical cell area, not the fixed die footprint.
Timing uses placement-estimated RC with an ideal clock, before CTS and routing.
`T_min` and estimated maximum frequency retain the definitions in
[the benchmarking specification](../../../../doc/uqu_spec.bench.md).
Estimated workload time is `workload_cycles * T_min_ns / 1e6` milliseconds.
It is a setup-derived estimate, not a demonstrated silicon operating point.

## Current helper and historical evidence

Run the current bounded helper with externally provisioned tools:

```sh
.venv/bin/python impl/asic/orfs/investigations/bpu_replay_sweep.py \
  --elf <existing-performance-program.elf> \
  --bender "$BENDER" --orfs-root "$ORFS_ROOT" \
  --yosys "$YOSYS_EXE" --openroad "$OPENROAD_EXE" \
  --workers 3 --jobs 2
make report PYTHON=.venv/bin/python
```

The helper calls the existing Make benchmark and implementation targets. It
writes complete configurations, constraints, separate logs for each invocation,
a measured-method source snapshot, `experiment.json`, `summary.json` and an HTML scatter/table view under
`build/investigations/bpu-replay-hwords/`. The current matrix crosses capacities
2/4/8/16 and halfword budgets 0/2/4/8/16, naming points `bpu-b<B>-t<T>-h<H>`.
It has not been physically measured as part of the packing change. Historical
reports and the measured-method snapshot remain under
`build/investigations/bpu-replay/`, with their original names and units; do not
retag those results as new halfword measurements. Raw results remain in each configuration's
normal `build/uquintus-<configuration>/` hierarchy and are collected by the
project report. Cached runs are reused only when configuration/context and
recorded input hashes match. `--benchmark-only`, `--skip-ihp` and `--summary-only`
permit phased execution and inspection; the default runs the full matrix on
Sky130, then selected candidates on IHP.

The IHP subset includes the smallest-area Sky130 point, the fastest estimated
Sky130 runtime, and its matching uncached reference with identical table sizes.
Previously measured IHP anchors are retained when extending the matrix, subject
to the same cache validation. It is not an exhaustive IHP
frontier. Failed qualification remains visible and is excluded from candidate
selection. Workload, timing corner, constraints, tool versions and source hashes
must accompany all comparisons.

## Historical fixed-slot results (2026-10-22)

All 80 CoreMark runs pass CRC validation and retire exactly 757,486 workload
instructions from the same ELF. All 80 Sky130 placements pass legality, setup,
hold and electrical checks at the common 40 ns target. This extends the initial
36-point matrix, reusing its unchanged measurements and adding 44 points.
The 16/16 depth-8 configuration also passes the full BPU component regression
and the directed IF instruction-replay test.
All five selected IHP placements pass the same qualification checks. The final
evidence audit verifies 165 joined records (80 benchmark plus 85 implementation
records), their parameter identities, common RTL/workload, memory schedule,
constraints, and per-platform tool/library identities. A redundant IHP rerun
was cancelled after the identical point qualified; that interrupted run is
marked skipped and is excluded from the comparison and audit.

The local Sky130 area/runtime frontier contains these seven points:

| Direction / BTB entries | Data depth | Workload cycles | Placed cell area µm² | T_min ns | Estimated time ms |
| --- | --- | --- | --- | --- | --- |
| 2 / 2 | 0 | 1,680,668 | 158,037 | 31.583 | 53.081 |
| 4 / 2 | 0 | 1,680,668 | 160,956 | 31.020 | 52.134 |
| 4 / 4 | 2 | 1,646,795 | 191,400 | 30.684 | 50.530 |
| 8 / 8 | 2 | 1,417,190 | 226,401 | 31.527 | 44.680 |
| 8 / 8 | 4 | 1,321,048 | 250,021 | 32.954 | 43.534 |
| 16 / 8 | 4 | 1,321,359 | 262,821 | 31.777 | 41.989 |
| 16 / 16 | 8 | 1,280,224 | 432,291 | 32.481 | 41.584 |

These are local points for this workload and implementation context, not the
project's deferred Greek profiles. The smallest measured design is 2/2 with
replay disabled. The smallest setup-derived period is the 4/4 depth-2 point;
the shortest estimated workload time is 16/16 with depth 8. Relative to 16/8
depth 4, that point uses 64.5% more area for only 1.0% less estimated runtime.

For an isolated replay comparison, retain 8/8 table capacities:

| Data depth | Workload cycles | Placed cell area µm² | T_min ns | Estimated time ms |
| --- | --- | --- | --- | --- |
| 0 | 1,709,621 | 181,245 | 32.512 | 55.584 |
| 1 | 1,596,093 | 207,896 | 32.080 | 51.202 |
| 2 | 1,417,190 | 226,401 | 31.527 | 44.680 |
| 4 | 1,321,048 | 250,021 | 32.954 | 43.534 |
| 8 | 1,321,048 | 299,512 | 33.038 | 43.645 |

Depth 2 reduces estimated runtime by 19.6% versus depth zero at 24.9% more cell
area. Going from depth 2 to depth 4 adds another 10.4% area for 2.6% less
estimated runtime. Depth 2 is therefore a useful performance/area candidate;
depth 4 improves on it with diminishing returns. Depth 8 adds 19.8% more area
than depth 4 and no cycle reduction, with a slightly longer timing estimate.

The added 16/16 table configurations measure as follows:

| Data depth | Workload cycles | Placed cell area µm² | T_min ns | Estimated time ms |
| --- | --- | --- | --- | --- |
| 0 | 1,703,569 | 210,841 | 32.288 | 55.005 |
| 1 | 1,569,849 | 258,661 | 34.415 | 54.026 |
| 2 | 1,385,792 | 286,542 | 33.903 | 46.982 |
| 4 | 1,280,224 | 332,785 | 33.179 | 42.476 |
| 8 | 1,280,224 | 432,291 | 32.481 | 41.584 |

Depths 4 and 8 have identical cycle counts for **all 16 table-size pairs** in
this experiment. More instructions come from replay at depth 8, but that does
not remove additional execution stalls with these one-cycle memories. At 16/16,
depth 8 adds 29.9% area over depth 4; its 2.1% lower estimated runtime comes
entirely from the shorter timing estimate of this particular mapped and placed
netlist, rather than fewer cycles. Do not interpret that difference as an
intrinsic timing advantage of deeper storage.

Moving from 8/8 to 16/16 at depth 4 saves 3.1% of cycles, costs 33.1% more area,
and reduces estimated runtime by 2.4%. The 16/8 depth-4 point instead retains
almost the same cycle count as 8/8 and gains estimated runtime through timing,
at 5.1% more area. These physical timing differences need confirmation across
clock targets and repeated implementation runs before selecting a default.

Table coverage matters as much as replay depth. At BTB capacity 8, both
2-entry and 4-entry direction tables achieve only about 46% raw direction
accuracy in this program; eight direction entries reach about 73%. The BTB
control-flow hit rate stays near 86% in all three cases. At depth 4, replay
accounts for about 14% of retired instructions with the smaller direction
tables versus 43.9% with eight entries. A target-table hit alone does not ensure
useful taken steering or replay. The current tagged direction-table policy
and this executable's address/outcome pattern determine those results.

The selected IHP comparison is:

| Direction / BTB entries | Data depth | Placed cell area µm² | T_min ns | Estimated time ms |
| --- | --- | --- | --- | --- |
| 2 / 2 | 0 | 357,518 | 22.766 | 38.262 |
| 8 / 8 | 0 | 411,853 | 22.007 | 37.624 |
| 8 / 8 | 4 | 570,215 | 23.059 | 30.462 |
| 16 / 16 | 0 | 489,204 | 22.759 | 38.772 |
| 16 / 16 | 8 | 990,599 | 24.747 | 31.681 |

At fixed 8/8 capacities, IHP depth 4 costs 38.5% more cell area and reduces
estimated runtime by 19.0% versus depth zero. This is a selected subset; no
complete IHP frontier is claimed. At 16/16, depth 8 costs 102.5% more area and
reduces estimated runtime by 18.3% versus its matching depth-zero reference.
However, IHP's 8/8 depth-4 point is both smaller and faster than 16/16 depth 8:
the point with the shortest Sky130 estimated runtime is not the best IHP point.

The setup-derived limits include all constrained I/O paths. Sky130's limiting
paths start at `fence_ack_i` or `irq_software_i` and end at instruction-memory
address/request outputs; the selected IHP limits come from interrupt/control
inputs to instruction-memory outputs or BTB data storage. These are frontend/global-control interface
paths, rather than a direct measurement of predictor-table lookup delay.
The JSON summary also retains register-to-register-only period estimates and
critical endpoints. They must not be substituted for the full-path timing
scope in the runtime comparison.

The reported periods belong to these particular netlists optimized at 40 ns;
a tighter synthesis target can trade area for a different period estimate,
as the separate 20 ns pilot illustrates. Clock-target exploration, routed/CTS
qualification, power measurement, repeated physical runs and additional
workloads remain separate follow-ups. No default or Greek preset is selected
from this single CoreMark study.

The [selected RV32IC follow-up](bpu-rv32ic.md) measures the subsequent packed
halfword replay implementation with a compressed CoreMark executable. It uses
13 candidates rather than repeating this full matrix; its RTL and executable
identities are separate from the measurements above.
