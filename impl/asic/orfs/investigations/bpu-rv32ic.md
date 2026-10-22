# Selected RV32IC branch-system and packed-replay characterization

This follow-up measures a small candidate set after the halfword-capacity
change. It does not repeat the full RV32I Cartesian sweep or select Greek
profiles. Candidate choice uses the prior study's small-area and area/runtime
frontier, plus the new 96-bit packed prefix.

## Inputs and selection

[The candidate list](bpu_rv32ic_candidates.yml) fixes 13 points:

| Direction / BTB entries | Payload halfwords per entry |
| --- | --- |
| 2 / 2 | 0 |
| 4 / 4 | 0, 4 |
| 8 / 8 | 0, 4, 6, 8 |
| 16 / 8 | 0, 6, 8 |
| 16 / 16 | 0, 6, 8 |

All other parameters come from `config/rv32ic_bimodal_idata.yml`: RV32IC,
decompression in IF, FF GPRs, enabled forwarding, two fetched-word FIFO slots,
physical addressing and no PMP/FPU/XIF. Payload capacity is `16 * H` bits per
entry and in the active replay snapshot; H=6 is 96 bits, H=8 is 128 bits.
Instruction coverage varies with the mix of original 16-/32-bit encodings.

The expanded study crosses these 13 points with all three compressed
implementations: decompression in IF, decompression in DE, and direct compressed
decoding. This gives 39 configurations. Only `MUA_C_IMPL` and
`MUA_C_DECOMPRESS_STAGE` change between matched points. Direct compressed
decoding fixes the inactive decompressor-placement selector to `if`.
Original IF point names and input hashes permit reuse of the initial 13 runs;
DE and direct-decoder names add `-cde` and `-cdecode` respectively. The original
experiment, method snapshot and rendered comparison are preserved separately
under `build/investigations/bpu-rv32ic-initial/`.

Build one performance-profile CoreMark ELF with GCC 13.2.0, `-O2`, the RV32IC
integer runtime, one iteration and the same pinned sources/settings as before.
Its ELF attributes include `rv32i2p1_c2p0_zicsr2p0`; disassembly contains both
16- and 32-bit instructions. All candidates execute that exact ELF. The new
executable has its own identity: historical RV32I results are not an iso-binary
comparison or physical measurements of this packed-C RTL.

Instruction/data memory grant immediately and respond in one cycle; fence
acknowledgements are immediate. Fast native Verilator execution checks CRCs,
completion and the cycle/retirement window. This is workload validation, not a
replacement for architectural tests.

Physical characterization retains the previous standalone envelope: 40 ns
optimization target, fixed 4 ns input/output budgets, reset arrival 0–1 ns,
0.1 ns input transition/clock uncertainty and 0.01 pF output load. Use the same
tools, per-platform libraries, speed mapping and buffer policy, automatic pins,
1240 × 1240 µm die, 1200 × 1200 µm core and placement density 0.65. Timing uses
placement-estimated RC with an ideal clock before CTS/routing. Area is placed
logical cell area. Estimated workload time is `cycles * T_min_ns / 1e6` ms,
including all constrained timing paths, not just register-to-register paths.

The complete selected set is measured on Sky130. For each compressed
implementation, the IHP follow-up selects the smallest-area Sky130 candidate,
the shortest estimated-runtime candidate, and the latter's matching H=0
reference. It is a selected subset, not a complete
IHP frontier. Do not mix tool/constraint/input changes into these comparisons.

## Reproduction and evidence

```sh
make benchmark-build CONFIG=rv32ic_bimodal_idata BENCHMARK_PROFILE=performance \
  PYTHON=.venv/bin/python RISCV_CC="$RISCV_CC"
.venv/bin/python impl/asic/orfs/investigations/bpu_replay_sweep.py \
  --elf <the-built-RV32IC-performance-program.elf> \
  --base-config config/rv32ic_bimodal_idata.yml \
  --candidates impl/asic/orfs/investigations/bpu_rv32ic_candidates.yml \
  --c-variants decompr-if decompr-de cdecode \
  --name-prefix bpu-c --output build/investigations/bpu-rv32ic \
  --bender "$BENDER" --orfs-root "$ORFS_ROOT" \
  --yosys "$YOSYS_EXE" --openroad "$OPENROAD_EXE" --workers 4 --jobs 2
make report PYTHON=.venv/bin/python
```

