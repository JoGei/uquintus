# RV32IMC cumulative forwarding characterization

This study holds the branch system, ISA, multiplier, executable and physical
constraints fixed while adding operand bypasses one at a time. It is an
order-dependent ladder, not a search of all forwarding combinations or a
selection of Greek profiles.

## Frozen baseline

[`config/rv32imc_bimodal_idata.yml`](../../../../config/rv32imc_bimodal_idata.yml)
selects RV32IMC, 16 bimodal direction counters, 16 direct-mapped BTB entries,
six packed instruction-data halfwords per entry, and decompression in IF.
The GPR file uses flip-flops, the fetch FIFO holds two words, and operands are
resolved continuously without a DE retention buffer. U-mode is enabled;
PMP, FPU, XIF and debug are disabled.

`MUA_MUL: parallel` selects a dedicated combinational multiplier with a
single-cycle result. This is the parallel interpretation of “fully unrolled
multiplier”; it is not the iterative multiplier with factor 32. DIV remains
iterative with `MUA_MULDIV_ITERUNROLL: 8`, avoiding an incidental change to the
divider when selecting the multiplier implementation.

There is no WB-to-MEM operand bypass. Store base/data operands are resolved
in EX and carried into MEM. The hazard unit supplies DE and EX consumers.
WB-to-DE is implicit when `MUA_FORWARDING` is enabled; the other four paths
have independent switches.

| Step | Newly enabled path | Master | WB→EX | MEM→EX | MEM→DE | EX→DE |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | None; stall until register-file visibility | 0 | 0 | 0 | 0 | 0 |
| 1 | WB→DE | 1 | 0 | 0 | 0 | 0 |
| 2 | WB→EX | 1 | 1 | 0 | 0 | 0 |
| 3 | MEM→EX | 1 | 1 | 1 | 0 | 0 |
| 4 | MEM→DE | 1 | 1 | 1 | 1 | 0 |
| 5 | EX→DE | 1 | 1 | 1 | 1 | 1 |

The ordering leaves same-cycle EX-to-DE forwarding until last so its incremental
cycle saving can be compared with its longer arithmetic/branch timing path.
Marginal changes depend on which paths are already enabled.

## Software and implementation envelope

One CoreMark performance-profile ELF is built with GCC 13.2.0, `-O2`,
`-march=rv32imc_zicsr -mabi=ilp32`, the matching RV32IMC runtime, pinned CoreMark
sources and one iteration. All six configurations execute that exact ELF.
ELF SHA-256: `5c8b82617b5f4a07369b1a69937287a78e1590df99bde75257bd947b373bca7b`.
Disassembly contains compressed instructions and native MUL/DIVU/REMU.
This is a new executable; earlier RV32I/RV32IC CoreMark counts are not an
iso-binary comparison.

Native fast Verilator execution checks completion and the CoreMark CRCs.
Instruction/data memory grants are immediate, responses take one cycle, and
fence acknowledgements are immediate. The measured window excludes startup
and validation. Each configuration retires 314,834 window instructions.

Sky130HD measures all six configurations with the same
60 ns mapping target, fixed 4 ns input/output budgets, reset arrival 0–1 ns,
0.1 ns input transition/clock uncertainty and 0.01 pF output load. The die is
1240 × 1240 µm, the core is 1200 × 1200 µm and placement density is 0.65.
Speed mapping, ABC wire-load policy, buffer-removal policy and tools remain
fixed within the experiment. Area is placed logical cell area.

Timing uses placement-estimated wire RC and ideal clocks before CTS/routing.
`T_min = 60 ns − full constrained-path setup slack`; `F_max = 1000/T_min` MHz.
Estimated workload time is `cycles * T_min_ns / 1e6` milliseconds. This includes
I/O paths and is not routed/signoff frequency or a memory-system performance
measurement. A configuration qualifies only after passing workload, setup/hold,
electrical and placement checks.

The initial 40 ns Sky130 pass is preserved separately. The first three points
missed setup by 0.183–0.225 ns, with hold, electrical and placement checks
passing. Their worst paths run from `fence_ack_i` into the MUL/DIV accumulator
state. The main comparison therefore uses 60 ns for every point,
without changing external timing budgets. Do not mix the two
mapping targets into one area/runtime frontier.

## RTL cycle results

All six CRC checks passed and retired the same number of instructions.

