# Inferred versus Dadda multiplier with divider unroll 1

This comparison changes only the multiplier implementation. It avoids the
unroll-factor mismatch in the earlier `rv32im_dadda` trial, which used the
default eight-step iterative divider and was not comparable with the recent
RV32IMC/unroll-1 configuration.

## Fixed configuration and flow

- Reference: `config/rv32imc_bimodal_idata_parallel_div1.yml`, `MUA_MUL: parallel`.
- Candidate: `config/rv32imc_bimodal_idata_dadda_div1.yml`, `MUA_MUL: dadda`.
- Every other hardware parameter is identical: RV32IMC, divider unroll **1**,
  all forwarding paths enabled, continuous operand resolution, FF GPR file,
  IF decompression, BP16/BTB16/H6, two-word instruction buffer, no fetch bypasses,
  U-mode enabled, no PMP, FPU, XIF or debug, HART_ID zero.
- Both multipliers complete in one EX computation cycle. DIV/REM takes 35 cycles.
- Fresh full-core Sky130 HD speed mapping and placement/timing repair for both
  points, using the same RTL, tools, libraries and buffering policy.
- Clock target **20 ns**, data input/output budgets **4 ns**, reset arrival
  **0–1 ns**, input transition and clock uncertainty **0.1 ns**, output load
  **0.01 pF**. The generated standalone evaluation profile is used.
- Fixed 1240×1240 µm die, 1200×1200 µm core, placement density 0.65, two tool
  threads per run. Timing uses ideal clocks and placement-estimated RC before
  CTS or routing; the results are not routed/signoff frequencies.

Use the normal externally provisioned tool environment described in
[ASIC flows](../../README.md). Reproduce with:

```sh
make impl CONFIG=rv32imc_bimodal_idata_parallel_div1 TOP=core PLATFORM=sky130hd \
  CLOCK_PERIOD_NS=20 RESET_INPUT_DELAY_NS=1 JOBS=2
make impl CONFIG=rv32imc_bimodal_idata_dadda_div1 TOP=core PLATFORM=sky130hd \
  CLOCK_PERIOD_NS=20 RESET_INPUT_DELAY_NS=1 JOBS=2
make report
```

Each implementation run retains its mapped and placed timing summaries,
register-region paths, netlists, cell counts, constraints, configuration,
source hashes and tool identities. The controlled-pair input manifest and
comparison artifacts are under `build/investigations/daddamul-div1/`.

## Software and functional checks

The complete core component regression passes for the new RV32IMC Dadda preset.
CoreMark uses the exact same cached performance-profile ELF for both points,
with immediate memory grants, next-cycle responses and the existing fast
native Verilator harness. The cached software suite contains the performance
profile only; select it explicitly when reusing this suite:

```sh
make benchmark-run CONFIG=rv32imc_bimodal_idata_parallel_div1 \
  BENCHMARK=coremark BENCHMARK_PROFILE=performance \
  BENCHMARK_REUSE_SUITE=build/uquintus-rv32imc_bimodal_idata/sw/benchmark/coremark/suite.json
make benchmark-run CONFIG=rv32imc_bimodal_idata_dadda_div1 \
  BENCHMARK=coremark BENCHMARK_PROFILE=performance \
  BENCHMARK_REUSE_SUITE=build/uquintus-rv32imc_bimodal_idata/sw/benchmark/coremark/suite.json
```

The first attempt requested both software profiles and correctly failed the
suite for the unavailable validation profile; each performance workload itself
passed. The explicit performance-only reruns provide the selected comparison.
No missing validation ELF was treated as an RTL failure or a passed suite.

| Multiplier | Window cycles | Window retired instructions | CPI | CoreMark CRC checks |
| --- | ---: | ---: | ---: | --- |
| Inferred parallel | 463,144 | 314,834 | 1.471074 | Pass |
| Structural Dadda | 463,144 | 314,834 | 1.471074 | Pass |

Equal cycle counts are expected for two single-cycle implementations with the
rest of the configuration and memory model fixed. These are RTL cycle
measurements, not official CoreMark scores. Physical area and period determine
the difference in this comparison.

## Fresh synthesis and placement results, 2026-10-23