Generated configs, SDC, method snapshot, per-invocation logs, `experiment.json`,
`summary.json` and the comparison `index.html` live under the selected output
directory. `software.json` and disassembly preserve the particular executable's
compiler/encoding evidence. Raw flow reports remain in the normal per-config
build hierarchy. All artifact identities and qualified joins are checked by
`audit.json`; failed physical qualification stays visible and does not enter
the local measured frontier.

To make room for this experiment, byte-identical immutable database snapshots
from the historical sweep were hard-linked. Their paths and bytes are unchanged;
`deduplication.json` records the paths, hashes and reclaimed storage. No source,
measurement, executable or timing evidence was discarded.

## Initial IF-decompression results

All 13 CoreMark candidates pass CRC checks and retire 757,486 instructions.
All 13 Sky130 candidates and all three selected IHP candidates also pass
placement, setup/hold and electrical checks. The initial study's archived
evidence audit passed all 29 records: 13 workload runs and 16 physical runs.
The following measurements were produced on 2026-10-22. B/T denotes direction
predictor/BTB entries; H denotes stored halfwords per target. A star marks the
local area/runtime frontier within this selected set.

| B/T | H | Cycles | CPI | Cell area (µm²) | T_min (ns) | Estimated time (ms) | Frontier |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 2/2 | 0 | 1,707,924 | 2.255 | 161,482 | 34.514 | 58.947 | ★ |
| 4/4 | 0 | 1,701,963 | 2.247 | 169,186 | 33.275 | 56.633 | ★ |
| 4/4 | 4 | 1,656,664 | 2.187 | 199,600 | 33.916 | 56.187 | ★ |
| 8/8 | 0 | 1,732,880 | 2.288 | 185,153 | 36.601 | 63.425 | |
| 8/8 | 4 | 1,411,799 | 1.864 | 238,351 | 34.629 | 48.889 | ★ |
| 8/8 | 6 | 1,380,194 | 1.822 | 268,067 | 33.768 | 46.607 | ★ |
| 8/8 | 8 | 1,377,599 | 1.819 | 276,528 | 35.321 | 48.658 | |
| 16/8 | 0 | 1,732,762 | 2.288 | 195,899 | 34.689 | 60.108 | |
| 16/8 | 6 | 1,380,084 | 1.822 | 280,652 | 35.774 | 49.371 | |
| 16/8 | 8 | 1,377,489 | 1.818 | 286,338 | 35.663 | 49.125 | |
| 16/16 | 0 | 1,717,846 | 2.268 | 214,931 | 34.786 | 59.758 | |
| 16/16 | 6 | 1,293,533 | 1.708 | 369,120 | 35.669 | 46.139 | ★ |
| 16/16 | 8 | 1,290,631 | 1.704 | 373,406 | 35.329 | 45.596 | ★ |

The useful compact candidate is **8/8, H=6**: it is only 2.2% slower than the
shortest estimated-runtime point (16/16, H=8), with 28.2% less whole-core cell
area. Relative to its own H=0 reference, it reduces cycles by 20.4% at a 44.8%
area increase. H=4 is another useful tradeoff: 11.1% less area than H=6, with
4.9% longer estimated time.

At 8/8, H=6 uses 25% fewer replay payload bits than H=8, loses only 0.19% in
cycle count, and in these placed netlists uses 3.1% less whole-core cell area
and has 4.2% shorter estimated time. Packing therefore produces a useful
96-bit capacity point; the payload saving is not a 25% saving for the entire
core. At 16/16, H=8 does remain on the local frontier: compared with H=6 it
adds 1.2% area for 1.2% shorter estimated time, while saving only 0.22% cycles.

Doubling only the direction table from 8 to 16 entries with an eight-entry BTB
saves just 110 cycles at either H=6 or H=8. At H=6, the eight-entry BTB hits on
82.1% of resolved control-flow instructions, versus 92.8% for 16/16; next-PC
prediction accuracy rises from 66.4% to 73.3%. The target capacity matters more
than extra direction entries for this executable. These observations depend on
its branch layout and aliasing, and do not imply monotonic gains across other
workloads.

The selected IHP results are:

| B/T | H | Cell area (µm²) | T_min (ns) | Estimated time (ms) |
| --- | ---: | ---: | ---: | ---: |
| 2/2 | 0 | 367,700 | 23.268 | 39.739 |
| 16/16 | 0 | 489,867 | 22.794 | 39.156 |
| 16/16 | 8 | 835,246 | 23.320 | 30.097 |

