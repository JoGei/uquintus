# IHP reset-arrival timing trial — 2026-10-22

These measurements predate D-308's conversion of hart identity to the `HART_ID`
parameter. They describe the retained netlists with a `hart_id_i` port; they are
historical evidence, not a timing estimate for the subsequent constant-ID RTL.

A 0–1 ns reset-arrival window improves the default placed Zfinx core's estimated
frequency from **61.23 to 64.27 MHz**, with unchanged cells and placement. All
four timing analyses pass setup, hold, slew, capacitance, fanout and placement
checks at the analyzed typical corner.

The critical setup path moves from `rst_ni` to `hart_id_i`, which retains its
4 ns input delay. Consequently the overall slack improvement is less than 3 ns:
another constrained input becomes limiting before the full reset-path margin
can be used.

## Controlled comparison

The input placements are the two cases from the
[physical placement comparison](ihp-placement.md). Each is reanalyzed at both
reset budgets, with no resynthesis, cell resizing, placement, or timing repair.

| Mapping | Reset maximum arrival, ns | Worst setup slack, ns | `T_min`, ns | Estimated Fmax, MHz | Critical input |
|---|---:|---:|---:|---:|---|
| Default ABC | 4 | +3.668873 | 16.331127 | 61.2328 | `rst_ni` |
| Default ABC | 1 | +4.441093 | 15.558907 | 64.2719 | `hart_id_i[10]` |
| ABC wire-load disabled | 4 | +3.319190 | 16.680810 | 59.9491 | `rst_ni` |
| ABC wire-load disabled | 1 | +3.660285 | 16.339715 | 61.2006 | `hart_id_i[11]` |

Both reset-budget cases explicitly use **0 ns minimum reset arrival**, so hold
analysis allows reset to change immediately after its launching edge. All other
input/output delays remain 4 ns; clock period remains 20 ns; input transition,
output loads, uncertainty, cell library, placement RC and ideal clock model are
unchanged. The 4 ns controls reproduce the earlier setup/Fmax results exactly.
The earlier experiment had an implicit 4 ns reset minimum as well; explicitly
checking the earlier 0 ns arrival introduces no hold failure here.

Worst hold slack remains +0.167433 ns for the default mapping and +0.170299 ns
for the alternative. Electrical and placement violation counts are zero in
every case. The default retains better overall timing in this trial; its Fmax
gain over its own 4 ns control is approximately 4.96%.

This is a constraint sensitivity experiment on existing implementations. It does
not show what reoptimizing for the new input budget would achieve, and it does
not qualify post-CTS, routed or multi-corner timing. Reset is still synchronous
and has no false-path or multicycle exception. A 0–1 ns budget requires the
integrating reset source to meet that arrival window relative to `core_clk`,
including the assumed source/clock relationship and slew.

## Applying the budget to future synthesis

```sh
make synth CONFIG=rv32i_zfinx TOP=core PLATFORM=ihp-sg13g2 \
  CLOCK_PERIOD_NS=20 RESET_INPUT_DELAY_NS=1
```

`RESET_INPUT_DELAY_NS` is an optional **maximum** delay in ns. When specified,
the generator emits a 0 ns minimum reset delay and the requested maximum.
When omitted, it preserves the original data-input budget for reset. The
resolved minimum/maximum reset delays are recorded in the synthesis context.
This experiment does not change the default globally.

The actual override used by both the generator and the reanalysis is:

```tcl
set_input_delay -min 0 -clock core_clk [get_ports rst_ni]
set_input_delay -max 1 -clock core_clk [get_ports rst_ni]
```

The shared implementation lives in `impl/asic/orfs/common/synth.py`. This is a flow
setting, not an ISA or microarchitecture parameter.

## Reproduction and artifacts

```sh
.venv/bin/python impl/asic/orfs/investigations/reset_timing.py \
  --source build/uquintus-rv32i_zfinx/orfs_ihp-sg13g2/place-compare-20261022T062833Z-fadc3c8e \
  --orfs-root /path/to/OpenROAD-flow-scripts \
  --openroad /path/to/openroad
make report PYTHON=.venv/bin/python
```

The measured run is under:

```text
build/uquintus-rv32i_zfinx/orfs_ihp-sg13g2/
  reset-timing-20261022T065641Z-3b2568d0/
    comparison.json
    original_reset4ns/, original_reset1ns/
    no_wireload_reset4ns/, no_wireload_reset1ns/
      constraints.sdc, config.yml, inputs.tcl, reset_timing.tcl
      timing.log, metrics.tsv, metrics.json, report.json
```

Each record retains source placed ODB/SDC, Liberty/RC, analysis script and tool
hashes. The shared report lists the four cases separately with stage
`placed_timing_reanalysis`, reset min/max arrivals and `placement_unchanged`.
`T_min` follows the [benchmarking definition](../../../../doc/uqu_spec.bench.md).