| Step | Cycles | CPI | Cycle reduction from previous step |
| ---: | ---: | ---: | ---: |
| 0 | 893,465 | 2.838 | — |
| 1 | 770,091 | 2.446 | 13.8% |
| 2 | 693,969 | 2.204 | 9.9% |
| 3 | 646,727 | 2.054 | 6.8% |
| 4 | 615,785 | 1.956 | 4.8% |
| 5 | 604,991 | 1.922 | 1.8% |

Full forwarding reduces cycles by 32.3% relative to stall-only handling.
The final EX-to-DE path saves 10,794 cycles relative to step 4.

## Sky130 placement results

All six 60 ns placements pass setup/hold, electrical and placement checks.
The evidence audit passes all twelve joined benchmark/implementation records.

| Step | Placed cell area (µm²) | T_min (ns) | Estimated F_max (MHz) | Estimated CoreMark time (ms) |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 426,797 | 48.413 | 20.66 | 43.255 |
| 1 | 428,626 | 47.944 | 20.86 | 36.921 |
| 2 | 428,219 | 50.574 | 19.77 | 35.097 |
| 3 | 429,736 | 52.113 | 19.19 | 33.703 |
| 4 | 431,977 | 51.584 | 19.39 | 31.765 |
| 5 | 435,272 | 51.751 | 19.32 | 31.309 |

Full forwarding is fastest for this workload/envelope: 32.3% fewer cycles and
27.6% shorter estimated runtime than stall-only handling, with 2.0% more cell
area. Adding EX-to-DE after the other paths saves 1.8% of cycles; its 0.32%
period increase and 0.76% area increase leave a 1.44% estimated-runtime benefit.
The lowest-area point is step 0; step 1 has the highest frequency estimate.

Every full constrained worst path starts at `fence_ack_i` and ends in the
iterative divider's accumulator state. Thus EX-to-DE forwarding is not the
dominant endpoint in this M-enabled comparison. Forwarding and mapping still
change its fan-in, cells and loads. One placement per setting does not isolate
all such effects.

Frequency estimates depend on the optimization target: the tighter 40 ns pilot
mapped faster netlists that narrowly missed its target. The six 60 ns results
are a controlled trend comparison, not a per-configuration clock-period search
or the highest achievable frequency of each design. The rendered comparison
and standalone SVG plots are in `build/investigations/forwarding-rv32imc-60ns/`.

## Why full forwarding still has CPI 1.922

A passive diagnostic replay of step 5 uses the unchanged compiled Verilator
RTL archive. Only its C++ driver is rebuilt to observe existing internal
signals. It reproduces the original complete native outcome, start/stop
boundaries, BPU counters, 604,991 window cycles, 314,834 retirements and CRCs.

Empty-slot provenance tags follow the actual parent-owned pipeline-register
enable/next-valid signals. They attribute each non-retirement cycle once,
allowing overlapping upstream stalls to be hidden by older work. These are
operational bubble categories, not independent counterfactual speedups.

| Contribution | Cycles | Cycles / instruction |
| --- | ---: | ---: |
| Successful retirement | 314,834 | 1.000000 |
| LSU sequencing | 206,472 | 0.655812 |
| Redirect-recovery bubbles | 61,527 | 0.195427 |
| DE operand-dependency bubbles | 20,331 | 0.064577 |
| Other frontend supply bubbles | 1,824 | 0.005794 |
| Serialization | 3 | 0.000010 |
| Total | 604,991 | 1.921619 |

The measured code executes 54,381 loads, 14,443 stores and 9,396 multiplies.
ALU/MUL execution adds no EX completion-wait cycles. Although DIV/REM appear
in the executable, none executes inside this measured window.

Each of the 68,824 memory operations occupies MEM for four cycles even with
immediate grants and a one-cycle response:

| MEM cycle | LSU state at cycle start | Action |
| ---: | --- | --- |
| 1 | `ST_IDLE` | Accept the native request and capture address/data. |
| 2 | `ST_REQUEST` | Present and grant the OBI request. |
| 3 | `ST_RESPONSE` | Receive and register data/status. |
| 4 | `ST_RESULT` | Forward the registered result and transfer to WB. |

That is exactly `68,824 * 3 = 206,472` additional cycles, or 71.2% of the
290,157-cycle overhead. Memory operations are 21.86% of this workload, so
MEM occupancy alone gives a lower bound of `1 + 3 * 0.2186 ≈ 1.656` CPI,
before branch recovery and dependency bubbles. Forwarding cannot remove
that functional-unit occupancy cost. EX is blocked by downstream capacity in 145,479
cycles; those observations overlap the LSU cost and must not be added again.
Likewise, the raw 81,327 DE blocked-with-an-EX-slot observations are not an
additional cycle cost beyond the provenance accounting above.