At 16/16 on IHP, replay reduces estimated runtime by 23.1% versus H=0 at a
70.5% cell-area increase. The 16/16 H=8 point has the shortest estimated time
among these three measurements. The compact 8/8 H=6 point was not measured
on IHP, so this subset cannot establish whether Sky130's compact tradeoff
also holds there.

Sky130's limiting paths all end at instruction-memory address outputs and
start at `fence_ack_i`, except 16/16 H=8, which starts at `irq_software_i`.
These are complete frontend/control interface paths, not isolated predictor
lookup delays. The figures describe single placed netlists optimized at 40 ns,
with ideal clocks and estimated wires; they are not routed maximum-frequency
claims. No default or Greek profile is changed by this single-workload study.
IHP's selected H=0 paths likewise start at `fence_ack_i`; its H=8 path starts
at `irq_external_i`. All three end at instruction-memory address outputs.

## Compressed-implementation comparison

All 39 Sky130 points pass physical qualification and all 39 workload runs pass
CRC checks. Every matched triple has exactly the same cycle and retirement
counts, so compressed-implementation runtime differences come from physical
timing rather than CPI changes. The initial table's stars and conclusions
describe the 13 IF points; the expanded HTML recomputes the frontier across all
39 configurations.

The generated comparison distinguishes IF, DE and direct decoding with circle,
square and triangle outlines. It shows frequency versus area, full-path and
register-to-register timing, and matched `T_min` changes relative to IF.
H=0 rows provide references without replay storage. This helps separate the
cost of each compressed-instruction route from its interaction with replay;
it does not isolate packed versus unpacked storage, which would require a
matched RTL implementation comparison. Historical RV32I results also differ
in executable and RTL identity.

The existing IF measurements already argue against replay packing as the sole
frequency explanation: 8/8 H=0 has `T_min=36.601 ns`, versus `33.768 ns` for
H=6. Its no-replay netlist still contains the compressed-instruction fetch
path. The H=6 placed critical path starts at `fence_ack_i`, passes through
named nets `u_ex.u_alu.computed_result[0]` and `de_next_pc[31]`, and ends at
`imem_addr_o[3]`. It therefore spans execution, forwarding/DE next-PC selection,
and fetch control; the complete timed path is preserved in that run's
`timing/placed_pre_cts/full_max.rpt`. This is a path observation, not a proof
that a specific RTL block caused the historical difference.

The matched **8/8, H=6** Sky130 measurements are complete. Each retires the same
757,486 instructions in 1,380,194 cycles (CPI 1.822):

| Compressed implementation | Cell area (µm²) | T_min (ns) | F_max (MHz) | Estimated time (ms) |
| --- | ---: | ---: | ---: | ---: |
| Decompress in IF | 268,067 | 33.768 | 29.61 | 46.607 |
| Decompress in DE | 270,965 | 35.542 | 28.14 | 49.055 |
| Direct compressed decoder | 273,590 | 36.583 | 27.34 | 50.491 |

Moving or replacing decompression does not recover frequency at this compact
point. IF has the smallest area and shortest period of the three measured
netlists. All three full-path limits run from `fence_ack_i` to instruction-memory
address outputs. Other table/replay capacities may favor a different route;
the completed 16/16 H=6 DE point, for example, reaches 29.67 MHz and 43.601 ms
at 375,381 µm².

The complete matched Sky130 frequency comparison is below (MHz, full
constrained-path estimates):

| B/T | H | Decompress IF | Decompress DE | Direct compressed decoder |
| --- | ---: | ---: | ---: | ---: |
| 2/2 | 0 | 28.97 | 28.40 | 29.12 |
| 4/4 | 0 | 30.05 | 29.01 | 29.19 |
| 4/4 | 4 | 29.48 | 28.63 | 29.41 |
| 8/8 | 0 | 27.32 | 29.83 | 28.77 |
| 8/8 | 4 | 28.88 | 28.21 | 28.14 |
| 8/8 | 6 | 29.61 | 28.14 | 27.34 |
| 8/8 | 8 | 28.31 | 28.41 | 28.45 |
| 16/8 | 0 | 28.83 | 27.11 | 27.88 |
| 16/8 | 6 | 27.95 | 27.45 | 28.81 |
| 16/8 | 8 | 28.04 | 28.55 | 28.95 |
| 16/16 | 0 | 28.75 | 29.21 | 27.69 |
| 16/16 | 6 | 28.04 | 29.67 | 27.90 |
| 16/16 | 8 | 28.31 | 28.14 | 28.84 |

