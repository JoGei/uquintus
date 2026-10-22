# Instruction request bypass and replay capacity

The fetch engine now presents an allowed request combinationally when its
request holding slot is empty and transaction/completion capacity is available.
A preasserted grant accepts it on the first eligible edge. If grant is delayed,
the address is retained through permission changes and flush until grant.
Queued work can also start immediately when permission becomes available.
Idle address masking is removed; idle payload is unspecified.

The redirect/fetch pointer remains registered in IF. The two engine response
slots and downstream word FIFO remain registered. With immediate grant,
next-cycle response and no old-path bus work to drain, the first target word
is granted in cycle 1 after redirect and the instruction is available to IF/DE
in cycle 4, compared with cycle 5 before this change. Sustained fetch bandwidth
remains one word per clock. Protected fetches must resolve PMP before bus
presentation; denied requests still generate registered error tokens without OBI.

## Controlled workload

All points use RV32IMC, IF decompression, full forwarding, BP16/BTB16, a
single-cycle parallel multiplier, iterative divider with unroll 8, FF GPRs,
a two-word IF FIFO, and no PMP/FPU/XIF/debug. Only the packed instruction-data
budget per BTB entry varies: 0, 2, 4 or 6 halfwords. Generated complete configs
and method snapshots live under `build/investigations/ifetch-fast-imc/`.

Each executes the exact earlier CoreMark performance ELF, SHA-256
`5c8b82617b5f4a07369b1a69937287a78e1590df99bde75257bd947b373bca7b`,
with immediate grants, one-cycle instruction/data responses, immediate fence
acknowledgements and GCC 13.2.0 `-O2` RV32IMC software. The window retires
314,834 instructions. CRCs pass at every point. These short RTL runs are not
official CoreMark scores.

| Halfwords per entry | Instruction payload bits across 16 entries | Cycles | CPI |
| ---: | ---: | ---: | ---: |
| 0 | 0 | 527,043 | 1.6740 |
| 2 | 512 | 489,026 | 1.5533 |
| 4 | 1,024 | 471,311 | 1.4970 |
| 6 | 1,536 | 463,146 | 1.4711 |

The previous registered-request design at six halfwords took 478,021 cycles
(CPI 1.5183). Only `src/uquintus/uqu_ifetch.v` differs between that reference
and the new six-halfword run; ELF, parameters and memory schedule match.
The bypass saves 14,875 cycles (3.11%). Four halfwords with bypass is 1.40%
faster than the previous six-halfword point while reducing per-entry instruction
payload by one third. Six halfwords uses 1.73% fewer cycles than four with bypass.
Payload-bit counts exclude tags, validity/length counts, and the active replay
snapshot; physical cell area must be measured separately.

## Physical characterization

Sky130HD only, through placement and timing repair before CTS/routing. All
points use the same ORFS/Yosys/OpenROAD installations, speed mapping with ABC
wire-load estimates enabled and mapped buffers removed before placement.
The fixed target is 60 ns, with 4 ns input/output delays, reset arrival 0–1 ns,
0.1 ns input transition and clock uncertainty, and 0.01 pF output load.
The die is 1240 by 1240 um, the core 1200 by 1200 um, density 0.65, two tool
threads per point. Clock is ideal and interconnect RC is placement-estimated.

`T_min = 60 ns - full constrained-path setup slack`,
`F_max = 1000 / T_min` MHz, and estimated workload time is
`cycles * T_min / 1e6` ms. These include constrained I/O paths and are not
routed/signoff frequencies. Only points passing workload, setup/hold, electrical
and placement checks belong in the local area/runtime frontier.

## Placed results

All four points pass placement, setup/hold and electrical checks. The same
clock target and I/O constraints are used for every point.

| Halfwords | Placed cell area (um²) | T_min (ns) | Estimated F_max (MHz) | Estimated iteration time (ms) | Local area/runtime frontier |
| ---: | ---: | ---: | ---: | ---: | :---: |
| 0 | 278,232 | 53.091 | 18.836 | 27.981 | Yes |
| 2 | 337,938 | 52.782 | 18.946 | 25.812 | Yes |
| 4 | 376,087 | 55.327 | 18.074 | 26.076 | No |
| 6 | 437,435 | 53.746 | 18.606 | 24.892 | Yes |

At a common clock, six halfwords gives the lowest execution-cycle count. Using
each point's setup-derived clock estimate, six also gives the shortest workload
time. Two halfwords uses 22.7% less placed cell area than six, with 3.7% longer
estimated runtime. It is the compact candidate among the enabled replay points.
Four halfwords has more area and slightly longer estimated runtime than two,
so it is dominated in this measured area/runtime comparison despite lower CPI.
Zero remains the minimum-area endpoint. These are four individual placements,
not a statistical placement study or a selection of permanent Greek profiles.
No preset/default replay budget is changed by this characterization.

All full critical paths start at data-memory response status: `dmem_err_i`
for H=0/2/6 and `dmem_rvalid_i` for H=4, ending in EX MUL/DIV accumulator state.
The new imem address path is not the full critical path in these configurations.
This identifies data-response-to-EX control/state as a separate timing target;
this change does not attempt to repair that path. The earlier registered-fetch
reference is a controlled cycle comparison only; no matched before/after
physical run was made with the preceding LSU/WB revision held fixed.

Functional qualification includes 99 passing cases across 13 component,
subsystem, core and checked-ELF runs, plus all four native CoreMark CRC checks.
The checked six-halfword CoreMark execution matches native execution exactly:
463,146 window cycles, 314,834 retired instructions and identical BPU statistics.
The audit validates all eight benchmark/placement records against common RTL,
ELF, memory schedule, constraints, mapping libraries and tool identities.

## Reproduction and evidence

```sh
.venv/bin/python impl/asic/orfs/investigations/bpu_replay_sweep.py \
  --base-config config/rv32imc_bimodal_idata.yml \
  --candidates impl/asic/orfs/investigations/ifetch_request_candidates.yml \
  --name-prefix ifetch-fast-imc \
  --output build/investigations/ifetch-fast-imc \
  --elf <fixed-performance-program.elf> \
  --skip-ihp --clock-period 60 --workers 2 --jobs 2 \
  --bender <bender> --orfs-root <ORFS> --yosys <yosys> --openroad <openroad>
```

The experiment index contains CPI, area, timing, estimated runtime and plots,
with links to each immutable flow report. `experiment.json` records complete
inputs, `audit.json` checks consistent RTL/ELF/constraints/tools and qualification,
and `baseline-comparison.json` records the earlier six-halfword reference.
Component regressions cover immediate acceptance/grant, bounded streaming,
latency, delayed grant, permission release, protection, bus errors, persistent
canceled requests, concurrent results/requests and reset. Production IF tests
cover all compressed decoding paths, and full-core tests cover precise faults,
PMP, interrupts, prediction/replay and RVFI association.