The BPU observer records 13,131 DE correction redirects. A frontend bubble is
tagged as redirect recovery from a correction until the first subsequent IF
acceptance; later frontend gaps retain the ordinary supply tag. Propagating
those tags to empty WB slots yields the recovery contribution above. This is
not a fixed penalty for every branch or for a correctly predicted BTB hit.

The next throughput improvement should examine LSU acceptance/request timing
and turnover while preserving registered response data, precise side effects
and the existing one-outstanding policy. That implementation work is separate
from this fixed-RTL forwarding experiment. Diagnostic sources, a twelve-cycle
LSU example, `census.json` and its validation `audit.json` are retained under
`build/investigations/forwarding-rv32imc-60ns/cpi/`.

### Reference LSU pipeline structures

CV32E40P documents ideal aligned loads/stores at one-cycle throughput, with
request processing in EX and response handling in WB. It supports two
outstanding OBI transactions and still requires write responses. Its interface
omits `err`, so its bus-error behavior is not a template for uqu's precise
store-access exceptions. See the official
[pipeline manual](https://docs.openhwgroup.org/projects/cv32e40p-user-manual/en/latest/pipeline.html)
and [LSU manual](https://docs.openhwgroup.org/projects/cv32e40p-user-manual/en/latest/load_store_unit.html).

Default two-stage Ibex explicitly stalls loads and stores for at least one
response-wait cycle. With `WritebackStage=1`, its RTL allows the instruction to
leave ID/EX after request acceptance and waits for the response in WB. New
memory requests are allowed in the cycle the previous response arrives; a
next-cycle response therefore permits one-per-cycle throughput without a deep
request queue. This latter throughput statement follows from the RTL, rather
than the manual's two-stage timing table. See
[the pipeline manual](https://ibex-core.readthedocs.io/en/latest/03_reference/pipeline_details.html),
[ID-stage control](https://github.com/lowRISC/ibex/blob/master/rtl/ibex_id_stage.sv#L903)
and [WB completion](https://github.com/lowRISC/ibex/blob/master/rtl/ibex_wb_stage.sv#L95).

For uqu, the corresponding optimization is MEM request / WB response ownership:
grant transfers the pending instruction to WB; response completion is distinct
from request acceptance. The next MEM request may overlap a successful older
response, with younger side effects blocked on an older fault. The existing
registered-load-forwarding policy and response buffering under backpressure
must be respected. This is a proposed follow-up, not the implementation measured
in the sweep. A two-cycle bus transaction does not inherently require two
cycles of exclusive MEM-stage occupancy.

## Reproduction and evidence

```sh
make benchmark-build CONFIG=rv32imc_bimodal_idata BENCHMARK_PROFILE=performance \
  PYTHON=.venv/bin/python RISCV_CC="$RISCV_CC"
.venv/bin/python impl/asic/orfs/investigations/forwarding_sweep.py \
  --elf <the-built-RV32IMC-performance-program.elf> \
  --sdc impl/asic/orfs/investigations/standalone_60ns.sdc --clock-period 60 \
  --output build/investigations/forwarding-rv32imc-60ns \
  --platforms sky130hd \
  --bender "$BENDER" --orfs-root "$ORFS_ROOT" \
  --yosys "$YOSYS_EXE" --openroad "$OPENROAD_EXE" --workers 3 --jobs 2
make report PYTHON=.venv/bin/python
```

The actual SDC copy and generated complete configurations are retained in
`build/investigations/forwarding-rv32imc-60ns/`, along with `experiment.json`,
`summary.json`, `software.json`, disassembly, method snapshots, per-invocation
logs and the comparison `index.html`. `audit.json` checks all joins against the
same RTL, ELF, memory schedule, retired count and per-platform tools/libraries.
Raw reports remain in the normal `build/uquintus-fwd-imc-.../` hierarchy.
The runner reuses only compatible passed artifacts whose recorded inputs still
match the workspace.

The 40 ns results remain under `build/investigations/forwarding-rv32imc/` and
in their raw per-configuration implementation directories. They retain their
failed qualification rather than being relabelled as successful slower runs.
The three unfinished pilot points and the IHP jobs were stopped; IHP was
removed from scope at the user's request. Cancelled runs are explicitly skipped.

Rebuildable Verilator precompiled headers were removed only after their runs
passed. Byte-identical finalized ODB snapshots may be hard-linked to conserve
storage; their paths and bytes are preserved. Cleanup/deduplication manifests
retain this housekeeping evidence separately from measurements.