DE improves the period relative to IF at 5 of 13 points, with matched period
changes ranging from −8.4% to +6.3%. Direct decoding improves it at 6 of 13
points, ranging from −5.0% to +8.3%. Neither route provides a consistent
frequency improvement. All 39 estimates fall between 27.11 and 30.05 MHz;
the highest frequency remains IF at 4/4 H=0. The placement change therefore
does not produce a broad recovery of frequency under this timing envelope.
These are single placed netlists, not repeated or routed measurements.

The shortest estimated workload time across all 39 points is **DE, 16/16,
H=6**: 43.601 ms, 29.67 MHz and 375,381 µm². The compact **IF, 8/8, H=6**
point uses 28.6% less area at 6.9% longer estimated time. Direct decoding adds
two low-area points to the local frontier (2/2 H=0 and 4/4 H=0), but none of
its replay-enabled points enters that frontier in this selected set.

The Sky130 critical full paths still start at `fence_ack_i`, except the original
IF 16/16 H=8 point (`irq_software_i`). They all end at instruction-memory
address outputs, except direct decoding at 16/16 H=6 (`imem_req_o`). This
common control/fetch timing scope remains relevant across all three routes.

An RTL inspection suggests a control-to-datapath follow-up: fence completion
affects WB readiness in `uqu_pipeline_ctrl`; CSR result availability in
`uqu_stage_wb` depends on retirement; `uqu_hazard` uses availability to select
EX operands/readiness; and `uqu_alu` qualifies arithmetic inputs with request
acceptance. Together with EX-to-DE forwarding, these dependencies warrant
inspection of the mapped critical cone. This is a structural hypothesis,
not an isolated causal measurement or justification for a false-path constraint.

The IHP extension passes all nine selected points, with three reused IF
results and six new DE/direct-decoder measurements:

| C implementation | B/T | H | Cell area (µm²) | T_min (ns) | F_max (MHz) | Estimated time (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Decompress IF | 2/2 | 0 | 367,700 | 23.268 | 42.98 | 39.739 |
| Decompress IF | 16/16 | 0 | 489,867 | 22.794 | 43.87 | 39.156 |
| Decompress IF | 16/16 | 8 | 835,246 | 23.320 | 42.88 | 30.097 |
| Decompress DE | 2/2 | 0 | 378,140 | 23.083 | 43.32 | 39.424 |
| Decompress DE | 16/16 | 0 | 487,711 | 21.692 | 46.10 | 37.263 |
| Decompress DE | 16/16 | 6 | 822,057 | 23.588 | 42.39 | 30.512 |
| Direct compressed decoder | 2/2 | 0 | 377,685 | 23.267 | 42.98 | 39.739 |
| Direct compressed decoder | 16/16 | 0 | 487,778 | 23.176 | 43.15 | 39.812 |
| Direct compressed decoder | 16/16 | 8 | 847,456 | 23.044 | 43.40 | 29.741 |

The fastest selected IHP runtime is **direct decoding, 16/16, H=8**. Against
the matched IF point, it is 1.2% faster at 1.5% more cell area. Sky130's best
runtime candidate (DE, 16/16, H=6) uses 1.6% less IHP area than IF H=8, with
1.4% longer estimated time. At 16/16 H=0, DE instead improves IHP frequency
from 43.87 to 46.10 MHz and slightly reduces area. Route ordering therefore
depends on the capacity and platform; the selected subset does not establish
a full IHP frontier or include the compact 8/8 H=6 point.

IHP's DE H=6 full-path limit runs from `fence_ack_i` to a BTB data flip-flop;
the other selected limits run from fence/interrupt inputs to instruction-memory
address outputs. The final audit passes **87 records**: 39 same-ELF benchmark
runs, 39 Sky130 runs and nine IHP runs. No default or Greek profile is changed.

The subsequent [matched ISA_C timing diagnosis](bpu-c-timing.md) adds two
RV32I controls on the same current RTL. It confirms a C penalty without
replay and locates the H=8 worst-path delay increase downstream of the shared
EX ALU result, in the combined DE/frontend control path.