The controlled-pair audit verifies that only `MUA_MUL` differs, all common input
hashes match, the generated SDC is byte-identical, and tool/library identities
and buffering settings agree. Tools are Yosys 0.63 (70a11c6bf) and OpenROAD
26Q2-9-gd34d035725, with Sky130 HD TT 25°C / 1.8 V timing libraries.
CoreMark ELF SHA-256 is
`af8fe6b9ff4bf31306354de0a84b919b67b961dfbffe6a9053e62b069ad0a89e`.

Mapped preplacement estimates:

| Multiplier | Cell area (µm²) | Setup WNS (ns) | Estimated Tmin (ns) |
| --- | ---: | ---: | ---: |
| Inferred parallel | 411,168.1 | −10.950 | 30.950 |
| Structural Dadda | 403,891.1 | −17.544 | 37.544 |

Placed results after timing repair:

| Multiplier | Logical cell area (µm²) | Setup WNS (ns) | Estimated Tmin (ns) | Estimated Fmax (MHz) |
| --- | ---: | ---: | ---: | ---: |
| Inferred parallel | 477,536.7 | −12.346 | 32.346 | 30.916 |
| Structural Dadda | 465,367.6 | −10.885 | 30.885 | 32.378 |

`Tmin = 20 ns − setup WNS` and `Fmax = 1000 / Tmin` for the fixed mapped/placed
circuit and retained I/O budgets. These are estimates from the whole constrained
core, not an isolated multiplier delay or a routed/signoff frequency. Area is
logical Liberty cell area, including inserted logic/buffers, excluding
physical-only cells; do not substitute the LEF-based area printed in flow logs.

Dadda is **2.55% smaller** and its estimated required period is **4.52% shorter**
(**4.73% higher estimated frequency**) after placement repair. This is one
controlled pair at one mapping target; it does not establish a globally optimal
configuration. Preplacement timing ranked the points differently, illustrating
why the placement result is needed before choosing between them.

**Neither configuration meets the 20 ns setup target.** Both runs are correctly
recorded as failed implementations for setup only. Both pass hold (worst slack
+0.305 ns), electrical slew/capacitance/fanout checks (zero violations), and
placement legality. The target was not relaxed to qualify either result.

The placed whole-core worst paths are:

- Inferred: `dmem_rvalid_i` → `imem_req_o`, setup slack −12.346 ns.
- Dadda: `dmem_err_i` → `imem_req_o`, setup slack −10.885 ns.

Worst internal register paths also involve control: WB CSR address state → IF
fetch-address registers (−7.817 ns inferred, −6.630 ns Dadda). With unroll fixed
at 1, the limiting reports no longer identify the eight-step divider chain from
the unrelated initial preset. The next timing investigation should trace the
memory-response, precise-exception/CSR and fetch-request control dependencies.
These endpoint reports do not isolate the multiplier's intrinsic propagation
delay, and moving multiplication into MEM alone is not justified by this pair.

## Follow-up: path sensitization audit

The [gate-level path audit](memory-fetch-path.md) finds that both reported first
worst paths contain multiplication and DE control-flow logic, with mutually
exclusive validity/forwarding conditions. Two-snapshot Boolean checks cannot
sensitize either entire route, while each source can affect the endpoint through
other logic. The quoted periods are therefore conservative graph-based STA
estimates dominated by these routes, not established functional Fmax values.
The original failure records remain unchanged; no timing exception was added.
Timed-hazard assessment, structural cleanup and further path analysis are needed
before claiming 20 ns closure.

## Retained evidence

- [Comparison JSON](../../../../build/investigations/daddamul-div1/comparison.json)
  and [compact table](../../../../build/investigations/daddamul-div1/comparison.md).
- [Inferred implementation](../../../../build/uquintus-rv32imc_bimodal_idata_parallel_div1/orfs_sky130hd/impl-core-20261023T122300Z-5d45327a/report.json).
- [Dadda implementation](../../../../build/uquintus-rv32imc_bimodal_idata_dadda_div1/orfs_sky130hd/impl-core-20261023T122300Z-a40978bc/report.json).
- [CoreMark comparison manifests](../../../../build/investigations/daddamul-div1/benchmarks-performance.json).
- [Merged HTML synthesis view](../../../../build/report/synthesis/index.html).

Each implementation directory contains both `timing/mapped_preplacement/` and
`timing/placed_pre_cts/`, including `summary.json`, full path reports and all
register-region paths. Raw records retain failed-target status and diagnostics.
